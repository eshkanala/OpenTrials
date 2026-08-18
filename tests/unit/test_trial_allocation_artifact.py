from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.patient import PopulationSpec
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
    TrialArmAllocationArtifactStore,
)
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    RandomizationType,
    TimeWindow,
    Trial,
    TrialArm,
)

COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-allocation-test"


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def population_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {"IndividualId": i, "Gender": "FEMALE", "Organism|Age": 20.0 + i} for i in range(10)
    )


def build_population(tmp_path: Path) -> PopulationArtifactStore:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="allocation-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "allocation-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=10,
        column_names=COLUMNS,
        rows=population_rows(),
    )
    return store


def arm(arm_id: str, dose_mg: float, allocation: float) -> TrialArm:
    intervention = Intervention(
        intervention_id=f"aciclovir-{arm_id}",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id=f"{arm_id}-regimen",
            doses=(
                Dose(
                    amount=assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                    infusion_duration=assumed(10, "min"),
                ),
            ),
        ),
    )
    return TrialArm(arm_id=arm_id, name=arm_id, intervention=intervention, allocation=allocation)


def two_arm_trial() -> Trial:
    return Trial(
        trial_id="OTALLOC-TEST-TRIAL",
        title="Allocation artifact test",
        question_of_interest="Does OTALLOC persist a deterministic partition?",
        population=PopulationSpec(id="alloc-demo", size=10, seed=1, generator_version="0.1.0"),
        arms=(arm("low", 125.0, 0.5), arm("high", 250.0, 0.5)),
        randomization=RandomizationType.PARALLEL,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=42,
    )


def test_write_and_verify_allocation(tmp_path: Path) -> None:
    populations = build_population(tmp_path)
    store = TrialArmAllocationArtifactStore(tmp_path / "allocations", population_store=populations)
    store.create_allocation("OTALLOC-001")

    manifest = store.write_allocation(
        "OTALLOC-001", trial=two_arm_trial(), generation_id=GENERATION_ID
    )

    assert manifest.total_population == 10
    assert manifest.arm_counts == {"low": 5, "high": 5}
    assert manifest.allocation.rows == 10
    assert store.verify_allocation("OTALLOC-001") == manifest

    low_rows = store.read_rows_for_arm("OTALLOC-001", "low")
    high_rows = store.read_rows_for_arm("OTALLOC-001", "high")
    assert len(low_rows) == 5
    assert len(high_rows) == 5
    assert {row["source_row_index"] for row in low_rows} | {
        row["source_row_index"] for row in high_rows
    } == set(range(10))

    with pytest.raises(FileExistsError, match="already exist"):
        store.write_allocation("OTALLOC-001", trial=two_arm_trial(), generation_id=GENERATION_ID)


def test_verify_allocation_detects_population_row_tampering(tmp_path: Path) -> None:
    populations = build_population(tmp_path)
    store = TrialArmAllocationArtifactStore(tmp_path / "allocations", population_store=populations)
    store.create_allocation("OTALLOC-002")
    store.write_allocation("OTALLOC-002", trial=two_arm_trial(), generation_id=GENERATION_ID)

    # Directly overwrite the persisted population Parquet with different content;
    # verify_allocation must recompute row hashes against the live table and reject.
    population_manifest = populations.read_manifest(GENERATION_ID)
    parquet_path = tmp_path / "populations" / GENERATION_ID / population_manifest.individuals.path
    table = pq.read_table(parquet_path)
    tampered = table.set_column(
        table.column_names.index("Organism|Age"),
        "Organism|Age",
        [[999.0] * table.num_rows],
    )
    pq.write_table(tampered, parquet_path, compression="zstd")

    with pytest.raises(ValueError, match="does not match its manifest|does not match the verified"):
        store.verify_allocation("OTALLOC-002")
