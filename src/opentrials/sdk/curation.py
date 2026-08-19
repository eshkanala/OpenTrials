"""Registry curation pipeline: connector output -> reviewed candidate -> accepted record.

``evidence.connector``/``orchestration.evidence_ingestion`` already solve
Source -> Raw snapshot -> Normalization generically (fetch/normalize/persist
one connector run into immutable ``OTRAW``/``OTOBS``/``OTCONN`` artifacts).
``sdk.registry_match`` already solves rules-based identity matching against
already-registered Registry content. What has never existed is the stage in
between an ingested-but-unreviewed dataset and a real, immutable Registry
record -- until now, that gap was closed by hand-writing a one-off script
(``sdk.registry_seed``) that baked every judgment call (eligibility,
identity, evidence class, license, compatibility) directly into code, with
an ineligible candidate (Laskin 1982) simply never called at all -- a
silent omission, not a recorded decision.

This module makes every one of those judgment calls an explicit, visible,
persisted decision instead:

    run a connector
        -> ingested successfully:  a mutable, reviewable CurationCandidate
        -> IneligibleEvidenceCandidateError: a real, listable
           IneligibleCandidateRecord -- *why* it was excluded is now data,
           not an absence a future curator has to rediscover by reading code
    reviewer sets logical_id / evidence_class / compatibility, reviews
    license, and reviews identity (an automatic Registry compound match,
    or an explicit acknowledgment that this is a genuinely new compound)
    checklist() recomputes every requirement fresh, gating accept_candidate()
    the same un-bypassable way sdk.onboarding.register_model() gates
    registration -- no candidate becomes a real record without every item
    satisfied, checked server-side, not trusted from a caller's claim.
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

from opentrials.core.serialization import SchemaDocument, document
from opentrials.evidence.connector import DataConnector, IneligibleEvidenceCandidateError
from opentrials.orchestration.evidence_ingestion import ingest_evidence
from opentrials.registry import (
    EvidenceClass,
    RegistryBackend,
    RegistryCompatibility,
    RegistryEntryManifest,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.sdk.registry_match import match_compound
from opentrials.storage.connector_run import DataConnectorRunManifest
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.validation import ObservedDataset

CURATION_ROOT_ENV_VAR = "OPENTRIALS_CURATION_ROOT"
CURATION_CANDIDATE_SCHEMA = "opentrials.curation-candidate"
CURATION_INELIGIBLE_SCHEMA = "opentrials.curation-ineligible"


class CurationOutcome(StrEnum):
    """A candidate's own review lifecycle -- distinct from ``EvidenceClass``.

    ``EvidenceClass`` (once accepted) says how trustworthy the record is;
    this says whether a human has decided to let it into the Registry at all.
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class IneligibleCandidateRecord(BaseModel):
    """A connector run that could not honestly become a candidate at all.

    Persisted specifically so this outcome is *visible* -- ``sdk.registry_seed``
    excludes Laskin 1982 by simply never calling its connector; a future
    curator reading the Registry has no way to discover that decision, let
    alone why it was made. This record is the fix: the exact error a real
    ``normalize()`` call raised, kept as data.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    attempted_at: datetime


class CurationCandidate(BaseModel):
    """A mutable, persisted review document for one successfully ingested dataset.

    Self-contained like ``sdk.onboarding.OnboardingDraft``: embeds the full
    ``ObservedDataset`` and its ``DataConnectorRunManifest`` rather than
    referencing them by ID, so a reviewer (or Studio) never needs direct
    access to whatever ``evidence_root`` ingestion happened to use.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    kind: RegistryRecordKind = RegistryRecordKind.DATASET
    connector_run: DataConnectorRunManifest
    dataset: ObservedDataset
    proposed_logical_id: str | None = None
    proposed_evidence_class: EvidenceClass | None = None
    proposed_compatibility: RegistryCompatibility | None = None
    license_reviewed: bool = False
    identity_reviewed: bool = False
    outcome: CurationOutcome = CurationOutcome.PENDING
    rejection_reason: str | None = None
    accepted_record_id: str | None = None
    created_at: datetime
    updated_at: datetime


# ================= persistence =================


def _default_curation_root() -> Path:
    """Global, like the Registry itself -- a candidate outlives the project it was ingested in."""
    explicit = os.environ.get(CURATION_ROOT_ENV_VAR)
    if explicit:
        return Path(explicit)
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "opentrials" / "curation"


def _resolve_root(root: str | Path | None) -> Path:
    return _default_curation_root() if root is None else Path(root)


def _candidate_path(candidate_id: str, root: Path) -> Path:
    return root / "candidates" / f"{candidate_id}.json"


def _ineligible_path(record_id: str, root: Path) -> Path:
    return root / "ineligible" / f"{record_id}.json"


def _save_candidate(candidate: CurationCandidate, root: Path) -> None:
    path = _candidate_path(candidate.candidate_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        document(CURATION_CANDIDATE_SCHEMA, candidate).canonical_json() + "\n", encoding="utf-8"
    )


def load_candidate(candidate_id: str, *, root: str | Path | None = None) -> CurationCandidate:
    path = _candidate_path(candidate_id, _resolve_root(root))
    if not path.is_file():
        raise ValueError(f"Unknown curation candidate: {candidate_id!r}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = SchemaDocument.model_validate(raw)
    if envelope.schema_id != CURATION_CANDIDATE_SCHEMA:
        raise ValueError(
            f"Expected schema {CURATION_CANDIDATE_SCHEMA!r}; got {envelope.schema_id!r}."
        )
    return CurationCandidate.model_validate(envelope.payload)


def list_candidates(*, root: str | Path | None = None) -> tuple[CurationCandidate, ...]:
    resolved_root = _resolve_root(root) / "candidates"
    if not resolved_root.is_dir():
        return ()
    raw_root = _resolve_root(root)
    candidates = [
        load_candidate(p.stem, root=raw_root) for p in sorted(resolved_root.glob("*.json"))
    ]
    candidates.sort(key=lambda c: c.updated_at, reverse=True)
    return tuple(candidates)


def list_ineligible(*, root: str | Path | None = None) -> tuple[IneligibleCandidateRecord, ...]:
    resolved_root = _resolve_root(root) / "ineligible"
    if not resolved_root.is_dir():
        return ()
    records = []
    for path in sorted(resolved_root.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        envelope = SchemaDocument.model_validate(raw)
        records.append(IneligibleCandidateRecord.model_validate(envelope.payload))
    records.sort(key=lambda r: r.attempted_at, reverse=True)
    return tuple(records)


def _resave(candidate: CurationCandidate, data: dict[str, Any], root: Path) -> CurationCandidate:
    data["updated_at"] = datetime.now(UTC).isoformat()
    updated = CurationCandidate.model_validate(data)
    _save_candidate(updated, root)
    return updated


# ================= ingestion: Source -> Raw snapshot -> Normalization =================


def create_candidate_from_connector(
    connector: DataConnector,
    *,
    evidence_root: str | Path | None = None,
    root: str | Path | None = None,
) -> CurationCandidate | IneligibleCandidateRecord:
    """Run one connector and turn its outcome into a visible, persisted decision.

    ``evidence_root`` derives its three ingestion sub-roots (``raw/``,
    ``observed/``, ``connector_runs/``) the same way ``sdk.evidence.ingest_and_persist``
    already does; defaults to a subdirectory of the curation root itself,
    since curated candidates are destined for the shared Registry, not tied
    to any one project the way ``sdk.evidence``'s per-project evidence is.

    A connector that raises ``IneligibleEvidenceCandidateError`` no longer
    just gets skipped by whoever is writing curation code -- it becomes a
    real ``IneligibleCandidateRecord``, listable via ``list_ineligible()``,
    with the connector's own reasoning kept verbatim.
    """
    resolved_root = _resolve_root(root)
    resolved_evidence_root = (
        Path(evidence_root) if evidence_root is not None else resolved_root / "evidence"
    )
    observed_root = resolved_evidence_root / "observed"
    try:
        manifest = ingest_evidence(
            connector,
            raw_snapshot_root=resolved_evidence_root / "raw",
            observed_root=observed_root,
            connector_run_root=resolved_evidence_root / "connector_runs",
        )
    except IneligibleEvidenceCandidateError as error:
        record = IneligibleCandidateRecord(
            record_id=uuid.uuid4().hex,
            connector_id=connector.identity.connector_id,
            connector_version=connector.identity.version,
            reason=str(error),
            attempted_at=datetime.now(UTC),
        )
        path = _ineligible_path(record.record_id, resolved_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            document(CURATION_INELIGIBLE_SCHEMA, record).canonical_json() + "\n", encoding="utf-8"
        )
        return record

    observed_manifest = ObservedArtifactStore(observed_root).read_manifest(
        manifest.observed_dataset_id
    )
    dataset = observed_manifest.dataset

    now = datetime.now(UTC)
    candidate = CurationCandidate(
        candidate_id=uuid.uuid4().hex,
        connector_run=manifest,
        dataset=dataset,
        created_at=now,
        updated_at=now,
    )
    _save_candidate(candidate, resolved_root)
    return candidate


# ================= review: Identity resolution, Context annotation, =================
# ================= Evidence classification, License/rights check     =================


def set_candidate_identity(
    candidate_id: str,
    *,
    logical_id: str,
    evidence_class: EvidenceClass,
    root: str | Path | None = None,
) -> CurationCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["proposed_logical_id"] = logical_id
    data["proposed_evidence_class"] = evidence_class.value
    return _resave(candidate, data, resolved_root)


def set_candidate_compatibility(
    candidate_id: str,
    *,
    model_ids: tuple[str, ...] = (),
    route: str | None = None,
    species: tuple[str, ...] = (),
    notes: str | None = None,
    root: str | Path | None = None,
) -> CurationCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    compatibility = RegistryCompatibility(
        model_ids=model_ids, route=route, species=species, notes=notes
    )
    data = candidate.model_dump(mode="json")
    data["proposed_compatibility"] = compatibility.model_dump(mode="json")
    return _resave(candidate, data, resolved_root)


def mark_license_reviewed(
    candidate_id: str, *, root: str | Path | None = None
) -> CurationCandidate:
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["license_reviewed"] = True
    return _resave(candidate, data, resolved_root)


def acknowledge_identity(candidate_id: str, *, root: str | Path | None = None) -> CurationCandidate:
    """Explicitly acknowledge this candidate's compound identity -- matched or genuinely new.

    Distinct from ``checklist()``'s own automatic match check: a reviewer
    calls this once they have actually looked, whether or not
    ``sdk.registry_match.match_compound`` found an existing record.
    """
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["identity_reviewed"] = True
    return _resave(candidate, data, resolved_root)


# ================= Human/automated validation =================


def checklist(candidate: CurationCandidate, *, backend: RegistryBackend) -> dict[str, Any]:
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

    compound_id = candidate.dataset.study.intervention.compound.identity.compound_id
    match = match_compound(compound_id, backend=backend)
    identity_ok = match is not None or candidate.identity_reviewed
    add(
        "identity_resolved",
        "Compound identity resolved",
        identity_ok,
        f"matches registered compound {compound_id!r}"
        if match is not None
        else (
            "reviewer acknowledged as new" if candidate.identity_reviewed else "not yet reviewed"
        ),
    )

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
        "license_reviewed",
        "License / rights reviewed",
        candidate.license_reviewed,
        candidate.dataset.license if candidate.license_reviewed else "not yet reviewed",
    )
    compatibility_ok = candidate.proposed_compatibility is not None and bool(
        candidate.proposed_compatibility.model_ids or candidate.proposed_compatibility.route
    )
    add(
        "compatibility_declared",
        "Compatibility context declared",
        compatibility_ok,
        "declared" if compatibility_ok else "not yet declared",
    )
    add(
        "not_already_decided",
        "Outcome still pending",
        candidate.outcome == CurationOutcome.PENDING,
        candidate.outcome.value,
    )

    return {"ok": ok, "checks": checks}


# ================= Registry candidate -> Accepted record =================


def accept_candidate(
    candidate_id: str, *, backend: RegistryBackend, root: str | Path | None = None
) -> RegistryEntryManifest:
    """Write the real, immutable Registry record -- gated, no bypass.

    Recomputes the checklist itself rather than trusting a client-side
    "all done" flag, the same discipline ``sdk.onboarding.register_model``
    uses for model registration.
    """
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    result = checklist(candidate, backend=backend)
    if not result["ok"]:
        unmet = [c["label"] for c in result["checks"] if c["status"] != "verified"]
        raise ValueError(
            f"Cannot accept candidate {candidate_id!r}: unmet requirement(s) -- {'; '.join(unmet)}."
        )

    assert candidate.proposed_logical_id is not None
    assert candidate.proposed_evidence_class is not None

    manifest = backend.put(
        RegistryRecordKind.DATASET,
        candidate.dataset,
        logical_id=candidate.proposed_logical_id,
        evidence_class=candidate.proposed_evidence_class,
        license=candidate.dataset.license,
        source=RegistrySource(
            kind="curation_pipeline",
            identifier=candidate.connector_run.run_id,
            retrieved_at=candidate.connector_run.source.retrieved_at,
        ),
        compatibility=candidate.proposed_compatibility,
        provenance_ids=(candidate.connector_run.run_id,),
    )

    data = candidate.model_dump(mode="json")
    data["outcome"] = CurationOutcome.ACCEPTED.value
    data["accepted_record_id"] = manifest.record_id
    _resave(candidate, data, resolved_root)
    return manifest


def reject_candidate(
    candidate_id: str, *, reason: str, root: str | Path | None = None
) -> CurationCandidate:
    """Explicitly, visibly reject a candidate -- never leave it silently unreviewed forever."""
    resolved_root = _resolve_root(root)
    candidate = load_candidate(candidate_id, root=resolved_root)
    data = candidate.model_dump(mode="json")
    data["outcome"] = CurationOutcome.REJECTED.value
    data["rejection_reason"] = reason
    return _resave(candidate, data, resolved_root)
