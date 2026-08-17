"""End-to-end extreme-responder analysis: select, persist, compare baseline.

verified OTPK -> extreme OTXMEM -> reference OTXMEM -> baseline OTXCMP.

Ties the pieces from this milestone together without adding any new trust
decision of its own: each store call independently reverifies its own
sources exactly as if called directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from opentrials.analysis.baseline_comparison import BaselineComparisonResult
from opentrials.cohort.definitions import FieldCatalog
from opentrials.responders.baseline_comparison import compare_baseline_characteristics
from opentrials.responders.definitions import ExtremeResponderDefinition
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.responder_comparisons import (
    ResponderComparisonArtifactManifest,
    ResponderComparisonArtifactStore,
)
from opentrials.storage.responder_membership import (
    ExtremeResponderMembershipArtifactManifest,
    ExtremeResponderMembershipArtifactStore,
    ResponderGroupKind,
)


@dataclass(frozen=True)
class ExtremeResponderAnalysis:
    """Locations and manifests for one complete immutable responder analysis."""

    extreme_membership_id: str
    reference_membership_id: str
    comparison_id: str
    extreme_manifest: ExtremeResponderMembershipArtifactManifest
    reference_manifest: ExtremeResponderMembershipArtifactManifest
    comparison_manifest: ResponderComparisonArtifactManifest
    comparison_result: BaselineComparisonResult


def run_extreme_responder_analysis(
    *,
    definition: ExtremeResponderDefinition,
    extreme_label: str,
    reference_label: str,
    baseline_field_ids: tuple[str, ...],
    field_catalog: FieldCatalog,
    endpoint_store: PkEndpointArtifactStore,
    population_store: PopulationArtifactStore,
    membership_root: Path,
    comparison_root: Path,
) -> ExtremeResponderAnalysis:
    """Select an extreme tail, persist both groups, and compare their baselines."""
    membership_store = ExtremeResponderMembershipArtifactStore(
        membership_root, endpoint_store=endpoint_store, population_store=population_store
    )
    suffix = definition.definition_id.removeprefix("OTRESP-")
    unique = uuid.uuid4().hex[:8]
    extreme_id = f"OTXMEM-{suffix}-extreme-{unique}"
    reference_id = f"OTXMEM-{suffix}-reference-{unique}"

    membership_store.create_membership(extreme_id)
    extreme_manifest = membership_store.write_membership(
        extreme_id, definition=definition, group_kind=ResponderGroupKind.EXTREME
    )
    membership_store.create_membership(reference_id)
    reference_manifest = membership_store.write_membership(
        reference_id, definition=definition, group_kind=ResponderGroupKind.REFERENCE
    )

    result = compare_baseline_characteristics(
        extreme_membership_id=extreme_id,
        reference_membership_id=reference_id,
        extreme_label=extreme_label,
        reference_label=reference_label,
        field_ids=baseline_field_ids,
        membership_store=membership_store,
        population_store=population_store,
        field_catalog=field_catalog,
    )

    comparison_store = ResponderComparisonArtifactStore(comparison_root)
    comparison_id = f"OTXCMP-{suffix}-{unique}"
    comparison_store.create_comparison(comparison_id)
    comparison_manifest = comparison_store.write_comparison(comparison_id, result)

    return ExtremeResponderAnalysis(
        extreme_membership_id=extreme_id,
        reference_membership_id=reference_id,
        comparison_id=comparison_id,
        extreme_manifest=extreme_manifest,
        reference_manifest=reference_manifest,
        comparison_manifest=comparison_manifest,
        comparison_result=result,
    )
