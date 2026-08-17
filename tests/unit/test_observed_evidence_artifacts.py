from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.storage.observed import (
    OBSERVATION_COLUMNS,
    ObservedArtifactStore,
    semantic_observations_hash,
)
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def dataset() -> ObservedDataset:
    intervention = Intervention(
        intervention_id="aciclovir-iv-250-mg",
        compound=Compound(
            identity=CompoundIdentity(
                compound_id="aciclovir",
                preferred_name="Aciclovir",
                canonical_smiles="C1=NC2=C(N1CO)NC(=NC2=O)NCCO",
            ),
            molecular_weight=observed(225.2, "g/mol"),
            evidence_ids=("evidence-aciclovir",),
        ),
        regimen=Regimen(
            regimen_id="aciclovir-iv-single-dose",
            doses=(
                Dose(
                    amount=observed(250, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=observed(0, "minute"),
                ),
            ),
        ),
        evidence_ids=("evidence-regimen",),
    )
    return ObservedDataset(
        dataset_id="OTOBS-aciclovir-001",
        role=DatasetRole.EXTERNAL_VALIDATION,
        study=ObservedStudy(
            study_id="study-aciclovir-iv-001",
            title="Aciclovir intravenous pharmacokinetics",
            evidence_ids=("evidence-study-001",),
            population_description="Adults with normal renal function",
            intervention=intervention,
            assay_context="Plasma aciclovir measured by LC-MS/MS.",
        ),
        observations=(
            ObservedPkObservation(
                observation_id="observation-001",
                subject_or_population_id="subject-001",
                time=observed(30, "minute"),
                value=observed(4.2, "mg/L"),
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
                assay="LC-MS/MS",
                condition="fasted",
                evidence_ids=("evidence-observation-001",),
            ),
        ),
        license="CC-BY-4.0",
        source_identifier="doi:10.0000/aciclovir-iv",
        provenance_ids=("provenance-001",),
    )


def test_observed_evidence_artifact_reloads_and_verifies(tmp_path: Path) -> None:
    store = ObservedArtifactStore(tmp_path / "observed")
    directory = store.create_observed_dataset("OTOBS-aciclovir-001")
    manifest = store.write_observed_dataset(dataset())

    reloaded = store.verify_observed_dataset("OTOBS-aciclovir-001")
    table = pq.read_table(directory / "observations.parquet")

    assert reloaded == manifest
    assert table.column_names == list(OBSERVATION_COLUMNS)
    assert table.num_rows == 1
    assert manifest.role is DatasetRole.EXTERNAL_VALIDATION
    assert manifest.license == "CC-BY-4.0"
    assert manifest.provenance_ids == ("provenance-001",)
    assert manifest.study.evidence_ids == ("evidence-study-001",)
    assert manifest.dataset_canonical_sha256.startswith("sha256:")
    assert (
        '"schema":"opentrials.observed-evidence-artifact"'
        in (directory / "manifest.json").read_text()
    )


def test_observed_evidence_artifact_is_immutable_and_rejects_mismatched_id(tmp_path: Path) -> None:
    store = ObservedArtifactStore(tmp_path / "observed")
    store.create_observed_dataset("OTOBS-aciclovir-001")
    artifact = dataset()
    store.write_observed_dataset(artifact)

    with pytest.raises(FileExistsError, match="already exist"):
        store.write_observed_dataset(artifact)
    with pytest.raises(ValueError, match="must match"):
        store.write_observed_dataset(artifact, dataset_id="OTOBS-other")


def test_semantic_observation_hash_normalizes_equivalent_numeric_cells() -> None:
    integer_rows = ({"observation_id": "1", "time_value": 60, "value": 1},)
    float_rows = ({"observation_id": "1", "time_value": 60.0, "value": 1.0},)

    assert semantic_observations_hash(
        ("observation_id", "time_value", "value"), integer_rows
    ) == semantic_observations_hash(("observation_id", "time_value", "value"), float_rows)
