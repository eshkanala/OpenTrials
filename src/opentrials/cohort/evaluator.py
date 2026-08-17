"""Pure evaluation of registered cohort predicates against raw population rows."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from opentrials.cohort.definitions import (
    CategoricalPredicate,
    CohortDefinition,
    CohortKind,
    FieldCatalog,
    LogicalFieldKind,
    NumericOperator,
    NumericPredicate,
    Predicate,
    PresencePredicate,
)
from opentrials.core.serialization import sha256
from opentrials.core.units import unit_registry
from opentrials.storage.populations import PopulationArtifactManifest


@dataclass(frozen=True)
class MembershipRow:
    """A stable reference to one complete source population row."""

    source_subject_id: str
    source_row_index: int
    source_row_sha256: str


@dataclass(frozen=True)
class EvaluatedMembership:
    """Pure evaluator output, ready for immutable membership persistence."""

    definition: CohortDefinition
    members: tuple[MembershipRow, ...]


def source_row_sha256(column_names: Sequence[str], row: Mapping[str, object]) -> str:
    """Hash every declared source-table cell, not merely fields used in selection."""
    columns = tuple(column_names)
    return sha256({"columns": columns, "row": {column: row[column] for column in columns}})


class CohortEvaluator:
    """Evaluate only the declarative, AND-only OpenTrials cohort DSL."""

    evaluator_id = "opentrials.cohort.pure"
    evaluator_version = "1.0.0"

    def evaluate(
        self,
        definition: CohortDefinition,
        *,
        field_catalog: FieldCatalog,
        source_manifest: PopulationArtifactManifest,
        source_columns: Sequence[str],
        source_rows: Sequence[Mapping[str, object]],
        parent_members: Sequence[MembershipRow] | None = None,
    ) -> EvaluatedMembership:
        """Return membership references without writing files or invoking a solver."""
        self._validate_bindings(definition, field_catalog, source_manifest, source_columns)
        allowed_indexes: set[int] | None = None
        if definition.kind is CohortKind.SUBGROUP:
            if parent_members is None:
                raise ValueError("Subgroup evaluation requires verified parent membership rows.")
            allowed_indexes = {member.source_row_index for member in parent_members}
            if any(index < 0 or index >= len(source_rows) for index in allowed_indexes):
                raise ValueError(
                    "Parent membership references a row outside the source population."
                )
        elif parent_members is not None:
            raise ValueError("Top-level cohort evaluation cannot receive parent membership rows.")

        members: list[MembershipRow] = []
        for row_index, row in enumerate(source_rows):
            if allowed_indexes is not None and row_index not in allowed_indexes:
                continue
            if self._matches(definition.predicates, field_catalog, row):
                members.append(
                    MembershipRow(
                        source_subject_id=str(row[field_catalog.subject_id_column]),
                        source_row_index=row_index,
                        source_row_sha256=source_row_sha256(source_columns, row),
                    )
                )
        if allowed_indexes is not None and len(members) >= len(allowed_indexes):
            raise ValueError(
                "A subgroup membership must be a strict subset of its parent membership."
            )
        return EvaluatedMembership(definition=definition, members=tuple(members))

    @staticmethod
    def _validate_bindings(
        definition: CohortDefinition,
        catalog: FieldCatalog,
        manifest: PopulationArtifactManifest,
        source_columns: Sequence[str],
    ) -> None:
        if definition.source_generation_id != manifest.generation_id:
            raise ValueError(
                "Cohort definition source generation does not match verified population."
            )
        if (
            definition.source_population_semantic_sha256
            != manifest.individuals.semantic_content_sha256
        ):
            raise ValueError(
                "Cohort definition population semantic hash does not match verified population."
            )
        if definition.field_catalog_sha256 != catalog.canonical_sha256():
            raise ValueError(
                "Cohort definition field catalog hash does not match the supplied catalog."
            )
        columns = set(source_columns)
        required = {catalog.subject_id_column, *(field.source_column for field in catalog.fields)}
        missing = required - columns
        if missing:
            raise ValueError(f"Population source table lacks catalog columns: {sorted(missing)!r}.")
        for predicate in definition.predicates:
            field = catalog.field(predicate.field_id)
            if (
                isinstance(predicate, NumericPredicate)
                and field.kind is not LogicalFieldKind.NUMERIC
            ):
                raise ValueError(f"Numeric predicate requires a numeric field: {field.field_id!r}.")
            if (
                isinstance(predicate, CategoricalPredicate)
                and field.kind is not LogicalFieldKind.CATEGORICAL
            ):
                raise ValueError(
                    f"Categorical predicate requires a categorical field: {field.field_id!r}."
                )

    def _matches(
        self, predicates: Sequence[Predicate], catalog: FieldCatalog, row: Mapping[str, object]
    ) -> bool:
        return all(self._matches_predicate(predicate, catalog, row) for predicate in predicates)

    @staticmethod
    def _matches_predicate(
        predicate: Predicate, catalog: FieldCatalog, row: Mapping[str, object]
    ) -> bool:
        field = catalog.field(predicate.field_id)
        value = row[field.source_column]
        if isinstance(predicate, PresencePredicate):
            return (value is not None) is predicate.present
        if value is None:
            return False
        if isinstance(predicate, CategoricalPredicate):
            return isinstance(value, str) and value in predicate.values
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            return False
        assert field.unit is not None
        try:
            converted = (float(value) * unit_registry.Unit(field.unit)).to(predicate.unit).magnitude
        except Exception as error:
            raise ValueError(
                f"Cannot convert field {field.field_id!r} from {field.unit!r} "
                f"to {predicate.unit!r}."
            ) from error
        converted_number = float(converted)
        target = predicate.value
        if predicate.operator is NumericOperator.LT:
            return converted_number < target
        if predicate.operator is NumericOperator.LTE:
            return converted_number <= target
        if predicate.operator is NumericOperator.GT:
            return converted_number > target
        if predicate.operator is NumericOperator.GTE:
            return converted_number >= target
        return converted_number == target
