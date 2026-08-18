"""Pure result types for a paired cross-physiology-state PK comparison.

Distinct from ``analysis.arm_comparison``: trial arms compare *different*
prospective subgroups of one population. Physiology states compare the
*same* individuals executed under different declared physiological-state
overrides -- subject 17 at GFR x1.0 is paired against subject 17 at GFR
x0.6, never against a different individual. Purely descriptive -- no
inferential claim, and never disease/impairment-severity language.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.descriptive import DescriptiveSummary
from opentrials.analysis.pk import PkEndpointType
from opentrials.models.package import SHA256_PATTERN
from opentrials.physiology.overrides import PhysiologyCoverageReport

DESCRIPTIVE_ONLY_NOTE = (
    "Descriptive only: reports observed paired PK differences for the same individuals "
    "executed under different declared physiological-state overrides in this one "
    "simulation. Does not imply a disease, impairment-severity, or clinical claim."
)


class PhysiologyStateEndpointSummary(BaseModel):
    """Descriptive PK summary for one declared physiological state and endpoint type."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    state_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    unit: str = Field(min_length=1)
    n: int = Field(gt=0)
    summary: DescriptiveSummary


class SubjectPhysiologyDelta(BaseModel):
    """One subject's paired baseline-vs-comparison-state PK delta."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    unit: str = Field(min_length=1)
    baseline_state_id: str = Field(min_length=1)
    comparison_state_id: str = Field(min_length=1)
    baseline_value: float
    comparison_value: float
    absolute_difference: float
    relative_difference: float | None


class PhysiologyComparisonMissingness(BaseModel):
    """Explicit accounting of which subjects entered the paired comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    expected_subject_count: int = Field(ge=0)
    complete_subject_count: int = Field(ge=0)
    excluded_subject_ids: tuple[str, ...] = ()


class PhysiologyTrialComparisonResult(BaseModel):
    """Complete, verifiable result of one paired cross-physiology-state PK comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    baseline_state_id: str = Field(min_length=1)
    state_physiology_population_ids: dict[str, str]
    state_endpoint_ids: dict[str, str]
    state_endpoint_semantic_sha256: dict[str, str]
    state_summaries: tuple[PhysiologyStateEndpointSummary, ...]
    subject_deltas: tuple[SubjectPhysiologyDelta, ...]
    missingness: PhysiologyComparisonMissingness
    coverage: PhysiologyCoverageReport
    interpretation_note: str = DESCRIPTIVE_ONLY_NOTE
