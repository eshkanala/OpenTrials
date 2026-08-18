"""Declared trial observation/sampling schedules, separate from dosing timing.

An ``ObservationSchedule`` is the trial's *measurement* timeline -- when
blood samples are taken -- kept explicitly distinct from the intervention's
*administration* timing (``Dose.administration_time``/``infusion_duration``).
Verified empirically against the installed ``ospsuite``: ``addOutputInterval``
lets the solver's output grid be set to one or more evenly-spaced windows
(read back and confirmed exact -- see HANDOFF v0.5-B); it does not support
arbitrary irregular time lists in one call, so a realistic protocol (dense
early sampling, sparse later) is expressed as a union of such windows.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.scientific_value import ScientificValue


class SamplingWindow(BaseModel):
    """One evenly-spaced block of declared sample times: start, end, interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: ScientificValue
    end: ScientificValue
    interval: ScientificValue

    @model_validator(mode="after")
    def validate_dimensions_and_ordering(self) -> SamplingWindow:
        fields = (("start", self.start), ("end", self.end), ("interval", self.interval))
        for field_name, value in fields:
            if not value.quantity().check("[time]"):
                raise ValueError(f"SamplingWindow.{field_name} must be time-dimensional.")
        if self.interval.value <= 0:
            raise ValueError("SamplingWindow.interval must be positive.")
        if self.start.value < 0:
            raise ValueError("SamplingWindow.start must be nonnegative.")
        if self.end.value <= self.start.value:
            raise ValueError("SamplingWindow.end must be after start (in comparable units).")
        return self

    def declared_times(self, time_unit: str) -> tuple[float, ...]:
        """Deterministically enumerate every sample time in this window."""
        start = self.start.to(time_unit).value
        end = self.end.to(time_unit).value
        interval = self.interval.to(time_unit).value
        span = end - start
        step_count = span / interval
        rounded = round(step_count)
        if abs(step_count - rounded) > 1e-9:
            raise ValueError(
                "SamplingWindow span must be an exact multiple of its interval "
                f"(got span={span}, interval={interval})."
            )
        return tuple(start + index * interval for index in range(rounded + 1))


class ObservationSchedule(BaseModel):
    """An immutable, deterministic set of declared sample times for a trial."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_id: str = Field(min_length=1)
    time_unit: str = Field(min_length=1)
    windows: tuple[SamplingWindow, ...] = Field(min_length=1)

    def declared_times(self) -> tuple[float, ...]:
        """All declared sample times across every window, sorted and deduplicated."""
        times: set[float] = set()
        for window in self.windows:
            times.update(window.declared_times(self.time_unit))
        return tuple(sorted(times))
