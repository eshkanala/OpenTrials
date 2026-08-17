"""Join two verified responder memberships to their source population's baseline fields.

Purely descriptive: no causal or inferential claim. Numeric fields (age,
weight, height, BMI, ...) get ``DescriptiveSummary`` statistics and mean
differences; categorical fields (sex, ...) get simple category counts.
"""

from __future__ import annotations

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from opentrials.analysis.baseline_comparison import (
    BaselineComparisonResult,
    CategoricalFieldSummary,
    NumericFieldComparison,
    NumericFieldSummary,
)
from opentrials.analysis.descriptive import calculate_descriptive_summary
from opentrials.cohort.definitions import FieldCatalog, LogicalField, LogicalFieldKind
from opentrials.responders.selection import RankedSubject
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.responder_membership import ExtremeResponderMembershipArtifactStore


def compare_baseline_characteristics(
    *,
    extreme_membership_id: str,
    reference_membership_id: str,
    extreme_label: str,
    reference_label: str,
    field_ids: tuple[str, ...],
    membership_store: ExtremeResponderMembershipArtifactStore,
    population_store: PopulationArtifactStore,
    field_catalog: FieldCatalog,
) -> BaselineComparisonResult:
    """Strictly join two verified OTXMEM groups to their source population's fields.

    Both memberships are independently reverified (including row-hash
    recomputation against the real population table) before any field value
    is read; this function performs no trust decision of its own beyond
    that. Restricting ``field_ids`` to a small, explicitly cataloged set (for
    example age/sex/weight/height/BMI) is the caller's responsibility.
    """
    if extreme_membership_id == reference_membership_id:
        raise ValueError("Baseline comparison requires two distinct memberships.")
    if not field_ids:
        raise ValueError("At least one baseline field is required.")

    extreme_manifest = membership_store.verify_membership(extreme_membership_id)
    reference_manifest = membership_store.verify_membership(reference_membership_id)
    if (
        extreme_manifest.source_generation_id != reference_manifest.source_generation_id
        or extreme_manifest.source_population_semantic_sha256
        != reference_manifest.source_population_semantic_sha256
    ):
        raise ValueError(
            "Extreme and reference memberships originate from different generated populations."
        )

    population_manifest = population_store.verify_population(extreme_manifest.source_generation_id)
    if (
        population_manifest.individuals.semantic_content_sha256
        != extreme_manifest.source_population_semantic_sha256
    ):
        raise ValueError("Population hash does not match the compared memberships.")

    population_table = pq.read_table(
        population_store.root
        / extreme_manifest.source_generation_id
        / population_manifest.individuals.path
    )
    population_columns = set(population_table.column_names)
    population_rows = population_table.to_pylist()

    fields = [field_catalog.field(field_id) for field_id in field_ids]
    missing_columns = {field.source_column for field in fields} - population_columns
    if missing_columns:
        raise ValueError(f"Population table lacks catalog columns: {sorted(missing_columns)!r}.")

    extreme_members = membership_store.read_member_rows(extreme_membership_id)
    reference_members = membership_store.read_member_rows(reference_membership_id)

    numeric_summaries: list[NumericFieldSummary] = []
    numeric_comparisons: list[NumericFieldComparison] = []
    categorical_summaries: list[CategoricalFieldSummary] = []

    for field in fields:
        extreme_summary = _summarize_field(
            extreme_label, extreme_membership_id, field, extreme_members, population_rows
        )
        reference_summary = _summarize_field(
            reference_label, reference_membership_id, field, reference_members, population_rows
        )
        if field.kind is LogicalFieldKind.NUMERIC:
            assert isinstance(extreme_summary, NumericFieldSummary)
            assert isinstance(reference_summary, NumericFieldSummary)
            numeric_summaries.extend((extreme_summary, reference_summary))
            assert field.unit is not None
            numeric_comparisons.append(
                _compare_numeric_field(
                    field.field_id, field.unit, extreme_summary, reference_summary
                )
            )
        else:
            assert isinstance(extreme_summary, CategoricalFieldSummary)
            assert isinstance(reference_summary, CategoricalFieldSummary)
            categorical_summaries.extend((extreme_summary, reference_summary))

    return BaselineComparisonResult(
        extreme_membership_id=extreme_membership_id,
        reference_membership_id=reference_membership_id,
        extreme_label=extreme_label,
        reference_label=reference_label,
        extreme_membership_semantic_sha256=extreme_manifest.members.semantic_content_sha256,
        reference_membership_semantic_sha256=reference_manifest.members.semantic_content_sha256,
        source_generation_id=extreme_manifest.source_generation_id,
        source_population_semantic_sha256=extreme_manifest.source_population_semantic_sha256,
        field_catalog_sha256=field_catalog.canonical_sha256(),
        numeric_summaries=tuple(numeric_summaries),
        numeric_comparisons=tuple(numeric_comparisons),
        categorical_summaries=tuple(categorical_summaries),
    )


def _summarize_field(
    group_label: str,
    membership_id: str,
    field: LogicalField,
    members: tuple[RankedSubject, ...],
    population_rows: list[dict[str, object]],
) -> NumericFieldSummary | CategoricalFieldSummary:
    values: list[object] = [
        population_rows[member.source_row_index][field.source_column] for member in members
    ]

    if field.kind is LogicalFieldKind.NUMERIC:
        numeric_values: list[float] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Baseline field {field.field_id!r} has a non-numeric value.")
            numeric_values.append(float(value))
        assert field.unit is not None
        return NumericFieldSummary(
            group_label=group_label,
            membership_id=membership_id,
            field_id=field.field_id,
            unit=field.unit,
            n_members=len(members),
            summary=calculate_descriptive_summary(numeric_values) if numeric_values else None,
        )

    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return CategoricalFieldSummary(
        group_label=group_label,
        membership_id=membership_id,
        field_id=field.field_id,
        n_members=len(members),
        category_counts=counts,
    )


def _compare_numeric_field(
    field_id: str, unit: str, extreme: NumericFieldSummary, reference: NumericFieldSummary
) -> NumericFieldComparison:
    extreme_mean = extreme.summary.mean if extreme.summary is not None else None
    reference_mean = reference.summary.mean if reference.summary is not None else None
    absolute_difference = (
        extreme_mean - reference_mean
        if extreme_mean is not None and reference_mean is not None
        else None
    )
    relative_difference = (
        absolute_difference / reference_mean
        if absolute_difference is not None and reference_mean is not None and reference_mean != 0.0
        else None
    )
    return NumericFieldComparison(
        field_id=field_id,
        unit=unit,
        extreme_mean=extreme_mean,
        reference_mean=reference_mean,
        absolute_difference=absolute_difference,
        relative_difference=relative_difference,
    )
