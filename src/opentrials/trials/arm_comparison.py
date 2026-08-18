"""Join independently-executed trial arms' endpoint artifacts for comparison.

Unlike ``cohort.comparison`` (OTCPK, two subgroups of *one* shared endpoint
artifact), each arm here was executed through its own separate batched OSP
run and has its own endpoint artifact. What ties them together is the same
source population and the same verified ``OTALLOC`` allocation: every
endpoint row's lineage is cross-checked against OTALLOC's own declared
per-arm membership before being trusted, catching any endpoint artifact that
does not actually correspond to what was allocated.
"""

from __future__ import annotations

from collections.abc import Mapping

from opentrials.analysis.arm_comparison import (
    ArmEndpointSummary,
    ArmPairwiseComparison,
    TrialArmComparisonResult,
)
from opentrials.analysis.descriptive import calculate_descriptive_summary
from opentrials.analysis.pk import PkEndpointType
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore


def compare_trial_arms(
    *,
    allocation_id: str,
    arm_endpoint_ids: Mapping[str, str],
    allocation_store: TrialArmAllocationArtifactStore,
    endpoint_stores: Mapping[str, PkEndpointArtifactStore],
) -> TrialArmComparisonResult:
    """Strictly join every arm's verified endpoint artifact to OTALLOC and compare.

    ``arm_endpoint_ids``/``endpoint_stores`` must cover the same set of arm
    IDs. Every endpoint row's population-row lineage is required to be
    exactly the set OTALLOC declared for that arm -- no extra rows, none
    missing -- before any statistic is computed.
    """
    if len(arm_endpoint_ids) < 2:
        raise ValueError("Comparing trial arms requires at least two arms.")
    if set(arm_endpoint_ids) != set(endpoint_stores):
        raise ValueError("arm_endpoint_ids and endpoint_stores must cover the same arm IDs.")

    allocation_manifest = allocation_store.verify_allocation(allocation_id)
    arm_ids = sorted(arm_endpoint_ids)

    endpoint_manifest_hashes: dict[str, str] = {}
    rows_by_arm: dict[str, tuple[dict[str, object], ...]] = {}
    for arm_id in arm_ids:
        endpoint_store = endpoint_stores[arm_id]
        endpoint_id = arm_endpoint_ids[arm_id]
        endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
        if (
            not endpoint_manifest.population_lineage_present
            or endpoint_manifest.source_generation_id != allocation_manifest.source_generation_id
            or endpoint_manifest.source_population_semantic_sha256
            != allocation_manifest.source_population_semantic_sha256
        ):
            raise ValueError(
                f"Arm {arm_id!r} endpoint artifact lacks lineage matching this allocation's "
                "source population."
            )
        endpoint_manifest_hashes[arm_id] = endpoint_manifest.endpoints.semantic_content_sha256

        allocated_indexes = {
            row["source_row_index"]
            for row in allocation_store.read_rows_for_arm(allocation_id, arm_id)
        }
        rows = endpoint_store.read_rows(endpoint_id)
        actual_indexes = {row["source_population_row_index"] for row in rows}
        if actual_indexes != allocated_indexes:
            raise ValueError(
                f"Arm {arm_id!r} endpoint lineage does not exactly match OTALLOC's declared "
                "membership for this arm."
            )
        rows_by_arm[arm_id] = rows

    all_endpoint_types: set[PkEndpointType] = set()
    for rows in rows_by_arm.values():
        for row in rows:
            raw_endpoint_type = row["endpoint_type"]
            assert isinstance(raw_endpoint_type, str)
            all_endpoint_types.add(PkEndpointType(raw_endpoint_type))
    endpoint_types = sorted(all_endpoint_types, key=lambda endpoint_type: endpoint_type.value)

    summaries: list[ArmEndpointSummary] = []
    for arm_id in arm_ids:
        for endpoint_type in endpoint_types:
            matching = [row for row in rows_by_arm[arm_id] if row["endpoint_type"] == endpoint_type]
            if not matching:
                continue
            units = {str(row["unit"]) for row in matching}
            if len(units) > 1:
                raise ValueError(
                    f"Arm {arm_id!r} has inconsistent units for {endpoint_type.value}: "
                    f"{sorted(units)!r}."
                )
            values = [float(row["value"]) for row in matching]  # type: ignore[arg-type]
            summaries.append(
                ArmEndpointSummary(
                    arm_id=arm_id,
                    endpoint_type=endpoint_type,
                    unit=str(next(iter(units))),
                    n=len(values),
                    summary=calculate_descriptive_summary(values),
                )
            )

    comparisons: list[ArmPairwiseComparison] = []
    for endpoint_type in endpoint_types:
        by_arm = {
            summary.arm_id: summary
            for summary in summaries
            if summary.endpoint_type == endpoint_type
        }
        for index, arm_a in enumerate(arm_ids):
            if arm_a not in by_arm:
                continue
            for arm_b in arm_ids[index + 1 :]:
                if arm_b not in by_arm:
                    continue
                summary_a = by_arm[arm_a]
                summary_b = by_arm[arm_b]
                if summary_a.unit != summary_b.unit:
                    raise ValueError(
                        f"Arms {arm_a!r} and {arm_b!r} use different units for "
                        f"{endpoint_type.value}: {summary_a.unit!r} vs {summary_b.unit!r}."
                    )
                mean_a = summary_a.summary.mean
                mean_b = summary_b.summary.mean
                absolute_difference = mean_b - mean_a
                relative_difference = (
                    absolute_difference / mean_a if mean_a != 0.0 else None
                )
                comparisons.append(
                    ArmPairwiseComparison(
                        arm_a_id=arm_a,
                        arm_b_id=arm_b,
                        endpoint_type=endpoint_type,
                        unit=summary_a.unit,
                        arm_a_mean=mean_a,
                        arm_b_mean=mean_b,
                        absolute_difference=absolute_difference,
                        relative_difference=relative_difference,
                    )
                )

    return TrialArmComparisonResult(
        allocation_id=allocation_id,
        allocation_semantic_sha256=allocation_manifest.allocation.semantic_content_sha256,
        source_generation_id=allocation_manifest.source_generation_id,
        source_population_semantic_sha256=allocation_manifest.source_population_semantic_sha256,
        arm_endpoint_ids=dict(arm_endpoint_ids),
        arm_endpoint_semantic_sha256=endpoint_manifest_hashes,
        arm_summaries=tuple(summaries),
        pairwise_comparisons=tuple(comparisons),
    )
