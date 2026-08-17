"""Pure result types for a strict, verified two-group cohort PK comparison.

These types carry no storage or cohort-evaluation dependency so both the
join/comparison logic (``opentrials.cohort.comparison``) and its immutable
artifact persistence (``opentrials.storage.cohort_comparisons``) can depend on
them without creating an import cycle.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.analysis.descriptive import DescriptiveSummary
from opentrials.analysis.pk import PkEndpointType
from opentrials.models.package import SHA256_PATTERN


class OverlapPolicy(StrEnum):
    """How a comparison must treat population rows shared by both groups."""

    ALLOWED_AND_REPORTED = "ALLOWED_AND_REPORTED"
    REQUIRE_DISJOINT = "REQUIRE_DISJOINT"


class OverlapReport(BaseModel):
    """Explicit accounting of shared population rows between two groups."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    policy: OverlapPolicy
    group_a_n: int = Field(ge=0)
    group_b_n: int = Field(ge=0)
    overlap_n: int = Field(ge=0)
    group_a_only_n: int = Field(ge=0)
    group_b_only_n: int = Field(ge=0)


class GroupEndpointSummary(BaseModel):
    """Descriptive PK summary for one group and one endpoint type."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    group_label: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    unit: str = Field(min_length=1)
    n_members: int = Field(ge=0)
    n_matched: int = Field(ge=0)
    n_missing: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    summary: DescriptiveSummary | None

    @model_validator(mode="after")
    def consistent_counts(self) -> GroupEndpointSummary:
        if self.n_matched + self.n_missing != self.n_members:
            raise ValueError("Matched and missing counts must sum to the group member count.")
        if (self.summary is None) != (self.n_matched == 0):
            raise ValueError("A descriptive summary is required exactly when matches exist.")
        return self


class EndpointComparison(BaseModel):
    """Group-A-vs-group-B mean comparison for one endpoint type."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    endpoint_type: PkEndpointType
    unit: str
    group_a_mean: float | None
    group_b_mean: float | None
    absolute_difference: float | None
    relative_difference: float | None

    @model_validator(mode="after")
    def consistent_differences(self) -> EndpointComparison:
        both_present = self.group_a_mean is not None and self.group_b_mean is not None
        if (self.absolute_difference is not None) != both_present:
            raise ValueError("An absolute difference requires both group means.")
        if self.relative_difference is not None and (
            self.absolute_difference is None or self.group_a_mean == 0.0
        ):
            raise ValueError("A relative difference requires a nonzero group-A mean.")
        return self


class CohortPkComparisonResult(BaseModel):
    """Complete, verifiable result of one strict two-group OTPK comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    group_a_membership_id: str = Field(min_length=1)
    group_b_membership_id: str = Field(min_length=1)
    group_a_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    group_b_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    group_a_label: str = Field(min_length=1)
    group_b_label: str = Field(min_length=1)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    source_endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    overlap: OverlapReport
    group_summaries: tuple[GroupEndpointSummary, ...]
    comparisons: tuple[EndpointComparison, ...]
