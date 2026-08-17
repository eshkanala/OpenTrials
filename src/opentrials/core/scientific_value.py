"""A provenance-capable, unit-aware scientific quantity."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, cast

from pint import Quantity
from pint.errors import DimensionalityError, UndefinedUnitError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from opentrials.core.distributions import Distribution
from opentrials.core.exceptions import InvalidUnitError, UnitCompatibilityError
from opentrials.core.units import unit_registry


class ValueType(StrEnum):
    """How a scientific value entered the system."""

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    FITTED = "FITTED"
    INFERRED = "INFERRED"
    PREDICTED = "PREDICTED"
    ASSUMED = "ASSUMED"
    CALIBRATED = "CALIBRATED"


class ScientificValue(BaseModel):
    """A numerical value that retains its unit and scientific context.

    The primary value remains a point estimate. Its optional uncertainty is an
    explicit typed distribution rather than an overloaded numeric field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float = Field(description="Numerical magnitude in the stated unit.")
    unit: str = Field(min_length=1, description="Original unit supplied by the source.")
    value_type: ValueType
    uncertainty: Distribution | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    provenance_id: str | None = None
    method: str | None = None
    species: str | None = None
    population: str | None = None
    tissue: str | None = None
    version: str | None = None
    quality_flags: tuple[str, ...] = ()

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        """Reject units that cannot be parsed before they enter scientific state."""
        try:
            unit_registry.Unit(value)
        except UndefinedUnitError as error:
            raise InvalidUnitError(f"Unknown unit: {value!r}") from error
        return value

    def quantity(self) -> Quantity[float]:
        """Return this value as a Pint quantity from the shared registry."""
        return cast(Quantity[float], unit_registry.Quantity(self.value, self.unit))

    def to(self, unit: str) -> ScientificValue:
        """Return an equivalent value in a compatible target unit.

        The returned object retains all scientific metadata and records the
        requested target unit as its unit; the source object is immutable.
        """
        try:
            converted = self.quantity().to(unit)
        except UndefinedUnitError as error:
            raise InvalidUnitError(f"Unknown unit: {unit!r}") from error
        except DimensionalityError as error:
            raise UnitCompatibilityError(
                f"Cannot convert {self.unit!r} to incompatible unit {unit!r}."
            ) from error
        return self.model_copy(update={"value": float(converted.magnitude), "unit": unit})

    def canonical_json(self) -> str:
        """Serialize deterministically for hashing, manifests, and reproducibility."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
