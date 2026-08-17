"""Solver-independent cohort definitions and registered logical field catalogs."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.serialization import sha256
from opentrials.core.units import unit_registry
from opentrials.models.package import SHA256_PATTERN

COHORT_ID_PATTERN = r"^OTCOH-[A-Za-z0-9_-]+$"
MEMBERSHIP_ID_PATTERN = r"^OTMEM-[A-Za-z0-9_-]+$"


class LogicalFieldKind(StrEnum):
    """The limited value types allowed in cohort predicates."""

    NUMERIC = "NUMERIC"
    CATEGORICAL = "CATEGORICAL"


class NumericOperator(StrEnum):
    """Supported numeric comparisons."""

    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    EQ = "EQ"


class LogicalField(BaseModel):
    """One named, auditable logical field backed by exactly one source column."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    kind: LogicalFieldKind
    source_column: str = Field(min_length=1)
    unit: str | None = None

    @model_validator(mode="after")
    def validate_unit(self) -> LogicalField:
        if self.kind is LogicalFieldKind.NUMERIC and self.unit is None:
            raise ValueError("Numeric logical fields require a canonical unit.")
        if self.kind is LogicalFieldKind.CATEGORICAL and self.unit is not None:
            raise ValueError("Categorical logical fields cannot declare a unit.")
        if self.unit is not None:
            try:
                unit_registry.Unit(self.unit)
            except Exception as error:  # Pint has several public exception types.
                raise ValueError(f"Invalid field unit: {self.unit!r}.") from error
        return self


class FieldCatalog(BaseModel):
    """Canonical, source-table-specific mapping for registered logical fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    catalog_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    source_schema: str = Field(min_length=1)
    subject_id_column: str = Field(min_length=1)
    fields: tuple[LogicalField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fields(self) -> FieldCatalog:
        ids = [field.field_id for field in self.fields]
        columns = [field.source_column for field in self.fields]
        if len(ids) != len(set(ids)) or len(columns) != len(set(columns)):
            raise ValueError("Field catalog logical IDs and source columns must be unique.")
        if self.subject_id_column in columns:
            raise ValueError("Subject ID column cannot also be a logical field.")
        return self

    def field(self, field_id: str) -> LogicalField:
        """Return a registered field, rejecting arbitrary source paths."""
        for field in self.fields:
            if field.field_id == field_id:
                return field
        raise ValueError(f"Cohort predicate references unregistered field {field_id!r}.")

    def canonical_sha256(self) -> str:
        """Return the content identity that definitions bind to."""
        return sha256(self)


class NumericPredicate(BaseModel):
    """Compare a registered numeric field using an explicitly unit-tagged value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = "numeric"
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    operator: NumericOperator
    value: float
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def finite_value_and_unit(self) -> NumericPredicate:
        if not math.isfinite(self.value):
            raise ValueError("Numeric predicate value must be finite.")
        try:
            unit_registry.Unit(self.unit)
        except Exception as error:
            raise ValueError(f"Invalid predicate unit: {self.unit!r}.") from error
        return self


class CategoricalPredicate(BaseModel):
    """Match one of a declared, non-empty set of categorical values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = "categorical"
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    values: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_values(self) -> CategoricalPredicate:
        if any(not value.strip() for value in self.values) or len(self.values) != len(
            set(self.values)
        ):
            raise ValueError("Categorical predicate values must be non-empty and unique.")
        return self


class PresencePredicate(BaseModel):
    """Require that a field is explicitly present or explicitly missing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = "presence"
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    present: bool


Predicate = NumericPredicate | CategoricalPredicate | PresencePredicate


class CohortKind(StrEnum):
    COHORT = "COHORT"
    SUBGROUP = "SUBGROUP"


class CohortDefinition(BaseModel):
    """Immutable AND-only logical selection bound to one population and catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    cohort_id: str = Field(pattern=COHORT_ID_PATTERN)
    kind: CohortKind = CohortKind.COHORT
    predicates: tuple[Predicate, ...] = Field(min_length=1)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    field_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    parent_membership_id: str | None = Field(default=None, pattern=MEMBERSHIP_ID_PATTERN)

    @model_validator(mode="after")
    def validate_parent_contract(self) -> CohortDefinition:
        if self.kind is CohortKind.SUBGROUP and self.parent_membership_id is None:
            raise ValueError("A subgroup definition requires a parent OTMEM membership reference.")
        if self.kind is CohortKind.COHORT and self.parent_membership_id is not None:
            raise ValueError("Only subgroup definitions may reference a parent membership.")
        return self

    def canonical_sha256(self) -> str:
        return sha256(self)
