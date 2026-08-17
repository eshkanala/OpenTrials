"""Pure result types for an extreme-responder vs. reference baseline comparison.

Purely descriptive: summarizes and differences baseline population-table
fields (age, sex, weight, ...) between two groups. Never implies causation --
a higher or lower mean in one group is reported as an observation about this
one simulation, not a mechanism.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.analysis.descriptive import DescriptiveSummary
from opentrials.models.package import SHA256_PATTERN

DESCRIPTIVE_ONLY_NOTE = (
    "Descriptive only: reports observed differences in baseline characteristics between the "
    "selected extreme-responder group and the reference group for this one simulation. Does "
    "not imply causation."
)


class NumericFieldSummary(BaseModel):
    """Descriptive baseline-field summary for one group."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    group_label: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    n_members: int = Field(ge=0)
    summary: DescriptiveSummary | None

    @model_validator(mode="after")
    def consistent(self) -> NumericFieldSummary:
        if (self.summary is None) != (self.n_members == 0):
            raise ValueError("A descriptive summary is required exactly when members exist.")
        return self


class NumericFieldComparison(BaseModel):
    """Extreme-vs-reference mean comparison for one numeric baseline field."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    field_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    extreme_mean: float | None
    reference_mean: float | None
    absolute_difference: float | None
    relative_difference: float | None

    @model_validator(mode="after")
    def consistent_differences(self) -> NumericFieldComparison:
        both_present = self.extreme_mean is not None and self.reference_mean is not None
        if (self.absolute_difference is not None) != both_present:
            raise ValueError("An absolute difference requires both group means.")
        if self.relative_difference is not None and (
            self.absolute_difference is None or self.reference_mean == 0.0
        ):
            raise ValueError("A relative difference requires a nonzero reference-group mean.")
        return self


class CategoricalFieldSummary(BaseModel):
    """Category frequency counts for one baseline field within one group."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    group_label: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    n_members: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)


class BaselineComparisonResult(BaseModel):
    """Complete, verifiable result of one extreme-responder baseline comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    extreme_membership_id: str = Field(min_length=1)
    reference_membership_id: str = Field(min_length=1)
    extreme_label: str = Field(min_length=1)
    reference_label: str = Field(min_length=1)
    extreme_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    reference_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    field_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    numeric_summaries: tuple[NumericFieldSummary, ...]
    numeric_comparisons: tuple[NumericFieldComparison, ...]
    categorical_summaries: tuple[CategoricalFieldSummary, ...]
    interpretation_note: str = DESCRIPTIVE_ONLY_NOTE
