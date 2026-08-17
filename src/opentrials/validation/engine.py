"""Numerical PK validation over compatible observed and predicted series."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.pk import PkEndpointType, calculate_pk_endpoints
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.validation.compatibility import (
    PredictedPkSeriesDescriptor,
    ValidationCompatibilityReport,
    ValidationEligibility,
)
from opentrials.validation.observed import ObservedDataset


class AlignedPkPoint(BaseModel):
    """A single exact subject-time comparison in the predicted series units."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    time: ScientificValue
    predicted: ScientificValue
    observed: ScientificValue
    residual: ScientificValue
    relative_error: float


class EndpointComparison(BaseModel):
    """A paired predicted and observed noncompartmental PK endpoint."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    predicted: ScientificValue
    observed: ScientificValue
    residual: ScientificValue
    relative_error: float


class ValidationMetric(BaseModel):
    """An aggregate descriptive validation metric, without a pass/fail decision."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    metric_id: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ValidationEngineResult(BaseModel):
    """Immutable output of an eligible PK validation comparison."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    compatibility_report: ValidationCompatibilityReport
    aligned_points: tuple[AlignedPkPoint, ...] = Field(min_length=1)
    endpoint_comparisons: tuple[EndpointComparison, ...] = Field(min_length=1)
    metrics: tuple[ValidationMetric, ...] = Field(min_length=1)


_REQUIRED_COLUMNS = (
    "subject_id",
    "time",
    "time_unit",
    "analyte",
    "matrix",
    "fraction",
    "measurement",
    "value",
    "unit",
)
_CONTEXT_COLUMNS = ("analyte", "matrix", "fraction", "measurement")


def _text(row: Mapping[str, object], column: str, row_index: int) -> str:
    value = row.get(column)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Predicted row {row_index} field {column!r} must be non-empty text.")
    return value


def _number(row: Mapping[str, object], column: str, row_index: int) -> float:
    value = row.get(column)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Predicted row {row_index} field {column!r} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Predicted row {row_index} field {column!r} must be finite.")
    return number


def _validated_predicted_rows(
    rows: Sequence[Mapping[str, object]], descriptor: PredictedPkSeriesDescriptor
) -> tuple[dict[str, object], ...]:
    if not rows:
        raise ValueError("At least one predicted canonical row is required.")

    validated: list[dict[str, object]] = []
    for row_index, row in enumerate(rows):
        missing = next((column for column in _REQUIRED_COLUMNS if column not in row), None)
        if missing is not None:
            raise ValueError(f"Predicted row {row_index} is missing required field {missing!r}.")
        for column in _CONTEXT_COLUMNS:
            if _text(row, column, row_index) != getattr(descriptor, column):
                message = (
                    f"Predicted row {row_index} field {column!r} does not match "
                    + "the predicted descriptor."
                )
                raise ValueError(message)
        if _text(row, "unit", row_index) != descriptor.unit:
            raise ValueError(
                f"Predicted row {row_index} unit does not match the predicted descriptor."
            )
        if _text(row, "time_unit", row_index) != descriptor.time_unit:
            raise ValueError(
                f"Predicted row {row_index} time unit does not match the predicted descriptor."
            )
        validated.append(
            {
                "subject_id": _text(row, "subject_id", row_index),
                "time": _number(row, "time", row_index),
                "time_unit": descriptor.time_unit,
                "analyte": descriptor.analyte,
                "matrix": descriptor.matrix,
                "fraction": descriptor.fraction,
                "measurement": descriptor.measurement,
                "value": _number(row, "value", row_index),
                "unit": descriptor.unit,
            }
        )
    return tuple(validated)


def evaluate_pk_validation(
    compatibility: ValidationCompatibilityReport,
    observed: ObservedDataset,
    predicted: PredictedPkSeriesDescriptor,
    predicted_rows: Sequence[Mapping[str, object]],
    predicted_result_hash: str,
    observed_dataset_hash: str,
) -> ValidationEngineResult:
    """Compare an eligible observed PK dataset with canonical predicted rows.

    Version 0.2-C requires exact identity of the subject/time pairs after observed
    values and sampling times are converted to the units declared by ``predicted``.
    """
    if compatibility.eligibility is ValidationEligibility.INELIGIBLE:
        raise ValueError("Cannot evaluate validation for an INELIGIBLE compatibility report.")
    if compatibility.dataset_id != observed.dataset_id:
        raise ValueError("Compatibility report dataset ID does not match the observed dataset.")

    canonical_predicted = _validated_predicted_rows(predicted_rows, predicted)
    predicted_by_key: dict[tuple[str, float], dict[str, object]] = {}
    for row in canonical_predicted:
        key = (str(row["subject_id"]), cast(float, row["time"]))
        if key in predicted_by_key:
            raise ValueError(f"Predicted rows contain duplicate subject/time pair {key!r}.")
        predicted_by_key[key] = row

    observed_by_key: dict[tuple[str, float], dict[str, object]] = {}
    for observation in observed.observations:
        time = observation.time.to(predicted.time_unit).value
        value = observation.value.to(predicted.unit).value
        key = (observation.subject_or_population_id, time)
        if key in observed_by_key:
            raise ValueError(f"Observed data contain duplicate subject/time pair {key!r}.")
        observed_by_key[key] = {
            "subject_id": observation.subject_or_population_id,
            "time": time,
            "time_unit": predicted.time_unit,
            "analyte": predicted.analyte,
            "matrix": predicted.matrix,
            "fraction": predicted.fraction,
            "measurement": predicted.measurement,
            "value": value,
            "unit": predicted.unit,
        }

    if predicted_by_key.keys() != observed_by_key.keys():
        message = (
            "Predicted and observed data must have exactly matching subject identities "
            + "and sample times."
        )
        raise ValueError(message)

    aligned_points: list[AlignedPkPoint] = []
    for row in canonical_predicted:
        subject_id, time = str(row["subject_id"]), cast(float, row["time"])
        observed_row = observed_by_key[(subject_id, time)]
        observed_value = cast(float, observed_row["value"])
        if observed_value == 0.0:
            raise ValueError("Relative error is undefined for an observed value of zero.")
        predicted_value = cast(float, row["value"])
        residual = predicted_value - observed_value
        aligned_points.append(
            AlignedPkPoint(
                subject_id=subject_id,
                time=ScientificValue(
                    value=time, unit=predicted.time_unit, value_type=ValueType.DERIVED
                ),
                predicted=ScientificValue(
                    value=predicted_value, unit=predicted.unit, value_type=ValueType.PREDICTED
                ),
                observed=ScientificValue(
                    value=observed_value, unit=predicted.unit, value_type=ValueType.OBSERVED
                ),
                residual=ScientificValue(
                    value=residual, unit=predicted.unit, value_type=ValueType.DERIVED
                ),
                relative_error=residual / observed_value,
            )
        )

    predicted_endpoints = calculate_pk_endpoints(canonical_predicted, predicted_result_hash)
    observed_rows = tuple(observed_by_key[key] for key in predicted_by_key)
    observed_endpoints = calculate_pk_endpoints(observed_rows, observed_dataset_hash)
    observed_endpoints_by_key = {
        (endpoint.subject_id, endpoint.endpoint_type): endpoint for endpoint in observed_endpoints
    }

    endpoint_comparisons: list[EndpointComparison] = []
    for endpoint in predicted_endpoints:
        observed_endpoint = observed_endpoints_by_key[(endpoint.subject_id, endpoint.endpoint_type)]
        if observed_endpoint.value == 0.0:
            raise ValueError("Relative error is undefined for an observed endpoint of zero.")
        residual = endpoint.value - observed_endpoint.value
        endpoint_comparisons.append(
            EndpointComparison(
                subject_id=endpoint.subject_id,
                endpoint_type=endpoint.endpoint_type,
                predicted=ScientificValue(
                    value=endpoint.value, unit=endpoint.unit, value_type=ValueType.PREDICTED
                ),
                observed=ScientificValue(
                    value=observed_endpoint.value,
                    unit=observed_endpoint.unit,
                    value_type=ValueType.OBSERVED,
                ),
                residual=ScientificValue(
                    value=residual, unit=endpoint.unit, value_type=ValueType.DERIVED
                ),
                relative_error=residual / observed_endpoint.value,
            )
        )

    relative_errors = tuple(point.relative_error for point in aligned_points)
    return ValidationEngineResult(
        compatibility_report=compatibility,
        aligned_points=tuple(aligned_points),
        endpoint_comparisons=tuple(endpoint_comparisons),
        metrics=(
            ValidationMetric(
                metric_id="mean_signed_error",
                value=sum(point.residual.value for point in aligned_points) / len(aligned_points),
                unit=predicted.unit,
                description="Mean predicted minus observed concentration.",
            ),
            ValidationMetric(
                metric_id="mean_absolute_percentage_error",
                value=sum(abs(error) for error in relative_errors) / len(relative_errors),
                unit="1",
                description="Mean absolute relative error as a dimensionless fraction.",
            ),
        ),
    )
