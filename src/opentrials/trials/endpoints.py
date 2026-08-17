"""Endpoint definitions separating measurement from analysis."""

from __future__ import annotations

from enum import StrEnum

from pint.errors import UndefinedUnitError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.exceptions import InvalidUnitError, UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue
from opentrials.core.units import unit_registry


class EndpointType(StrEnum):
    """Scientific endpoint classes supported by the trial domain model."""

    PK = "PK"
    PD = "PD"
    BIOMARKER = "BIOMARKER"
    PHYSIOLOGIC = "PHYSIOLOGIC"
    CLINICAL = "CLINICAL"
    TIME_TO_EVENT = "TIME_TO_EVENT"
    SAFETY = "SAFETY"
    DISEASE_PROGRESSION = "DISEASE_PROGRESSION"


class EndpointAggregation(StrEnum):
    """How observations in an endpoint window will eventually be summarized."""

    RAW = "RAW"
    LAST = "LAST"
    MEAN = "MEAN"
    MEDIAN = "MEDIAN"
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    AUC = "AUC"
    TIME_TO_EVENT = "TIME_TO_EVENT"


class MissingnessRule(StrEnum):
    """Declared handling for missing endpoint observations."""

    EXCLUDE = "EXCLUDE"
    REPORT = "REPORT"
    IMPUTE_LATER = "IMPUTE_LATER"


class TimeWindow(BaseModel):
    """An inclusive measurement window relative to trial time zero."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: ScientificValue
    end: ScientificValue

    @model_validator(mode="after")
    def validate_time_window(self) -> TimeWindow:
        try:
            start_seconds = self.start.to("second").value
            end_seconds = self.end.to("second").value
        except UnitCompatibilityError as error:
            raise ValueError("Endpoint time-window bounds must have time dimensions.") from error
        if start_seconds < 0:
            raise ValueError("Endpoint time-window start cannot be negative.")
        if end_seconds < start_seconds:
            raise ValueError("Endpoint time-window end cannot precede its start.")
        return self


class Endpoint(BaseModel):
    """A fully declared measurement, window, and analysis contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint_id: str = Field(min_length=1)
    endpoint_type: EndpointType
    measurement: str = Field(min_length=1)
    time_window: TimeWindow
    aggregation: EndpointAggregation
    missingness_rule: MissingnessRule
    analysis_method: str = Field(min_length=1)
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unit(self) -> Endpoint:
        try:
            unit_registry.Unit(self.unit)
        except UndefinedUnitError as error:
            raise InvalidUnitError(f"Unknown unit: {self.unit!r}") from error
        if self.aggregation is EndpointAggregation.AUC:
            try:
                unit_registry.Unit(f"({self.unit}) * second")
            except UndefinedUnitError as error:
                raise InvalidUnitError(
                    f"Endpoint unit cannot form an AUC quantity: {self.unit!r}"
                ) from error
        return self
