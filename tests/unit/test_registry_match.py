"""Contract tests for sdk.registry_match's deterministic, rules-based matcher.

No LLM anywhere in this module -- every assertion here checks a concrete,
auditable rule (compound identity, route agreement, evidence-count
scoring), matching the module's own "no fuzzy inference" discipline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Intervention, Regimen, Route
from opentrials.compound.intervention import Dose
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.registry import (
    EvidenceClass,
    FilesystemRegistryBackend,
    ParameterEvidenceRecord,
    RegistrySource,
)
from opentrials.registry.schema import RegistryRecordKind
from opentrials.sdk.registry_match import (
    match_compound,
    match_datasets_for_compound,
    match_parameter_evidence,
    match_summary,
)
from opentrials.validation import DatasetRole, ObservedDataset, ObservedPkObservation, ObservedStudy


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def manual_source(identifier: str = "test") -> RegistrySource:
    return RegistrySource(kind="manual_curation", identifier=identifier)


def aciclovir_intervention(route: Route = Route.INTRAVENOUS) -> Intervention:
    return Intervention(
        intervention_id="aciclovir-test-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="aciclovir-test-regimen",
            doses=(
                Dose(amount=assumed(250, "mg"), route=route, administration_time=assumed(0, "min")),
            ),
        ),
    )


def aciclovir_dataset(route: Route = Route.INTRAVENOUS) -> ObservedDataset:
    return ObservedDataset(
        dataset_id="OTOBS-test-aciclovir",
        role=DatasetRole.CALIBRATION,
        study=ObservedStudy(
            study_id="test-study",
            title="Test aciclovir study",
            evidence_ids=("EV-test",),
            population_description="Test population",
            intervention=aciclovir_intervention(route),
        ),
        observations=(
            ObservedPkObservation(
                observation_id="obs-1",
                subject_or_population_id="pop-1",
                time=assumed(0, "hour"),
                value=assumed(10, "mg/L"),
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
                evidence_ids=("EV-test",),
            ),
        ),
        license="CC-BY-4.0",
        source_identifier="test",
        provenance_ids=("EV-test",),
    )


@pytest.fixture
def backend(tmp_path: Path) -> FilesystemRegistryBackend:
    return FilesystemRegistryBackend(tmp_path / "registry")


def test_match_compound_finds_an_exact_identity_match(backend: FilesystemRegistryBackend) -> None:
    backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    match = match_compound("aciclovir", backend=backend)

    assert match is not None
    assert match.compatibility.value == "HIGH"
    assert "aciclovir" in match.reasons[0]


def test_match_compound_returns_none_for_an_unregistered_compound(
    backend: FilesystemRegistryBackend,
) -> None:
    assert match_compound("midazolam", backend=backend) is None


def test_match_datasets_upgrades_to_high_when_route_agrees(
    backend: FilesystemRegistryBackend,
) -> None:
    backend.put(
        RegistryRecordKind.DATASET,
        aciclovir_dataset(Route.INTRAVENOUS),
        logical_id="test-dataset",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    matches = match_datasets_for_compound(
        "aciclovir", backend=backend, target_route="INTRAVENOUS"
    )

    assert len(matches) == 1
    assert matches[0].compatibility.value == "HIGH"
    assert any("route matches" in r for r in matches[0].reasons)


def test_match_datasets_downgrades_to_low_when_route_disagrees(
    backend: FilesystemRegistryBackend,
) -> None:
    backend.put(
        RegistryRecordKind.DATASET,
        aciclovir_dataset(Route.INTRAVENOUS),
        logical_id="test-dataset",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    matches = match_datasets_for_compound("aciclovir", backend=backend, target_route="ORAL")

    assert len(matches) == 1
    assert matches[0].compatibility.value == "LOW"
    assert any("differs" in r for r in matches[0].reasons)


def test_match_datasets_excludes_a_different_compound(backend: FilesystemRegistryBackend) -> None:
    backend.put(
        RegistryRecordKind.DATASET,
        aciclovir_dataset(),
        logical_id="test-dataset",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    assert match_datasets_for_compound("midazolam", backend=backend) == []


def test_match_parameter_evidence_requires_at_least_one_real_criterion(
    backend: FilesystemRegistryBackend,
) -> None:
    backend.put(
        RegistryRecordKind.PARAMETER_EVIDENCE,
        ParameterEvidenceRecord(
            parameter_id="aciclovir.renal_clearance",
            compound_id="aciclovir",
            target="renal.glomerular_filtration_rate",
            value=assumed(3.5, "L/hour"),
        ),
        logical_id="aciclovir.renal_clearance",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    # No overlap at all -- must not be returned.
    assert match_parameter_evidence(compound_id="midazolam", backend=backend) == []

    # One matching criterion -- MODERATE.
    compound_only = match_parameter_evidence(compound_id="aciclovir", backend=backend)
    assert len(compound_only) == 1
    assert compound_only[0].compatibility.value == "MODERATE"

    # Two matching criteria -- HIGH.
    both = match_parameter_evidence(
        compound_id="aciclovir", target="renal.glomerular_filtration_rate", backend=backend
    )
    assert len(both) == 1
    assert both[0].compatibility.value == "HIGH"


def test_match_parameter_evidence_matches_on_canonical_parameter_id(
    backend: FilesystemRegistryBackend,
) -> None:
    backend.put(
        RegistryRecordKind.PARAMETER_EVIDENCE,
        ParameterEvidenceRecord(
            parameter_id="aciclovir.renal_clearance",
            compound_id="aciclovir",
            value=assumed(3.5, "L/hour"),
        ),
        logical_id="aciclovir.renal_clearance",
        evidence_class=EvidenceClass.MEASURED,
        license="CC-BY-4.0",
        source=manual_source(),
    )

    # A different canonical id -- must not match on that criterion alone with no others.
    assert (
        match_parameter_evidence(canonical_parameter_id="hepatic_clearance", backend=backend) == []
    )

    both = match_parameter_evidence(
        compound_id="aciclovir", canonical_parameter_id="renal_clearance", backend=backend
    )
    assert len(both) == 1
    assert both[0].compatibility.value == "HIGH"
    assert any("Canonical parameter identity matches" in r for r in both[0].reasons)


def test_match_summary_is_json_friendly(backend: FilesystemRegistryBackend) -> None:
    backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=manual_source(),
    )
    match = match_compound("aciclovir", backend=backend)
    assert match is not None

    summary = match_summary(match)

    assert summary["compatibility"] == "HIGH"
    assert summary["kind"] == "COMPOUND"
    assert isinstance(summary["reasons"], list)
