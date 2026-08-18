"""The report data model: every field here comes from an already-verified artifact.

Nothing in this module computes a scientific result. Means, standard
deviations, and percentiles here are values already produced by
``analysis.arm_comparison``/``analysis.pk``/``analysis.descriptive`` and
persisted by an artifact store; this model only carries them from a
verified artifact to a renderer. Where a report needs a summary statistic
an artifact does not already carry (the population-only report has no
``OTACMP`` comparison artifact to read from), it calls the exact same
``analysis.descriptive.calculate_descriptive_summary`` every other
comparison in this project already uses -- reusing shared analysis code,
not building a second one.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ReportHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_type: str = Field(pattern=r"^(trial|population)$")
    run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    trial_id: str | None = None
    generated_at: datetime


class ModelSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    version: str = Field(min_length=1)
    artifact_hash: str = Field(min_length=1)


class PopulationSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_id: str = Field(min_length=1)
    participant_count: int = Field(gt=0)
    reference_population: str = Field(min_length=1)
    requested_seed: int
    determinism_level: str = Field(min_length=1)


class ArmSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    dose_amount: float = Field(gt=0)
    dose_unit: str = Field(min_length=1)
    route: str = Field(min_length=1)
    participant_count: int = Field(gt=0)


class ObservationScheduleSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_id: str = Field(min_length=1)
    declared_times_min: tuple[float, ...] = Field(min_length=1)


class EndpointSummaryRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str | None
    endpoint_type: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    n: int = Field(gt=0)
    mean: float
    sample_standard_deviation: float | None
    coefficient_of_variation: float | None
    minimum: float
    maximum: float
    p25: float
    p50: float
    p75: float


class PairwiseComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_a_id: str = Field(min_length=1)
    arm_b_id: str = Field(min_length=1)
    endpoint_type: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    arm_a_mean: float
    arm_b_mean: float
    absolute_difference: float
    relative_difference: float | None


class ExecutionVerificationRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str | None
    model_hash_verified: bool
    route_container_verified: bool
    solver_executed: bool


class ConcentrationTimeSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    time_unit: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    points: tuple[tuple[float, float], ...] = Field(min_length=1)


class ProvenanceSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_sha256: str = Field(min_length=1)
    population_generation_id: str = Field(min_length=1)
    population_semantic_sha256: str = Field(min_length=1)
    trial_sha256: str | None = None
    allocation_id: str | None = None
    allocation_semantic_sha256: str | None = None
    comparison_id: str | None = None
    comparison_semantic_sha256: str | None = None
    software_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


class ReportData(BaseModel):
    """Everything one rendered report needs, assembled from verified artifacts only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: ReportHeader
    model: ModelSummarySection
    population: PopulationSummarySection
    arms: tuple[ArmSummarySection, ...] = Field(min_length=1)
    observation_schedule: ObservationScheduleSection | None = None
    endpoints: tuple[EndpointSummaryRow, ...] = Field(min_length=1)
    comparisons: tuple[PairwiseComparisonRow, ...] = ()
    concentration_time_series: tuple[ConcentrationTimeSeries, ...] = ()
    execution_verification: tuple[ExecutionVerificationRow, ...] = Field(min_length=1)
    provenance: ProvenanceSection
    limitations: tuple[str, ...] = Field(min_length=1)
    reproducibility: tuple[str, ...] = Field(min_length=1)
    source_run_directory: Path
    source_population_root: Path
