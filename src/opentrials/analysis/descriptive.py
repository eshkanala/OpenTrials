"""Solver-independent descriptive statistics for a set of numeric samples."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class DescriptiveSummary(BaseModel):
    """Non-inferential descriptive statistics for one finite numeric sample."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(gt=0)
    mean: float
    sample_standard_deviation: float | None
    coefficient_of_variation: float | None
    minimum: float
    maximum: float
    p25: float
    p50: float
    p75: float


def calculate_descriptive_summary(values: Sequence[float]) -> DescriptiveSummary:
    """Summarize one finite numeric sample without any inferential claim.

    Only descriptive quantities are produced: no p-values, confidence intervals,
    or significance language. ``sample_standard_deviation`` and
    ``coefficient_of_variation`` are ``None`` for ``n == 1``, where sample
    variance is undefined rather than zero. Percentiles use linear interpolation
    between order statistics (the common "inclusive" convention).
    """
    if not values:
        raise ValueError("Descriptive summary requires at least one value.")
    numbers: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Descriptive summary values must be numeric.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Descriptive summary values must be finite.")
        numbers.append(number)

    n = len(numbers)
    mean = math.fsum(numbers) / n
    sample_standard_deviation: float | None = None
    coefficient_of_variation: float | None = None
    if n >= 2:
        variance = math.fsum((value - mean) ** 2 for value in numbers) / (n - 1)
        sample_standard_deviation = math.sqrt(variance)
        coefficient_of_variation = (
            sample_standard_deviation / mean if mean != 0.0 else None
        )

    ordered = sorted(numbers)
    return DescriptiveSummary(
        n=n,
        mean=mean,
        sample_standard_deviation=sample_standard_deviation,
        coefficient_of_variation=coefficient_of_variation,
        minimum=ordered[0],
        maximum=ordered[-1],
        p25=percentile(ordered, 0.25),
        p50=percentile(ordered, 0.50),
        p75=percentile(ordered, 0.75),
    )


def percentile(ordered: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile over an already-sorted sample.

    ``fraction`` is in ``[0, 1]``. Public so other rank/percentile-based
    selection logic (for example extreme-responder thresholds) shares the
    exact same interpolation convention as this module's own summaries.
    """
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight
