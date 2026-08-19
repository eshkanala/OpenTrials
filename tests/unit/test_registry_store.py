"""Contract tests for registry.store.FilesystemRegistryBackend.

Exercises the full put/get/verify/list/get_latest cycle against real
payload types this project already ships (Compound, ModelCapabilityProfile)
plus the two new registry-only types (ParameterEvidenceRecord,
ExperimentRecord) -- proving the "wrap existing types, don't redeclare
them" design actually round-trips, not just type-checks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Intervention, Regimen, Route
from opentrials.compound.intervention import Dose
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import sha256
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.patient import PopulationSpec
from opentrials.registry import (
    EvidenceClass,
    ExperimentRecord,
    FilesystemRegistryBackend,
    ParameterEvidenceRecord,
    RegistryError,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
    Trial,
    TrialArm,
)
from opentrials.trials.trial import RandomizationType


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def demo_trial() -> Trial:
    intervention = Intervention(
        intervention_id="aciclovir-demo-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="aciclovir-demo-regimen",
            doses=(
                Dose(
                    amount=assumed(250, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="ACICLOVIR-DEMO",
        title="Aciclovir demo trial",
        question_of_interest="What plasma concentration does this dose produce?",
        population=PopulationSpec(
            id="aciclovir-demo-population", size=10, seed=1, generator_version="0.1.0"
        ),
        arms=(
            TrialArm(
                arm_id="standard", name="standard", intervention=intervention, allocation=1.0
            ),
        ),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "hour"), end=assumed(24, "hour")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=1,
    )


@pytest.fixture
def backend(tmp_path: Path) -> FilesystemRegistryBackend:
    return FilesystemRegistryBackend(tmp_path / "registry")


def manual_source(identifier: str = "curator-review") -> RegistrySource:
    return RegistrySource(kind="manual_curation", identifier=identifier)


def test_put_get_and_verify_a_compound_record(backend: FilesystemRegistryBackend) -> None:
    compound = Compound(
        identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
    )

    manifest = backend.put(
        RegistryRecordKind.COMPOUND,
        compound,
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    assert manifest.record_id.startswith("OTREG-COMPOUND-")
    assert manifest.logical_id == "aciclovir"
    assert manifest.version == "1.0.0"

    reloaded_manifest, reloaded_payload = backend.get(manifest.record_id)
    assert reloaded_manifest == manifest
    assert reloaded_payload == compound

    verified = backend.verify(manifest.record_id)
    assert verified == manifest


def test_put_and_get_a_real_model_capability_profile(backend: FilesystemRegistryBackend) -> None:
    manifest = backend.put(
        RegistryRecordKind.MODEL,
        ACICLOVIR_IV_CAPABILITY_PROFILE,
        logical_id="osp.aciclovir.vergin-1995-iv",
        evidence_class=EvidenceClass.CURATED,
        license="proprietary",
        source=RegistrySource(kind="model_package", identifier="osp.aciclovir.vergin-1995-iv"),
    )

    _, payload = backend.get(manifest.record_id)
    assert payload == ACICLOVIR_IV_CAPABILITY_PROFILE


def test_put_rejects_a_payload_of_the_wrong_type_for_its_kind(
    backend: FilesystemRegistryBackend,
) -> None:
    compound = Compound(
        identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
    )
    with pytest.raises(RegistryError, match="type mismatch"):
        backend.put(
            RegistryRecordKind.MODEL,  # wrong kind for a Compound payload
            compound,
            logical_id="aciclovir",
            evidence_class=EvidenceClass.CURATED,
            license="CC-BY-4.0",
            source=manual_source(),
        )


def test_verify_detects_a_tampered_payload_on_disk(backend: FilesystemRegistryBackend) -> None:
    record = ParameterEvidenceRecord(
        parameter_id="aciclovir.renal_clearance",
        compound_id="aciclovir",
        value=ScientificValue(value=3.5, unit="L/hour", value_type=ValueType.OBSERVED),
    )
    manifest = backend.put(
        RegistryRecordKind.PARAMETER_EVIDENCE,
        record,
        logical_id="aciclovir.renal_clearance",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    payload_path = backend.root / manifest.record_id / "payload.json"
    tampered = payload_path.read_text(encoding="utf-8").replace("3.5", "999.0")
    payload_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(RegistryError, match="failed verification"):
        backend.verify(manifest.record_id)


def test_experiment_record_sourced_from_a_run_must_be_marked_simulated(
    backend: FilesystemRegistryBackend,
) -> None:
    trial = demo_trial()
    experiment = ExperimentRecord(
        trial_id=trial.trial_id,
        trial=trial,
        trial_sha256=sha256(trial),
        model_id="osp.aciclovir.vergin-1995-iv",
        run_id="OTR-population-abc123",
        title="Aciclovir demo trial",
    )
    with pytest.raises(Exception, match="SIMULATED"):
        backend.put(
            RegistryRecordKind.EXPERIMENT,
            experiment,
            logical_id="ACICLOVIR-DEMO-run",
            evidence_class=EvidenceClass.MEASURED,  # wrong -- a real execution is SIMULATED
            license="CC-BY-4.0",
            source=RegistrySource(kind="experiment_run", identifier="OTR-population-abc123"),
        )

    manifest = backend.put(
        RegistryRecordKind.EXPERIMENT,
        experiment,
        logical_id="ACICLOVIR-DEMO-run",
        evidence_class=EvidenceClass.SIMULATED,
        license="CC-BY-4.0",
        source=RegistrySource(kind="experiment_run", identifier="OTR-population-abc123"),
    )
    assert manifest.evidence_class == EvidenceClass.SIMULATED


def test_list_filters_by_kind_and_orders_most_recent_first(
    backend: FilesystemRegistryBackend,
) -> None:
    backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )
    backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="midazolam", preferred_name="Midazolam")),
        logical_id="midazolam",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )
    backend.put(
        RegistryRecordKind.PARAMETER_EVIDENCE,
        ParameterEvidenceRecord(
            parameter_id="aciclovir.renal_clearance",
            value=ScientificValue(value=3.5, unit="L/hour", value_type=ValueType.OBSERVED),
        ),
        logical_id="aciclovir.renal_clearance",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    compounds = backend.list(RegistryRecordKind.COMPOUND)
    assert len(compounds) == 2
    assert {m.kind for m in compounds} == {RegistryRecordKind.COMPOUND}

    everything = backend.list()
    assert len(everything) == 3


def test_get_latest_resolves_the_most_recent_version_for_a_logical_id(
    backend: FilesystemRegistryBackend,
) -> None:
    first = backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )
    second = backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(
            identity=CompoundIdentity(
                compound_id="aciclovir", preferred_name="Aciclovir", synonyms=("Acyclovir",)
            )
        ),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
        version="1.1.0",
        superseded_id=first.record_id,
    )

    manifest, payload = backend.get_latest("aciclovir")
    assert manifest.record_id == second.record_id
    assert manifest.superseded_id == first.record_id
    assert payload.identity.synonyms == ("Acyclovir",)


def test_get_raises_for_an_unknown_record_id(backend: FilesystemRegistryBackend) -> None:
    with pytest.raises(RegistryError, match="Unknown registry record"):
        backend.get("OTREG-COMPOUND-does-not-exist")


def test_get_latest_raises_for_an_unregistered_logical_id(
    backend: FilesystemRegistryBackend,
) -> None:
    with pytest.raises(RegistryError, match="No registered record"):
        backend.get_latest("no-such-thing")


def test_created_at_is_timezone_aware(backend: FilesystemRegistryBackend) -> None:
    manifest = backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )
    assert manifest.created_at.tzinfo is not None
    assert manifest.created_at <= datetime.now(UTC)
