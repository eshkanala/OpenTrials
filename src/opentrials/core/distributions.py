"""Explicit, unit-aware representations of scientific distributions."""

from __future__ import annotations

import json
import math
from enum import StrEnum

from pint.errors import UndefinedUnitError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrials.core.exceptions import InvalidUnitError
from opentrials.core.units import unit_registry


class DistributionPurpose(StrEnum):
    """Why a distribution exists; sampling semantics must remain distinct."""

    POPULATION_VARIABILITY = "POPULATION_VARIABILITY"
    PARAMETER_UNCERTAINTY = "PARAMETER_UNCERTAINTY"
    MEASUREMENT_UNCERTAINTY = "MEASUREMENT_UNCERTAINTY"


class DistributionType(StrEnum):
    """Supported distribution families for Phase 0 scientific state."""

    POINT = "POINT"
    NORMAL = "NORMAL"
    LOG_NORMAL = "LOG_NORMAL"
    UNIFORM = "UNIFORM"
    RANGE = "RANGE"
    EMPIRICAL = "EMPIRICAL"


_REQUIRED_PARAMETERS: dict[DistributionType, frozenset[str]] = {
    DistributionType.POINT: frozenset({"value"}),
    DistributionType.NORMAL: frozenset({"mean", "standard_deviation"}),
    DistributionType.LOG_NORMAL: frozenset({"log_mean", "log_standard_deviation"}),
    DistributionType.UNIFORM: frozenset({"lower", "upper"}),
    DistributionType.RANGE: frozenset({"lower", "upper"}),
    DistributionType.EMPIRICAL: frozenset(),
}


class Distribution(BaseModel):
    """A typed distribution whose magnitude is expressed in one stated unit.

    The model stores distribution *descriptions*, not random draws. Sampling
    behavior belongs to the future population/uncertainty engines, where seeds
    and solver configuration can be captured in run manifests.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_type: DistributionType
    purpose: DistributionPurpose = DistributionPurpose.PARAMETER_UNCERTAINTY
    unit: str = Field(min_length=1)
    parameters: dict[str, float] = Field(default_factory=dict)
    values: tuple[float, ...] = ()
    description: str | None = None

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        try:
            unit_registry.Unit(value)
        except UndefinedUnitError as error:
            raise InvalidUnitError(f"Unknown unit: {value!r}") from error
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Distribution:
        required = _REQUIRED_PARAMETERS[self.distribution_type]
        actual = frozenset(self.parameters)
        if actual != required:
            raise ValueError(
                f"{self.distribution_type} requires exactly parameter keys "
                f"{sorted(required)!r}; received {sorted(actual)!r}."
            )
        if any(not math.isfinite(value) for value in self.parameters.values()):
            raise ValueError("Distribution parameters must be finite.")
        if any(not math.isfinite(value) for value in self.values):
            raise ValueError("Empirical values must be finite.")

        if self.distribution_type is DistributionType.EMPIRICAL:
            if not self.values:
                raise ValueError("EMPIRICAL distributions require at least one value.")
        elif self.values:
            raise ValueError("Only EMPIRICAL distributions may define values.")

        if self.distribution_type in {DistributionType.NORMAL, DistributionType.LOG_NORMAL}:
            if (
                self.parameters[
                    "standard_deviation"
                    if self.distribution_type is DistributionType.NORMAL
                    else "log_standard_deviation"
                ]
                <= 0
            ):
                raise ValueError("Standard deviation must be greater than zero.")
        if self.distribution_type in {DistributionType.UNIFORM, DistributionType.RANGE}:
            if self.parameters["lower"] > self.parameters["upper"]:
                raise ValueError("Lower bound cannot exceed upper bound.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for manifests and reproducibility."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
