"""Experiment lineage and reproduction: find, understand, reproduce, fork, trace forever.

Everything here is pure translation/verification over what already exists
-- no new persistence layer, no new record kind. ``sdk.registry.default_registry_backend``
already stores ``EXPERIMENT`` records with a full embedded ``Trial``;
``registry.schema.ExperimentRecord.forked_from_record_id`` (resolved
automatically at registration time from ``trial.provenance_ids``, never
trusted from caller input) is the one genuinely new piece of structured
state this module depends on.

Three real, checkable capabilities, matching the founding UX goal exactly:

    endpoint_summary_sha256()  -- the reproducibility fingerprint: since
                                   population generation is seeded, re-running
                                   the same trial against the same model
                                   should reproduce this exact hash
    ancestry() / children()    -- walk the fork lineage graph, both
                                   directions, using only the structured
                                   pointer above -- never string-guessing
                                   through provenance_ids
    diff_trials()              -- a generic, recursive structural diff
                                   between two Trial protocols' own JSON
                                   representations -- reports exactly what
                                   changed, added, or removed, without
                                   hand-maintaining a per-field comparison
                                   that would drift out of sync with Trial's
                                   own schema
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentrials.core.serialization import sha256
from opentrials.registry import RegistryBackend, RegistryError, RegistryRecordKind
from opentrials.registry.schema import ExperimentRecord, RegistryEntryManifest
from opentrials.sdk.run import EndpointRecord
from opentrials.trials.trial import Trial


def endpoint_summary_sha256(endpoints: Sequence[EndpointRecord]) -> str:
    """The reproducibility fingerprint of a run's own flattened endpoint results.

    Population generation is seeded (``Population.seed``), so re-running
    the identical trial against the identical model should reproduce this
    exact hash -- a real, bit-for-bit checkable claim, not a fuzzy
    tolerance comparison. Sorted by ``(subject_id, endpoint_type)`` so the
    hash does not depend on incidental ordering.
    """
    rows = sorted(
        (
            {
                "arm_id": endpoint.arm_id,
                "subject_id": endpoint.subject_id,
                "endpoint_type": endpoint.endpoint_type,
                "value": endpoint.value,
                "unit": endpoint.unit,
            }
            for endpoint in endpoints
        ),
        key=lambda row: (row["subject_id"], row["endpoint_type"]),
    )
    return sha256(rows)


def resolve_forked_from(trial: Trial, *, backend: RegistryBackend) -> str | None:
    """Resolve a structured fork-lineage pointer from a trial's own provenance, if any.

    Scans ``trial.provenance_ids`` for the most recently appended entry
    matching a real, existing EXPERIMENT record -- ``fork_experiment``
    always appends the parent's exact ``record_id`` last, so the last
    match is the immediate parent. Never trusts an arbitrary string: the
    candidate record is fetched and its kind confirmed before being
    treated as a real parent.
    """
    for candidate_id in reversed(trial.provenance_ids):
        if not candidate_id.startswith("OTREG-EXPERIMENT-"):
            continue
        try:
            manifest, _ = backend.get(candidate_id)
        except RegistryError:
            continue
        if manifest.kind is RegistryRecordKind.EXPERIMENT:
            return candidate_id
    return None


def ancestry(record_id: str, *, backend: RegistryBackend) -> tuple[RegistryEntryManifest, ...]:
    """Walk the fork chain backward from ``record_id`` -- self first, root last.

    Stops if a cycle is somehow encountered (defensive; the write-once
    Registry cannot create one through normal use) rather than looping
    forever.
    """
    chain: list[RegistryEntryManifest] = []
    seen: set[str] = set()
    current_id: str | None = record_id
    while current_id is not None and current_id not in seen:
        seen.add(current_id)
        try:
            manifest, payload = backend.get(current_id)
        except RegistryError:
            break
        if manifest.kind is not RegistryRecordKind.EXPERIMENT or not isinstance(
            payload, ExperimentRecord
        ):
            break
        chain.append(manifest)
        current_id = payload.forked_from_record_id
    return tuple(chain)


def children(record_id: str, *, backend: RegistryBackend) -> tuple[RegistryEntryManifest, ...]:
    """Every registered experiment directly forked from ``record_id`` (not grandchildren)."""
    results: list[RegistryEntryManifest] = []
    for manifest in backend.list(RegistryRecordKind.EXPERIMENT):
        _, payload = backend.get(manifest.record_id)
        if isinstance(payload, ExperimentRecord) and payload.forked_from_record_id == record_id:
            results.append(manifest)
    return tuple(results)


def _walk_diff(before: Any, after: Any, path: str, changes: list[dict[str, Any]]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"path": child_path, "change": "added", "after": after[key]})
            elif key not in after:
                changes.append({"path": child_path, "change": "removed", "before": before[key]})
            else:
                _walk_diff(before[key], after[key], child_path, changes)
    elif isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            child_path = f"{path}[{index}]"
            if index >= len(before):
                changes.append({"path": child_path, "change": "added", "after": after[index]})
            elif index >= len(after):
                changes.append({"path": child_path, "change": "removed", "before": before[index]})
            else:
                _walk_diff(before[index], after[index], child_path, changes)
    elif before != after:
        changes.append({"path": path, "change": "changed", "before": before, "after": after})


def diff_trials(original: Trial, forked: Trial) -> list[dict[str, Any]]:
    """A generic, recursive structural diff between two trial protocols.

    Walks both trials' own JSON representations rather than hand-comparing
    known fields, so it never drifts out of sync with ``Trial``'s own
    schema as new fields are added. Reports every added/removed/changed
    leaf value with its exact path (e.g. ``"arms[1].intervention...dose...value"``).
    """
    changes: list[dict[str, Any]] = []
    _walk_diff(
        original.model_dump(mode="json"), forked.model_dump(mode="json"), "", changes
    )
    return changes
