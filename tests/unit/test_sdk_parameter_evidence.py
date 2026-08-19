"""Contract tests for sdk.parameter_evidence -- Registry v0.2's literature-value pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.core.scientific_value import ValueType
from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistryRecordKind
from opentrials.sdk import curation as sdk_curation
from opentrials.sdk import parameter_evidence as sdk_pe


def citation(url: str = "https://example.org/label") -> sdk_pe.LiteratureCitation:
    return sdk_pe.LiteratureCitation(
        url=url,
        title="Example drug label",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        excerpt="Renal clearance was reported as 3.5 L/hour in healthy adults.",
    )


def propose(
    tmp_path: Path, *, value: float = 3.5, unit: str = "L/hour"
) -> sdk_pe.ParameterEvidenceCandidate:
    return sdk_pe.propose_candidate(
        compound_id="aciclovir",
        canonical_parameter_id="renal_clearance",
        value=value,
        unit=unit,
        value_type=ValueType.OBSERVED,
        citation=citation(),
        species="human",
        root=tmp_path / "curation",
    )


def test_propose_candidate_rejects_a_dimensionally_incompatible_unit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not dimensionally compatible"):
        sdk_pe.propose_candidate(
            compound_id="aciclovir",
            canonical_parameter_id="renal_clearance",
            value=1.0,
            unit="L",
            value_type=ValueType.OBSERVED,
            citation=citation(),
            root=tmp_path / "curation",
        )


def test_propose_candidate_persists_and_round_trips(tmp_path: Path) -> None:
    candidate = propose(tmp_path)
    reloaded = sdk_pe.load_candidate(candidate.candidate_id, root=tmp_path / "curation")
    assert reloaded.candidate_id == candidate.candidate_id
    assert reloaded.value.value == 3.5
    assert reloaded.value.unit == "L/hour"
    assert reloaded.outcome == sdk_curation.CurationOutcome.PENDING


def test_list_candidates_returns_every_persisted_candidate(tmp_path: Path) -> None:
    first = propose(tmp_path)
    second = sdk_pe.propose_candidate(
        compound_id="midazolam",
        canonical_parameter_id="hepatic_clearance",
        value=1.2,
        unit="L/hour",
        value_type=ValueType.OBSERVED,
        citation=citation("https://example.org/other"),
        root=tmp_path / "curation",
    )
    ids = {c.candidate_id for c in sdk_pe.list_candidates(root=tmp_path / "curation")}
    assert ids == {first.candidate_id, second.candidate_id}


def test_checklist_reports_every_requirement_unmet_on_a_fresh_candidate(tmp_path: Path) -> None:
    candidate = propose(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    result = sdk_pe.checklist(candidate, backend=backend)
    assert result["ok"] is False
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["logical_id_set"] == "absent"
    assert statuses["no_duplicate"] == "verified"  # nothing registered yet -- no duplicate


def review(candidate_id: str, root: Path) -> None:
    sdk_pe.set_candidate_identity(
        candidate_id,
        logical_id="aciclovir.renal_clearance.example-label",
        evidence_class=EvidenceClass.MEASURED,
        root=root,
    )
    sdk_pe.mark_citation_reviewed(candidate_id, root=root)


def test_checklist_is_satisfied_once_reviewed_with_no_similar_records(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    candidate = propose(tmp_path)
    review(candidate.candidate_id, root)

    updated = sdk_pe.load_candidate(candidate.candidate_id, root=root)
    result = sdk_pe.checklist(updated, backend=backend)
    assert result["ok"] is True, result["checks"]


def test_accept_candidate_writes_a_real_parameter_evidence_record(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    candidate = propose(tmp_path)
    review(candidate.candidate_id, root)

    manifest = sdk_pe.accept_candidate(candidate.candidate_id, backend=backend, root=root)
    assert manifest.kind == RegistryRecordKind.PARAMETER_EVIDENCE
    assert manifest.evidence_class == EvidenceClass.MEASURED
    backend.verify(manifest.record_id)

    accepted = sdk_pe.load_candidate(candidate.candidate_id, root=root)
    assert accepted.outcome == sdk_curation.CurationOutcome.ACCEPTED
    assert accepted.accepted_record_id == manifest.record_id


def test_accept_candidate_raises_when_checklist_is_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    candidate = propose(tmp_path)
    with pytest.raises(ValueError, match="unmet requirement"):
        sdk_pe.accept_candidate(candidate.candidate_id, backend=backend, root=root)


def test_a_second_candidate_with_the_same_value_and_context_is_a_blocking_duplicate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "curation"
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    first = propose(tmp_path)
    review(first.candidate_id, root)
    sdk_pe.accept_candidate(first.candidate_id, backend=backend, root=root)

    second = propose(tmp_path, value=3.51)  # within 5% tolerance, same species/method (both None)
    sdk_pe.set_candidate_identity(
        second.candidate_id,
        logical_id="aciclovir.renal_clearance.another-source",
        evidence_class=EvidenceClass.MEASURED,
        root=root,
    )
    sdk_pe.mark_citation_reviewed(second.candidate_id, root=root)

    updated = sdk_pe.load_candidate(second.candidate_id, root=root)
    result = sdk_pe.checklist(updated, backend=backend)
    assert result["ok"] is False
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["no_duplicate"] == "absent"

    with pytest.raises(ValueError, match="unmet requirement"):
        sdk_pe.accept_candidate(second.candidate_id, backend=backend, root=root)


def test_a_second_candidate_with_a_materially_different_value_is_a_conflict_needing_acknowledgment(
    tmp_path: Path,
) -> None:
    root = tmp_path / "curation"
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    first = propose(tmp_path, value=3.5)
    review(first.candidate_id, root)
    sdk_pe.accept_candidate(first.candidate_id, backend=backend, root=root)

    second = propose(tmp_path, value=7.0)  # a genuinely different value, same (null) context
    sdk_pe.set_candidate_identity(
        second.candidate_id,
        logical_id="aciclovir.renal_clearance.disagreeing-source",
        evidence_class=EvidenceClass.MEASURED,
        root=root,
    )
    sdk_pe.mark_citation_reviewed(second.candidate_id, root=root)

    updated = sdk_pe.load_candidate(second.candidate_id, root=root)
    result = sdk_pe.checklist(updated, backend=backend)
    assert result["ok"] is False
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["no_duplicate"] == "verified"
    assert statuses["conflicts_acknowledged"] == "absent"

    sdk_pe.acknowledge_conflict(second.candidate_id, root=root)
    reacknowledged = sdk_pe.load_candidate(second.candidate_id, root=root)
    result_after = sdk_pe.checklist(reacknowledged, backend=backend)
    assert result_after["ok"] is True, result_after["checks"]

    manifest = sdk_pe.accept_candidate(second.candidate_id, backend=backend, root=root)
    assert manifest.record_id != first.candidate_id  # both records now exist independently


def test_reject_candidate_records_an_explicit_reason(tmp_path: Path) -> None:
    root = tmp_path / "curation"
    candidate = propose(tmp_path)
    rejected = sdk_pe.reject_candidate(
        candidate.candidate_id, reason="not a primary source", root=root
    )
    assert rejected.outcome == sdk_curation.CurationOutcome.REJECTED
    assert rejected.rejection_reason == "not a primary source"
