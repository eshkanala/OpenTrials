"""Solver-independent contracts for declarative simulation uncertainty."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrials.core.distributions import Distribution, DistributionPurpose


class SamplingMethod(StrEnum):
    """Supported deterministic sampling-plan algorithms.

    This contract declares an intended algorithm only. Materializing draws is a
    later execution concern.
    """

    MONTE_CARLO = "MONTE_CARLO"
    LATIN_HYPERCUBE = "LATIN_HYPERCUBE"


class UncertainParameter(BaseModel):
    """One model input whose *knowledge* uncertainty will be sampled.

    ``target`` is deliberately solver-independent. An engine adapter later
    translates it to an engine-specific mutable parameter path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    distribution: Distribution
    description: str | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_ids", "provenance_ids")
    @classmethod
    def validate_identifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Uncertain-parameter identifiers cannot be blank.")
        if len(values) != len(set(values)):
            raise ValueError("Uncertain-parameter identifiers must be unique.")
        return values

    @model_validator(mode="after")
    def validate_parameter_uncertainty(self) -> Self:
        if self.distribution.purpose is not DistributionPurpose.PARAMETER_UNCERTAINTY:
            raise ValueError(
                "Uncertain parameters require a distribution with purpose PARAMETER_UNCERTAINTY; "
                "population and measurement variability have distinct semantics."
            )
        return self


class CorrelationGroup(BaseModel):
    """A validated correlation matrix over a named subset of uncertain inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str = Field(min_length=1)
    parameter_ids: tuple[str, ...] = Field(min_length=2)
    matrix: tuple[tuple[float, ...], ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        count = len(self.parameter_ids)
        if len(self.parameter_ids) != len(set(self.parameter_ids)):
            raise ValueError("Correlation-group parameter IDs must be unique.")
        if any(not parameter_id.strip() for parameter_id in self.parameter_ids):
            raise ValueError("Correlation-group parameter IDs cannot be blank.")
        if len(self.matrix) != count or any(len(row) != count for row in self.matrix):
            raise ValueError("Correlation matrix dimensions must match its parameter IDs.")
        for row_index, row in enumerate(self.matrix):
            for column_index, value in enumerate(row):
                if not -1.0 <= value <= 1.0:
                    raise ValueError("Correlation coefficients must be within [-1, 1].")
                if abs(value - self.matrix[column_index][row_index]) > 1e-12:
                    raise ValueError("Correlation matrices must be symmetric.")
            if abs(row[row_index] - 1.0) > 1e-12:
                raise ValueError("Correlation matrices require 1.0 on the diagonal.")
        _require_positive_semidefinite(self.matrix)
        return self


def _require_positive_semidefinite(matrix: tuple[tuple[float, ...], ...]) -> None:
    """Reject correlation matrices that cannot represent a covariance structure.

    A small LDLᵀ decomposition accepts singular positive-semidefinite matrices
    without introducing a numerical dependency for this declarative layer.
    """

    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    diagonal = [0.0] * size
    tolerance = 1e-12
    for column in range(size):
        pivot = matrix[column][column] - sum(
            lower[column][index] ** 2 * diagonal[index] for index in range(column)
        )
        if pivot < -tolerance:
            raise ValueError("Correlation matrix must be positive semidefinite.")
        diagonal[column] = max(pivot, 0.0)
        lower[column][column] = 1.0
        for row in range(column + 1, size):
            residual = matrix[row][column] - sum(
                lower[row][index] * lower[column][index] * diagonal[index]
                for index in range(column)
            )
            if diagonal[column] <= tolerance:
                if abs(residual) > tolerance:
                    raise ValueError("Correlation matrix must be positive semidefinite.")
                lower[row][column] = 0.0
            else:
                lower[row][column] = residual / diagonal[column]


class UncertaintySamplingPlan(BaseModel):
    """A deterministic request to materialize uncertain parameter assignments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: SamplingMethod
    requested_draw_count: int = Field(gt=0)
    requested_seed: int = Field(ge=0)


class UncertaintyScenario(BaseModel):
    """Immutable, solver-independent declaration of a simulation uncertainty study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(pattern=r"^OTUSC-[A-Za-z0-9_-]+$")
    target_model_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    parameters: tuple[UncertainParameter, ...] = Field(min_length=1)
    correlations: tuple[CorrelationGroup, ...] = ()
    sampling: UncertaintySamplingPlan
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()

    @field_validator("evidence_ids", "provenance_ids", "assumptions")
    @classmethod
    def validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Uncertainty-scenario identifiers cannot be blank.")
        if len(values) != len(set(values)):
            raise ValueError("Uncertainty-scenario identifiers must be unique.")
        return values

    @model_validator(mode="after")
    def validate_parameter_and_correlation_identity(self) -> Self:
        parameter_ids = tuple(parameter.parameter_id for parameter in self.parameters)
        targets = tuple(parameter.target for parameter in self.parameters)
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("Uncertainty-scenario parameter IDs must be unique.")
        if len(targets) != len(set(targets)):
            raise ValueError("Uncertainty-scenario parameter targets must be unique.")
        group_ids = tuple(group.group_id for group in self.correlations)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Uncertainty-scenario correlation-group IDs must be unique.")
        correlated_parameters: set[str] = set()
        known_parameters = set(parameter_ids)
        for group in self.correlations:
            unknown = set(group.parameter_ids) - known_parameters
            if unknown:
                raise ValueError(
                    "Correlation groups reference unknown uncertain parameters: "
                    f"{sorted(unknown)!r}."
                )
            overlap = correlated_parameters.intersection(group.parameter_ids)
            if overlap:
                raise ValueError(
                    "A parameter can belong to at most one correlation group; found overlap: "
                    f"{sorted(overlap)!r}."
                )
            correlated_parameters.update(group.parameter_ids)
        return self
