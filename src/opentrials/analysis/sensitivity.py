"""Solver-independent first-order Pearson sensitivity calculations."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SensitivityInput(BaseModel):
    """Named numeric values assigned to one uncertain input for each draw."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    input_id: str = Field(min_length=1)
    values: tuple[float, ...] = Field(min_length=2)

    @field_validator("input_id")
    @classmethod
    def validate_input_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Sensitivity input IDs cannot be blank.")
        return value

    @field_validator("values", mode="before")
    @classmethod
    def validate_values(cls, values: object) -> tuple[float, ...]:
        return _validated_values(values, "Sensitivity input values")


class SensitivityOutput(BaseModel):
    """Named numeric output values produced for each corresponding draw."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    output_id: str = Field(min_length=1)
    values: tuple[float, ...] = Field(min_length=2)

    @field_validator("output_id")
    @classmethod
    def validate_output_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Sensitivity output IDs cannot be blank.")
        return value

    @field_validator("values", mode="before")
    @classmethod
    def validate_values(cls, values: object) -> tuple[float, ...]:
        return _validated_values(values, "Sensitivity output values")


class PearsonSensitivity(BaseModel):
    """First-order Pearson sensitivity of one named input to one named output."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    input_id: str = Field(min_length=1)
    output_id: str = Field(min_length=1)
    correlation: float = Field(ge=-1.0, le=1.0)


def _validated_values(values: object, label: str) -> tuple[float, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{label} must be a sequence of numeric values.")

    numbers: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must contain only numeric values.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{label} must contain only finite values.")
        numbers.append(number)
    return tuple(numbers)


def calculate_pearson_sensitivities(
    inputs: Sequence[SensitivityInput], outputs: Sequence[SensitivityOutput]
) -> tuple[PearsonSensitivity, ...]:
    """Calculate one Pearson correlation for every input/output pair.

    Input and output values are aligned by draw row: item ``n`` in each sequence
    represents the same materialized draw. This calculator neither invokes nor
    assumes a simulation solver.
    """
    if not inputs:
        raise ValueError("At least one sensitivity input is required.")
    if not outputs:
        raise ValueError("At least one sensitivity output is required.")

    _require_unique_ids((item.input_id for item in inputs), "input")
    _require_unique_ids((item.output_id for item in outputs), "output")

    row_count = len(inputs[0].values)
    if row_count < 2:
        raise ValueError("Sensitivity calculations require at least two draw rows.")
    for item in inputs:
        if len(item.values) != row_count:
            raise ValueError("Sensitivity input and output values must have equal row counts.")
    for output in outputs:
        if len(output.values) != row_count:
            raise ValueError("Sensitivity input and output values must have equal row counts.")

    centered_inputs = {
        item.input_id: _centered_values(item.values, f"input {item.input_id!r}") for item in inputs
    }
    centered_outputs = {
        item.output_id: _centered_values(item.values, f"output {item.output_id!r}")
        for item in outputs
    }

    results = [
        PearsonSensitivity(
            input_id=input_id,
            output_id=output_id,
            correlation=_pearson_correlation(input_values, output_values),
        )
        for input_id, input_values in centered_inputs.items()
        for output_id, output_values in centered_outputs.items()
    ]
    return tuple(sorted(results, key=lambda result: (result.input_id, result.output_id)))


def _require_unique_ids(ids: Iterable[str], kind: str) -> None:
    identifiers: tuple[str, ...] = tuple(ids)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"Sensitivity {kind} IDs must be unique.")


def _centered_values(values: tuple[float, ...], label: str) -> tuple[tuple[float, ...], float]:
    mean = math.fsum(values) / len(values)
    centered = tuple(value - mean for value in values)
    sum_of_squares = math.fsum(value * value for value in centered)
    if sum_of_squares == 0.0:
        raise ValueError(f"Sensitivity {label} must have nonzero variance.")
    return centered, sum_of_squares


def _pearson_correlation(
    left: tuple[tuple[float, ...], float], right: tuple[tuple[float, ...], float]
) -> float:
    left_values, left_sum_of_squares = left
    right_values, right_sum_of_squares = right
    correlation = math.fsum(
        left_value * right_value for left_value, right_value in zip(left_values, right_values)
    ) / math.sqrt(left_sum_of_squares * right_sum_of_squares)
    return max(-1.0, min(1.0, correlation))
