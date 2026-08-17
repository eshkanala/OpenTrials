"""Strict OTMEM <-> lineage-aware OTPK join and descriptive cohort PK comparison.

This module never joins on ``subject_id`` text. ``PkEndpointResult.subject_id``
is only an OSP execution label (for example an ``IndividualId``); it carries no
verified relationship to any generated population. The only trustworthy subject
identity is the population-row lineage recorded on a schema v2+ endpoint
artifact: ``(source_generation_id, source_population_semantic_sha256,
source_population_row_index, source_population_row_sha256)``. A cohort member's
own row identity is independently reverified against its source population by
``CohortMembershipArtifactStore.verify_membership``, so matching endpoint rows
against verified member rows -- rather than trusting endpoint-side lineage
claims alone -- fails safe: an endpoint row with a wrong or fabricated lineage
claim simply matches nothing.
"""

from __future__ import annotations

from opentrials.analysis.cohort_comparison import (
    CohortPkComparisonResult,
    EndpointComparison,
    GroupEndpointSummary,
    OverlapPolicy,
    OverlapReport,
)
from opentrials.analysis.descriptive import calculate_descriptive_summary
from opentrials.analysis.pk import PkEndpointType
from opentrials.cohort.evaluator import MembershipRow
from opentrials.cohort.storage import CohortMembershipArtifactStore
from opentrials.storage.endpoints import (
    MIN_LINEAGE_CAPABLE_SCHEMA_MAJOR,
    PkEndpointArtifactStore,
    schema_major_version,
)

__all__ = [
    "CohortPkComparisonResult",
    "EndpointComparison",
    "GroupEndpointSummary",
    "OverlapPolicy",
    "OverlapReport",
    "compare_cohort_pk_endpoints",
]


def compare_cohort_pk_endpoints(
    *,
    group_a_membership_id: str,
    group_b_membership_id: str,
    group_a_label: str,
    group_b_label: str,
    endpoint_id: str,
    membership_store: CohortMembershipArtifactStore,
    endpoint_store: PkEndpointArtifactStore,
    overlap_policy: OverlapPolicy = OverlapPolicy.ALLOWED_AND_REPORTED,
) -> CohortPkComparisonResult:
    """Strictly join two verified OTMEM groups to one lineage-aware OTPK artifact.

    Every group member row is independently reverified against its source
    population by ``verify_membership``. Endpoint rows are matched only by
    exact ``(row_index, row_sha256)`` identity against those verified member
    rows -- never by ``subject_id`` text.
    """
    if group_a_membership_id == group_b_membership_id:
        raise ValueError("A comparison requires two distinct cohort memberships.")

    manifest_a = membership_store.verify_membership(group_a_membership_id)
    manifest_b = membership_store.verify_membership(group_b_membership_id)
    if (
        manifest_a.source_generation_id != manifest_b.source_generation_id
        or manifest_a.source_population_semantic_sha256
        != manifest_b.source_population_semantic_sha256
    ):
        raise ValueError(
            "Group A and Group B originate from different generated populations and cannot be "
            "compared."
        )

    endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
    if (
        not endpoint_manifest.population_lineage_present
        or schema_major_version(endpoint_manifest.schema_version) < MIN_LINEAGE_CAPABLE_SCHEMA_MAJOR
    ):
        raise ValueError(
            "Endpoint artifact lacks population lineage. Schema v2+ required for cohort "
            "comparison."
        )
    if (
        endpoint_manifest.source_generation_id != manifest_a.source_generation_id
        or endpoint_manifest.source_population_semantic_sha256
        != manifest_a.source_population_semantic_sha256
    ):
        raise ValueError(
            "Endpoint artifact population lineage does not match the compared cohort groups."
        )

    members_a = membership_store.read_member_rows(group_a_membership_id)
    members_b = membership_store.read_member_rows(group_b_membership_id)
    index_set_a = {member.source_row_index for member in members_a}
    index_set_b = {member.source_row_index for member in members_b}
    overlap_n = len(index_set_a & index_set_b)
    if overlap_policy is OverlapPolicy.REQUIRE_DISJOINT and overlap_n > 0:
        raise ValueError(
            f"Group A and Group B overlap by {overlap_n} member(s); overlap policy "
            "REQUIRE_DISJOINT rejects this comparison."
        )
    overlap = OverlapReport(
        policy=overlap_policy,
        group_a_n=len(members_a),
        group_b_n=len(members_b),
        overlap_n=overlap_n,
        group_a_only_n=len(index_set_a - index_set_b),
        group_b_only_n=len(index_set_b - index_set_a),
    )

    endpoint_lookup, unit_by_endpoint_type = _build_lineage_lookup(
        endpoint_store.read_rows(endpoint_id)
    )

    endpoint_types = sorted(unit_by_endpoint_type, key=lambda endpoint_type: endpoint_type.value)
    summaries: list[GroupEndpointSummary] = []
    for group_label, membership_id, members in (
        (group_a_label, group_a_membership_id, members_a),
        (group_b_label, group_b_membership_id, members_b),
    ):
        for endpoint_type in endpoint_types:
            summaries.append(
                _summarize_group(
                    group_label,
                    membership_id,
                    endpoint_type,
                    unit_by_endpoint_type[endpoint_type],
                    members,
                    endpoint_lookup,
                )
            )

    comparisons = tuple(
        _compare_endpoint(
            endpoint_type,
            unit_by_endpoint_type[endpoint_type],
            _find_summary(summaries, group_a_membership_id, endpoint_type),
            _find_summary(summaries, group_b_membership_id, endpoint_type),
        )
        for endpoint_type in endpoint_types
    )

    return CohortPkComparisonResult(
        group_a_membership_id=group_a_membership_id,
        group_b_membership_id=group_b_membership_id,
        group_a_membership_semantic_sha256=manifest_a.members.semantic_content_sha256,
        group_b_membership_semantic_sha256=manifest_b.members.semantic_content_sha256,
        group_a_label=group_a_label,
        group_b_label=group_b_label,
        source_generation_id=manifest_a.source_generation_id,
        source_population_semantic_sha256=manifest_a.source_population_semantic_sha256,
        source_endpoint_id=endpoint_id,
        source_endpoint_semantic_sha256=endpoint_manifest.endpoints.semantic_content_sha256,
        overlap=overlap,
        group_summaries=tuple(summaries),
        comparisons=comparisons,
    )


_LineageKey = tuple[int, str]
_LineageLookup = dict[_LineageKey, dict[PkEndpointType, float]]


def _build_lineage_lookup(
    rows: tuple[dict[str, object], ...],
) -> tuple[_LineageLookup, dict[PkEndpointType, str]]:
    """Index verified endpoint rows by exact population-row lineage identity.

    Also derives one canonical unit per endpoint type across the whole
    artifact; a real, mixed-unit artifact would already have been rejected by
    ``calculate_pk_endpoints``, so a mismatch here indicates a malformed or
    tampered artifact and is rejected rather than silently resolved.
    """
    lookup: _LineageLookup = {}
    unit_by_endpoint_type: dict[PkEndpointType, str] = {}
    for row in rows:
        raw_endpoint_type = row["endpoint_type"]
        assert isinstance(raw_endpoint_type, str)
        endpoint_type = PkEndpointType(raw_endpoint_type)
        unit = row["unit"]
        assert isinstance(unit, str)
        existing_unit = unit_by_endpoint_type.setdefault(endpoint_type, unit)
        if existing_unit != unit:
            raise ValueError(
                f"Endpoint artifact has inconsistent units for {endpoint_type.value}: "
                f"{existing_unit!r} vs {unit!r}."
            )

        row_index = row["source_population_row_index"]
        row_hash = row["source_population_row_sha256"]
        if row_index is None or row_hash is None:
            continue
        assert isinstance(row_index, int)
        assert isinstance(row_hash, str)
        key = (row_index, row_hash)
        by_endpoint = lookup.setdefault(key, {})
        if endpoint_type in by_endpoint:
            raise ValueError(
                f"Endpoint artifact has duplicate {endpoint_type.value} rows for the same "
                "population row lineage."
            )
        value = row["value"]
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        by_endpoint[endpoint_type] = float(value)
    return lookup, unit_by_endpoint_type


def _summarize_group(
    group_label: str,
    membership_id: str,
    endpoint_type: PkEndpointType,
    unit: str,
    members: tuple[MembershipRow, ...],
    lookup: _LineageLookup,
) -> GroupEndpointSummary:
    matched_values = [
        entry[endpoint_type]
        for member in members
        for entry in (lookup.get((member.source_row_index, member.source_row_sha256), {}),)
        if endpoint_type in entry
    ]
    n_members = len(members)
    n_matched = len(matched_values)
    coverage = (n_matched / n_members) if n_members > 0 else 1.0
    return GroupEndpointSummary(
        group_label=group_label,
        membership_id=membership_id,
        endpoint_type=endpoint_type,
        unit=unit,
        n_members=n_members,
        n_matched=n_matched,
        n_missing=n_members - n_matched,
        coverage=coverage,
        summary=calculate_descriptive_summary(matched_values) if matched_values else None,
    )


def _find_summary(
    summaries: list[GroupEndpointSummary], membership_id: str, endpoint_type: PkEndpointType
) -> GroupEndpointSummary:
    for summary in summaries:
        if summary.membership_id == membership_id and summary.endpoint_type == endpoint_type:
            return summary
    raise AssertionError("Every requested group/endpoint-type summary must have been computed.")


def _compare_endpoint(
    endpoint_type: PkEndpointType,
    unit: str,
    group_a: GroupEndpointSummary,
    group_b: GroupEndpointSummary,
) -> EndpointComparison:
    mean_a = group_a.summary.mean if group_a.summary is not None else None
    mean_b = group_b.summary.mean if group_b.summary is not None else None
    absolute_difference = mean_b - mean_a if mean_a is not None and mean_b is not None else None
    relative_difference = (
        absolute_difference / mean_a
        if absolute_difference is not None and mean_a is not None and mean_a != 0.0
        else None
    )
    return EndpointComparison(
        endpoint_type=endpoint_type,
        unit=unit,
        group_a_mean=mean_a,
        group_b_mean=mean_b,
        absolute_difference=absolute_difference,
        relative_difference=relative_difference,
    )
