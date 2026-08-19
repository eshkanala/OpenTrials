"""Deterministic, rules-based matching between a model-onboarding discovery and the Registry.

No LLM, no fuzzy inference: every candidate is scored from explicit,
inspectable criteria (compound identity, administration route, declared
target, evidence class) and carries a human-readable list of exactly
which criteria matched. "Recommended" never means "the registry had a
number" -- a researcher can always see why a candidate was suggested,
matching the approved Model Builder design's own "Why is this
suggested?" affordance.

Deliberately conservative: a candidate with zero matching criteria is
never returned, and the ranking (HIGH > MODERATE > LOW) is a simple,
auditable rule count, not a learned or weighted score.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from opentrials.registry import RegistryBackend, RegistryEntryManifest, RegistryRecordKind
from opentrials.validation import ObservedDataset

_COMPATIBILITY_ORDER = {"HIGH": 0, "MODERATE": 1, "LOW": 2}


class CompatibilityLevel(StrEnum):
    """How strongly a matched record's own declared context fits the target."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


@dataclass(frozen=True)
class RegistryMatch:
    """One candidate Registry record, with an auditable reason for the match."""

    manifest: RegistryEntryManifest
    compatibility: CompatibilityLevel
    reasons: tuple[str, ...]


def _sorted_by_compatibility(matches: list[RegistryMatch]) -> list[RegistryMatch]:
    matches.sort(key=lambda m: _COMPATIBILITY_ORDER[m.compatibility.value])
    return matches


def match_compound(compound_id: str, *, backend: RegistryBackend) -> RegistryMatch | None:
    """Exact ``compound_id`` identity match against registered COMPOUND records."""
    for manifest in backend.list(RegistryRecordKind.COMPOUND):
        if manifest.logical_id == compound_id:
            return RegistryMatch(
                manifest=manifest,
                compatibility=CompatibilityLevel.HIGH,
                reasons=(f"Exact compound identity match: compound_id={compound_id!r}.",),
            )
    return None


def match_datasets_for_compound(
    compound_id: str, *, backend: RegistryBackend, target_route: str | None = None
) -> list[RegistryMatch]:
    """Registered DATASET records whose study intervention compound matches ``compound_id``.

    ``target_route`` (e.g. "INTRAVENOUS"), when supplied, upgrades a match
    to HIGH if the dataset's own administration route agrees, or
    downgrades it to LOW if it disagrees -- a route mismatch is a real,
    inspectable reason to distrust a candidate, not silently ignored.
    """
    matches: list[RegistryMatch] = []
    for manifest in backend.list(RegistryRecordKind.DATASET):
        _, payload = backend.get(manifest.record_id)
        if not isinstance(payload, ObservedDataset):
            continue
        dataset_compound_id = payload.study.intervention.compound.identity.compound_id
        if dataset_compound_id != compound_id:
            continue

        reasons = [f"Dataset intervention compound matches: compound_id={compound_id!r}."]
        compatibility = CompatibilityLevel.MODERATE
        dataset_route = payload.study.intervention.regimen.doses[0].route.value
        if target_route is not None:
            if dataset_route == target_route:
                reasons.append(f"Administration route matches: {target_route}.")
                compatibility = CompatibilityLevel.HIGH
            else:
                reasons.append(
                    f"Administration route differs (dataset: {dataset_route}, "
                    f"target: {target_route})."
                )
                compatibility = CompatibilityLevel.LOW
        reasons.append(
            f"Evidence class {manifest.evidence_class.value}; dataset role {payload.role.value}."
        )
        matches.append(
            RegistryMatch(manifest=manifest, compatibility=compatibility, reasons=tuple(reasons))
        )
    return _sorted_by_compatibility(matches)


def match_parameter_evidence(
    *,
    compound_id: str | None = None,
    target: str | None = None,
    canonical_parameter_id: str | None = None,
    backend: RegistryBackend,
) -> list[RegistryMatch]:
    """Registered PARAMETER_EVIDENCE records matching any of the given criteria.

    Requires at least one real criterion match -- a record matching none of
    ``compound_id``/``target``/``canonical_parameter_id`` is never returned,
    even if it is the only PARAMETER_EVIDENCE record that exists.
    ``canonical_parameter_id`` matches this project's own naming convention
    (``sdk.parameter_identity``): a record's own ``parameter_id`` is either
    exactly the canonical id or ends with ``.<canonical_id>`` (e.g.
    ``"aciclovir.renal_clearance"``) -- an exact structural check, not fuzzy
    string matching.
    """
    matches: list[RegistryMatch] = []
    for manifest in backend.list(RegistryRecordKind.PARAMETER_EVIDENCE):
        _, payload = backend.get(manifest.record_id)
        reasons: list[str] = []
        score = 0
        payload_compound_id = getattr(payload, "compound_id", None)
        payload_target = getattr(payload, "target", None)
        payload_parameter_id = getattr(payload, "parameter_id", None)
        if compound_id is not None and payload_compound_id == compound_id:
            reasons.append(f"Compound identity matches: compound_id={compound_id!r}.")
            score += 1
        if target is not None and payload_target == target:
            reasons.append(f"Parameter target matches: {target!r}.")
            score += 1
        if canonical_parameter_id is not None and payload_parameter_id is not None and (
            payload_parameter_id == canonical_parameter_id
            or payload_parameter_id.endswith(f".{canonical_parameter_id}")
        ):
            reasons.append(f"Canonical parameter identity matches: {canonical_parameter_id!r}.")
            score += 1
        if not reasons:
            continue
        compatibility = CompatibilityLevel.HIGH if score >= 2 else CompatibilityLevel.MODERATE
        reasons.append(f"Evidence class {manifest.evidence_class.value}.")
        matches.append(
            RegistryMatch(manifest=manifest, compatibility=compatibility, reasons=tuple(reasons))
        )
    return _sorted_by_compatibility(matches)


def match_summary(match: RegistryMatch) -> dict[str, Any]:
    """A JSON-friendly view of one match -- the shape Studio's bridge exposes."""
    manifest = match.manifest
    return {
        "record_id": manifest.record_id,
        "logical_id": manifest.logical_id,
        "kind": manifest.kind.value,
        "evidence_class": manifest.evidence_class.value,
        "license": manifest.license,
        "compatibility": match.compatibility.value,
        "reasons": list(match.reasons),
    }
