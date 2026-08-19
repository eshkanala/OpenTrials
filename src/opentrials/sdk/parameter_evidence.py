"""Registry v0.2: real, individually-cited parameter values, reviewed before acceptance.

Registry v0.2's own research pass found no real, bulk-importable parameter
data anywhere available to this project (not in the two shipped model
profiles, not bundled with ospsuite/PK-Sim) -- every existing "value" this
project has ever touched is either a dose/administration fact or a
simulated output, never a literature-sourced PK parameter. Rather than
fabricate values to populate a bulk importer, this module treats literature
lookup as what it actually is here: a manual, human-driven act (searching,
reading a real source, transcribing one real number with its real
citation) -- and makes that act structured, auditable, and checklist-gated
before anything enters the immutable Registry, mirroring
``sdk.curation``'s exact discipline (mutable candidate -> checklist ->
accept/reject, no bypass) rather than inventing a second, looser pipeline.

What *is* real, automatable machinery here: unit-dimensionality validation
against ``sdk.parameter_identity``'s canonical vocabulary (never silently
converting, only rejecting what could not possibly be the claimed
concept), and duplicate/conflict detection against already-registered
PARAMETER_EVIDENCE records via ``sdk.registry_match.match_parameter_evidence``
-- a literal duplicate (same value, same context) is refused outright; a
genuine conflict (different value, same context -- e.g. two papers
disagreeing) must be explicitly acknowledged, then both values are
preserved as separate, independently retrievable Registry records, never
silently merged or overwritten.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import SchemaDocument, document
from opentrials.registry import (
    EvidenceClass,
    ParameterEvidenceRecord,
    RegistryBackend,
    RegistryEntryManifest,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.sdk.curation import CURATION_ROOT_ENV_VAR, CurationOutcome
from opentrials.sdk.parameter_identity import check_unit_compatible
from opentrials.sdk.registry_match import match_parameter_evidence

PARAMETER_CANDIDATE_SCHEMA = "opentrials.parameter-evidence-candidate"


class SimilarityLevel(StrEnum):
    """How one candidate relates to an already-registered PARAMETER_EVIDENCE record."""

    DUPLICATE = "DUPLICATE"
    """Same value (within tolerance) and same context -- never re-registered."""
    CONFLICT = "CONFLICT"
    """Different value, same context -- a real scientific disagreement, must be acknowledged."""
    COMPLEMENTARY = "COMPLEMENTARY"
    """Different context (species/method/population) -- another real data point, not a conflict."""


class SimilarityFinding(BaseModel):
    """One already-registered record's relationship to a candidate, with the reason why."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    existing_record_id: str = Field(min_length=1)
    existing_logical_id: str = Field(min_length=1)
    level: SimilarityLevel
    existing_value: float
    existing_unit: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class LiteratureCitation(BaseModel):
    """A specific, real, checkable source for one parameter value.

    ``excerpt`` is the literal text the value was read from -- required so
    a later reviewer can verify the transcription without re-fetching the
    source, the same auditability ``evidence.connector.TransformationStep``
    already requires of every automated connector's own interpretation.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    retrieved_at: datetime
    excerpt: str = Field(min_length=1)


class ParameterEvidenceCandidate(BaseModel):
    """A mutable, persisted review document for one proposed literature value."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    compound_id: str = Field(min_length=1)
    canonical_parameter_id: str = Field(min_length=1)
    value: ScientificValue
    citation: LiteratureCitation
    proposed_logical_id: str | None = None
    proposed_evidence_class: EvidenceClass | None = None
    citation_reviewed: bool = False
    conflict_acknowledged: bool = False
    outcome: CurationOutcome = CurationOutcome.PENDING
    rejection_reason: str | None = None
    accepted_record_id: str | None = None
    created_at: datetime
    updated_at: datetime


# ================= persistence (shares the curation root's env var/convention) =================


def _default_curation_root() -> Path:
    explicit = os.environ.get(CURATION_ROOT_ENV_VAR)
    if explicit:
        return Path(explicit)
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "opentrials" / "curation"


def _resolve_root(root: str | Path | None) -> Path:
    return _default_curation_root() if root is None else Path(root)


def _candidate_path(candidate_id: str, root: Path) -> Path:
    return root / "parameter_candidates" / f"{candidate_id}.json"


def _save_candidate(candidate: ParameterEvidenceCandidate, root: Path) -> None:
    path = _candidate_path(candidate.candidate_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        document(PARAMETER_CANDIDATE_SCHEMA, candidate).canonical_json() + "\n", encoding="utf-8"
    )


def load_candidate(
    candidate_id: str, *, root: str | Path | None = None
) -> ParameterEvidenceCandidate:
    path = _candidate_path(candidate_id, _resolve_root(root))
    if not path.is_file():
        raise ValueError(f"Unknown parameter-evidence candidate: {candidate_id!r}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = SchemaDocument.model_validate(raw)
    if envelope.schema_id != PARAMETER_CANDIDATE_SCHEMA:
        raise ValueError(
            f"Expected schema {PARAMETER_CANDIDATE_SCHEMA!r}; got {envelope.schema_id!r}."
        )
    return ParameterEvidenceCandidate.model_validate(envelope.payload)


def list_candidates(*, root: str | Path | None = None) -> tuple[ParameterEvidenceCandidate, ...]:
    resolved_root = _resolve_root(root) / "parameter_candidates"
    if not resolved_root.is_dir():
        return ()
    raw_root = _resolve_root(root)
    candidates = [
        load_candidate(p.stem, root=raw_root) for p in sorted(resolved_root.glob("*.json"))
    ]
    candidates.sort(key=lambda c: c.updated_at, reverse=True)
    return tuple(candidates)


def _resave(
    candidate: ParameterEvidenceCandidate, data: dict[str, Any], root: Path
) -> ParameterEvidenceCandidate:
    data["updated_at"] = datetime.now(UTC).isoformat()
    updated = ParameterEvidenceCandidate.model_validate(data)
    _save_candidate(updated, root)
    return updated


# ================= propose: one real, cited value at a time =================


def propose_candidate(
    *,
    compound_id: str,
    canonical_parameter_id: str,
    value: float,
    unit: str,
    value_type: ValueType,
    citation: LiteratureCitation,
    species: str | None = None,
    population: str | None = None,
    method: str | None = None,
    conditions: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> ParameterEvidenceCandidate:
    """Propose one real, cited parameter value for review.

    Validates the reported unit is dimensionally compatible with the
    claimed canonical concept before persisting anything -- a value that
    could not possibly be this concept (e.g. a volume reported for a
    clearance) is rejected immediately.
    """
    check_unit_compatible(canonical_parameter_id, unit)
    scientific_value = ScientificValue(
        value=value,
        unit=unit,
        value_type=value_type,
        species=species,
        population=population,
        method=method,
        conditions=conditions or {},
    )
    now = datetime.now(UTC)
    candidate = ParameterEvidenceCandidate(
        candidate_id=uuid.uuid4().hex,
        compound_id=compound_id,
        canonical_parameter_id=canonical_parameter_id,
        value=scientific_value,
        citation=citation,
        created_at=now,
        updated_at=now,
    )
    _save_candidate(candidate, _resolve_root(root))
    return candidate


# ================= duplicate / conflict detection =================


def find_similar(
    candidate: ParameterEvidenceCandidate, *, backend: RegistryBackend, tolerance: float = 0.05
) -> tuple[SimilarityFinding, ...]:
    """Compare a candidate against every already-registered record for the same concept.

    ``tolerance`` is a relative difference (default 5%) below which two
    values reported in the same context are treated as the same
    measurement (``DUPLICATE``) rather than a real disagreement
    (``CONFLICT``). Values are compared in the candidate's own unit via
    ``ScientificValue.to()`` -- never by comparing raw numbers in
    potentially different units.
    """
    matches = match_parameter_evidence(
        compound_id=candidate.compound_id,
        canonical_parameter_id=candidate.canonical_parameter_id,
        backend=backend,
    )
    findings: list[SimilarityFinding] = []
    for match in matches:
        _, payload = backend.get(match.manifest.record_id)
        if not isinstance(payload, ParameterEvidenceRecord):
            continue
        existing = payload.value
        try:
            existing_in_candidate_unit = existing.to(candidate.value.unit)
        except UnitCompatibilityError:
            continue

        same_context = (
            existing.species == candidate.value.species
            and existing.method == candidate.value.method
            and existing.population == candidate.value.population
        )
        denominator = max(abs(candidate.value.value), 1e-9)
        relative_diff = abs(existing_in_candidate_unit.value - candidate.value.value) / denominator

        if same_context and relative_diff <= tolerance:
            level = SimilarityLevel.DUPLICATE
            reason = f"Same context, values within {tolerance:.0%} tolerance."
        elif same_context:
            level = SimilarityLevel.CONFLICT
            reason = "Same context (species/method/population) but a materially different value."
        else:
            level = SimilarityLevel.COMPLEMENTARY
            reason = "Different context (species/method/population) -- a distinct real data point."

        findings.append(
            SimilarityFinding(
                existing_record_id=match.manifest.record_id,
                existing_logical_id=match.manifest.logical_id,
                level=level,
                existing_value=existing_in_candidate_unit.value,
                existing_unit=candidate.value.unit,
                reason=reason,
            )
        )
    return tuple(findings)


# ================= review: identity, citation, conflict acknowledgment =================


def set_candidate_identity(
    candidate_id: str,
    *,
    logical_id: str,
    evidence_class: EvidenceClass,
    root: str | Path | None = None,
) -> ParameterEvidenceCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["proposed_logical_id"] = logical_id
    data["proposed_evidence_class"] = evidence_class.value
    return _resave(candidate, data, resolved_root)


def mark_citation_reviewed(
    candidate_id: str, *, root: str | Path | None = None
) -> ParameterEvidenceCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["citation_reviewed"] = True
    return _resave(candidate, data, resolved_root)


def acknowledge_conflict(
    candidate_id: str, *, root: str | Path | None = None
) -> ParameterEvidenceCandidate:
    """Explicitly acknowledge a real conflict with an already-registered value.

    Does not resolve the disagreement -- both values are preserved as
    separate records; this only confirms a reviewer has seen and accepted
    that the disagreement is real, not an oversight.
    """
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["conflict_acknowledged"] = True
    return _resave(candidate, data, resolved_root)


# ================= checklist + acceptance =================


def checklist(
    candidate: ParameterEvidenceCandidate, *, backend: RegistryBackend
) -> dict[str, Any]:
    """Every unresolved requirement, recomputed fresh -- never cached or trusted from the client."""
    checks: list[dict[str, str]] = []
    ok = True

    def add(requirement: str, label: str, satisfied: bool, detail: str) -> None:
        nonlocal ok
        checks.append(
            {
                "requirement": requirement,
                "label": label,
                "status": "verified" if satisfied else "absent",
                "detail": detail,
            }
        )
        if not satisfied:
            ok = False

    add(
        "logical_id_set",
        "Logical ID assigned",
        candidate.proposed_logical_id is not None,
        candidate.proposed_logical_id or "not yet set",
    )
    add(
        "evidence_class_set",
        "Evidence class assigned",
        candidate.proposed_evidence_class is not None,
        candidate.proposed_evidence_class.value
        if candidate.proposed_evidence_class
        else "not yet set",
    )
    add(
        "citation_reviewed",
        "Citation reviewed",
        candidate.citation_reviewed,
        candidate.citation.url if candidate.citation_reviewed else "not yet reviewed",
    )

    findings = find_similar(candidate, backend=backend)
    duplicates = [f for f in findings if f.level == SimilarityLevel.DUPLICATE]
    conflicts = [f for f in findings if f.level == SimilarityLevel.CONFLICT]
    add(
        "no_duplicate",
        "Not a duplicate of an existing record",
        not duplicates,
        f"duplicates {[d.existing_logical_id for d in duplicates]}"
        if duplicates
        else "no duplicate found",
    )
    conflict_ok = not conflicts or candidate.conflict_acknowledged
    add(
        "conflicts_acknowledged",
        "Conflicting values acknowledged",
        conflict_ok,
        f"conflicts with {[c.existing_logical_id for c in conflicts]}"
        if conflicts and not candidate.conflict_acknowledged
        else ("no conflict found" if not conflicts else "acknowledged"),
    )

    add(
        "not_already_decided",
        "Outcome still pending",
        candidate.outcome == CurationOutcome.PENDING,
        candidate.outcome.value,
    )

    return {"ok": ok, "checks": checks}


def accept_candidate(
    candidate_id: str, *, backend: RegistryBackend, root: str | Path | None = None
) -> RegistryEntryManifest:
    """Write the real, immutable PARAMETER_EVIDENCE record -- gated, no bypass."""
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    result = checklist(candidate, backend=backend)
    if not result["ok"]:
        unmet = [c["label"] for c in result["checks"] if c["status"] != "verified"]
        raise ValueError(
            f"Cannot accept candidate {candidate_id!r}: unmet requirement(s) -- {'; '.join(unmet)}."
        )

    logical_id = candidate.proposed_logical_id
    evidence_class = candidate.proposed_evidence_class
    if logical_id is None or evidence_class is None:
        raise ValueError(
            "Cannot accept: logical_id/evidence_class missing despite passing checklist."
        )

    payload = ParameterEvidenceRecord(
        parameter_id=f"{candidate.compound_id}.{candidate.canonical_parameter_id}",
        compound_id=candidate.compound_id,
        value=candidate.value,
        narrative=f"{candidate.citation.title} ({candidate.citation.url})",
    )
    manifest = backend.put(
        RegistryRecordKind.PARAMETER_EVIDENCE,
        payload,
        logical_id=logical_id,
        evidence_class=evidence_class,
        license="Public literature citation; no redistribution of source text asserted.",
        source=RegistrySource(
            kind="literature",
            identifier=candidate.citation.url,
            url=candidate.citation.url,
            retrieved_at=candidate.citation.retrieved_at,
        ),
    )

    data = candidate.model_dump(mode="json")
    data["outcome"] = CurationOutcome.ACCEPTED.value
    data["accepted_record_id"] = manifest.record_id
    _resave(candidate, data, resolved_root)
    return manifest


def reject_candidate(
    candidate_id: str, *, reason: str, root: str | Path | None = None
) -> ParameterEvidenceCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["outcome"] = CurationOutcome.REJECTED.value
    data["rejection_reason"] = reason
    return _resave(candidate, data, resolved_root)
