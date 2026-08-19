"""Contract tests for sdk.curation -- the Registry curation pipeline.

Uses minimal fake connectors (no OSP, no network) mirroring the pattern
``test_evidence_connector_contract.py`` already established, so this
module's real behavior (candidate persistence, checklist gating,
ineligible-outcome visibility, accept/reject) is proven independent of the
two real bundled connectors' own OSP dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    DataConnectorRunResult,
    IneligibleEvidenceCandidateError,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.registry import EvidenceClass, FilesystemRegistryBackend
from opentrials.sdk import curation as sdk_curation
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


class FakeEligibleConnector:
    """A minimal, fully synthetic connector that always succeeds."""

    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id="test.fake-eligible", version="0.0.1")

    def fetch(self) -> RawSnapshot:
        return RawSnapshot(
            content=b'{"rows": [1]}',
            media_type="application/json",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
        evidence = Evidence(
            id="EV-fake-001",
            source_type=EvidenceSourceType.PUBLIC_DATASET,
            source_identifier="fake-source-001",
            license="CC0",
        )
        intervention = Intervention(
            intervention_id="fake-intervention",
            compound=Compound(identity=CompoundIdentity(compound_id="fake", preferred_name="Fake")),
            regimen=Regimen(
                regimen_id="fake-regimen",
                doses=(
                    Dose(
                        amount=observed(1, "mg"),
                        route=Route.INTRAVENOUS,
                        administration_time=observed(0, "minute"),
                    ),
                ),
            ),
        )
        dataset = ObservedDataset(
            dataset_id="OTOBS-fake-001",
            role=DatasetRole.CALIBRATION,
            study=ObservedStudy(
                study_id="fake-study",
                title="Fake study",
                evidence_ids=(evidence.id,),
                population_description="Synthetic",
                intervention=intervention,
            ),
            observations=(
                ObservedPkObservation(
                    observation_id="fake-obs-001",
                    subject_or_population_id="fake-subject",
                    time=observed(0, "minute"),
                    value=observed(1.0, "mg/L"),
                    analyte="fake",
                    matrix="plasma",
                    fraction="total",
                    measurement="concentration",
                    evidence_ids=(evidence.id,),
                ),
            ),
            license="CC0",
            source_identifier="fake-source-001",
            provenance_ids=(evidence.id,),
        )
        return DataConnectorRunResult(
            identity=self.identity,
            source=SourceDescriptor(
                accession="fake-source-001", license="CC0", retrieved_at=snapshot.retrieved_at
            ),
            raw_snapshot=snapshot,
            transformation_provenance=(TransformationStep(description="Parsed fake rows."),),
            evidence=EvidenceSet(evidence=(evidence,)),
            dataset=dataset,
        )


class FakeIneligibleConnector:
    """A connector whose normalize() always refuses -- mirrors Laskin 1982's own behavior."""

    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id="test.fake-ineligible", version="0.0.1")

    def fetch(self) -> RawSnapshot:
        return RawSnapshot(
            content=b"{}",
            media_type="application/json",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
        raise IneligibleEvidenceCandidateError(
            "no recoverable body weight for weight-normalized dose"
        )


def test_create_candidate_from_connector_persists_a_reviewable_candidate(tmp_path: Path) -> None:
    result = sdk_curation.create_candidate_from_connector(
        FakeEligibleConnector(), root=tmp_path / "curation"
    )
    assert isinstance(result, sdk_curation.CurationCandidate)
    assert result.outcome == sdk_curation.CurationOutcome.PENDING
    assert result.dataset.dataset_id == "OTOBS-fake-001"

    reloaded = sdk_curation.load_candidate(result.candidate_id, root=tmp_path / "curation")
    assert reloaded.candidate_id == result.candidate_id
    assert reloaded.dataset == result.dataset


def test_create_candidate_from_connector_records_ineligibility_visibly(tmp_path: Path) -> None:
    result = sdk_curation.create_candidate_from_connector(
        FakeIneligibleConnector(), root=tmp_path / "curation"
    )
    assert isinstance(result, sdk_curation.IneligibleCandidateRecord)
    assert result.connector_id == "test.fake-ineligible"
    assert "body weight" in result.reason

    listed = sdk_curation.list_ineligible(root=tmp_path / "curation")
    assert len(listed) == 1
    assert listed[0].record_id == result.record_id
    # And it must not also appear as a reviewable candidate.
    assert sdk_curation.list_candidates(root=tmp_path / "curation") == ()


def make_candidate(tmp_path: Path) -> sdk_curation.CurationCandidate:
    result = sdk_curation.create_candidate_from_connector(
        FakeEligibleConnector(), root=tmp_path / "curation"
    )
    assert isinstance(result, sdk_curation.CurationCandidate)
    return result


def test_checklist_reports_every_requirement_unmet_on_a_fresh_candidate(tmp_path: Path) -> None:
    candidate = make_candidate(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    result = sdk_curation.checklist(candidate, backend=backend)
    assert result["ok"] is False
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["logical_id_set"] == "absent"
    assert statuses["identity_resolved"] == "absent"


def test_checklist_is_satisfied_once_every_item_is_reviewed(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    candidate = make_candidate(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    sdk_curation.set_candidate_identity(
        candidate.candidate_id, logical_id="fake.dataset", evidence_class=EvidenceClass.MEASURED,
        root=root,
    )
    sdk_curation.set_candidate_compatibility(
        candidate.candidate_id, model_ids=("osp.fake.model",), root=root
    )
    sdk_curation.mark_license_reviewed(candidate.candidate_id, root=root)
    sdk_curation.acknowledge_identity(candidate.candidate_id, root=root)

    updated = sdk_curation.load_candidate(candidate.candidate_id, root=root)
    result = sdk_curation.checklist(updated, backend=backend)
    assert result["ok"] is True, result["checks"]


def test_accept_candidate_raises_when_checklist_is_incomplete(tmp_path: Path) -> None:
    candidate = make_candidate(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    with pytest.raises(ValueError, match="unmet requirement"):
        sdk_curation.accept_candidate(
            candidate.candidate_id, backend=backend, root=tmp_path / "curation"
        )


def test_accept_candidate_writes_a_real_dataset_record_once_complete(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    candidate = make_candidate(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    sdk_curation.set_candidate_identity(
        candidate.candidate_id, logical_id="fake.dataset", evidence_class=EvidenceClass.MEASURED,
        root=root,
    )
    sdk_curation.set_candidate_compatibility(
        candidate.candidate_id, model_ids=("osp.fake.model",), root=root
    )
    sdk_curation.mark_license_reviewed(candidate.candidate_id, root=root)
    sdk_curation.acknowledge_identity(candidate.candidate_id, root=root)

    manifest = sdk_curation.accept_candidate(candidate.candidate_id, backend=backend, root=root)
    assert manifest.logical_id == "fake.dataset"
    assert manifest.evidence_class == EvidenceClass.MEASURED
    backend.verify(manifest.record_id)  # re-verifies from disk, not just written

    accepted = sdk_curation.load_candidate(candidate.candidate_id, root=root)
    assert accepted.outcome == sdk_curation.CurationOutcome.ACCEPTED
    assert accepted.accepted_record_id == manifest.record_id


def test_reject_candidate_records_an_explicit_reason(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    candidate = make_candidate(tmp_path)
    rejected = sdk_curation.reject_candidate(
        candidate.candidate_id, reason="duplicate of an already-registered dataset", root=root
    )
    assert rejected.outcome == sdk_curation.CurationOutcome.REJECTED
    assert rejected.rejection_reason == "duplicate of an already-registered dataset"


def test_checklist_reports_not_satisfied_once_a_candidate_has_already_been_decided(
    tmp_path: Path,
) -> None:
    root = tmp_path / "curation"
    candidate = make_candidate(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    sdk_curation.reject_candidate(candidate.candidate_id, reason="not needed", root=root)

    rejected = sdk_curation.load_candidate(candidate.candidate_id, root=root)
    result = sdk_curation.checklist(rejected, backend=backend)
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["not_already_decided"] == "absent"
