"""Pure result types for a prospective multi-arm trial PK comparison.

Distinct from ``analysis.cohort_comparison`` (OTCPK): that compares two
subgroups drawn from *one shared* verified endpoint artifact. Here each arm
was independently executed through OSP and has its *own* endpoint artifact;
what they share is the same source population and OTALLOC allocation. Purely
descriptive -- no inferential claim, no causal language.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.descriptive import DescriptiveSummary
from opentrials.analysis.pk import PkEndpointType
from opentrials.models.package import SHA256_PATTERN

DESCRIPTIVE_ONLY_NOTE = (
    "Descriptive only: reports observed PK differences between prospectively assigned trial "
    "arms in this one simulation. Does not imply a particular biological relationship or "
    "clinical claim."
)


class ArmEndpointSummary(BaseModel):
    """Descriptive PK summary for one arm and one endpoint type."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    unit: str = Field(min_length=1)
    n: int = Field(gt=0)
    summary: DescriptiveSummary


class ArmPairwiseComparison(BaseModel):
    """Arm-A-vs-arm-B mean comparison for one endpoint type."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    arm_a_id: str = Field(min_length=1)
    arm_b_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    unit: str = Field(min_length=1)
    arm_a_mean: float
    arm_b_mean: float
    absolute_difference: float
    relative_difference: float | None


class TrialArmComparisonResult(BaseModel):
    """Complete, verifiable result of one prospective multi-arm PK comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    allocation_id: str = Field(pattern=r"^OTALLOC-[A-Za-z0-9_-]+$")
    allocation_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    arm_endpoint_ids: dict[str, str]
    arm_endpoint_semantic_sha256: dict[str, str]
    arm_summaries: tuple[ArmEndpointSummary, ...]
    pairwise_comparisons: tuple[ArmPairwiseComparison, ...]
    interpretation_note: str = DESCRIPTIVE_ONLY_NOTE
