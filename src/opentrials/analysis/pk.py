"""Strict noncompartmental PK endpoints from canonical concentration-time rows."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.models.package import SHA256_PATTERN


class PkEndpointType(StrEnum):
    """Supported pharmacokinetic endpoint types."""

    CMAX = "CMAX"
    TMAX = "TMAX"
    AUC_0_LAST = "AUC_0_LAST"


class PkEndpointResult(BaseModel):
    """One PK endpoint derived only from observed canonical result rows."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    endpoint_type: PkEndpointType
    value: float
    unit: str = Field(min_length=1)
    time_basis: str = Field(min_length=1)
    integration_method: str = Field(min_length=1)
    source_result_hash: str = Field(pattern=SHA256_PATTERN)
    analyte: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    measurement: str = Field(min_length=1)


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
_PROVENANCE_COLUMNS = ("analyte", "matrix", "fraction", "measurement", "unit", "time_unit")
_TIME_BASIS = "actual_sample_times"
_NOT_APPLICABLE = "not_applicable"
_LINEAR_TRAPEZOIDAL = "linear_trapezoidal"


def _required_text(row: Mapping[str, object], column: str, row_index: int) -> str:
    try:
        value = row[column]
    except KeyError as error:
        raise ValueError(
            f"Canonical row {row_index} is missing required field {column!r}."
        ) from error
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Canonical row {row_index} field {column!r} must be non-empty text.")
    return value


def _finite_number(row: Mapping[str, object], column: str, row_index: int) -> float:
    try:
        value = row[column]
    except KeyError as error:
        raise ValueError(
            f"Canonical row {row_index} is missing required field {column!r}."
        ) from error
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Canonical row {row_index} field {column!r} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Canonical row {row_index} field {column!r} must be finite.")
    return number


def calculate_pk_endpoints(
    rows: Sequence[Mapping[str, object]], source_result_hash: str
) -> tuple[PkEndpointResult, ...]:
    """Calculate Cmax, Tmax, and AUC(0-last) for each subject in canonical rows.

    Rows must form one homogeneous concentration-time series definition. Times are
    checked in their supplied order for each subject; they are never sorted, so an
    unordered input cannot silently change the endpoint calculation. AUC covers
    only the first through last observed time and uses the linear trapezoidal rule.
    """
    if not rows:
        raise ValueError("At least one canonical concentration-time row is required.")

    validated_hash = PkEndpointResult.model_validate(
        {
            "subject_id": "validation",
            "endpoint_type": PkEndpointType.CMAX,
            "value": 0.0,
            "unit": "validation",
            "time_basis": _TIME_BASIS,
            "integration_method": _NOT_APPLICABLE,
            "source_result_hash": source_result_hash,
            "analyte": "validation",
            "matrix": "validation",
            "fraction": "validation",
            "measurement": "validation",
        }
    ).source_result_hash

    series: dict[str, list[tuple[float, float]]] = {}
    provenance: dict[str, str] | None = None
    for row_index, row in enumerate(rows):
        for column in _REQUIRED_COLUMNS:
            if column not in row:
                raise ValueError(f"Canonical row {row_index} is missing required field {column!r}.")

        subject_id = _required_text(row, "subject_id", row_index)
        time = _finite_number(row, "time", row_index)
        value = _finite_number(row, "value", row_index)
        row_provenance = {
            column: _required_text(row, column, row_index) for column in _PROVENANCE_COLUMNS
        }
        if provenance is None:
            provenance = row_provenance
        elif row_provenance != provenance:
            changed = next(
                column
                for column in _PROVENANCE_COLUMNS
                if row_provenance[column] != provenance[column]
            )
            raise ValueError(
                f"Canonical row {row_index} field {changed!r} does not match the combined series."
            )

        subject_series = series.setdefault(subject_id, [])
        if subject_series:
            previous_time = subject_series[-1][0]
            if time == previous_time:
                raise ValueError(
                    f"Canonical row {row_index} has duplicate time {time} for subject "
                    + f"{subject_id!r}."
                )
            if time < previous_time:
                raise ValueError(
                    f"Canonical row {row_index} has unordered time for subject {subject_id!r}."
                )
        subject_series.append((time, value))

    assert provenance is not None
    results: list[PkEndpointResult] = []
    for subject_id, samples in series.items():
        cmax = max(value for _, value in samples)
        tmax = next(time for time, value in samples if value == cmax)
        auc = sum(
            (next_time - time) * (value + next_value) / 2
            for (time, value), (next_time, next_value) in zip(samples, samples[1:])
        )
        common = {
            "subject_id": subject_id,
            "time_basis": _TIME_BASIS,
            "source_result_hash": validated_hash,
            "analyte": provenance["analyte"],
            "matrix": provenance["matrix"],
            "fraction": provenance["fraction"],
            "measurement": provenance["measurement"],
        }
        results.extend(
            (
                PkEndpointResult(
                    **common,
                    endpoint_type=PkEndpointType.CMAX,
                    value=cmax,
                    unit=provenance["unit"],
                    integration_method=_NOT_APPLICABLE,
                ),
                PkEndpointResult(
                    **common,
                    endpoint_type=PkEndpointType.TMAX,
                    value=tmax,
                    unit=provenance["time_unit"],
                    integration_method=_NOT_APPLICABLE,
                ),
                PkEndpointResult(
                    **common,
                    endpoint_type=PkEndpointType.AUC_0_LAST,
                    value=auc,
                    unit=f"{provenance['unit']} * {provenance['time_unit']}",
                    integration_method=_LINEAR_TRAPEZOIDAL,
                ),
            )
        )
    return tuple(results)
