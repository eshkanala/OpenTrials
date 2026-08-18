import pytest
from pydantic import ValidationError

from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.trials import ObservationSchedule, SamplingWindow


def t(value: float, unit: str = "min") -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def test_single_window_enumerates_evenly_spaced_times() -> None:
    window = SamplingWindow(start=t(0), end=t(60), interval=t(15))

    assert window.declared_times("min") == (0.0, 15.0, 30.0, 45.0, 60.0)


def test_schedule_unions_and_deduplicates_multiple_windows() -> None:
    dense = SamplingWindow(start=t(0), end=t(60), interval=t(15))
    sparse = SamplingWindow(start=t(60), end=t(240), interval=t(60))
    schedule = ObservationSchedule(schedule_id="mixed", time_unit="min", windows=(dense, sparse))

    assert schedule.declared_times() == (0.0, 15.0, 30.0, 45.0, 60.0, 120.0, 180.0, 240.0)


def test_window_converts_units_consistently() -> None:
    window = SamplingWindow(start=t(0, "h"), end=t(4, "h"), interval=t(30, "min"))

    assert window.declared_times("min") == (
        0.0,
        30.0,
        60.0,
        90.0,
        120.0,
        150.0,
        180.0,
        210.0,
        240.0,
    )


def test_window_rejects_non_time_dimensional_values() -> None:
    with pytest.raises(ValidationError, match="time-dimensional"):
        SamplingWindow(
            start=ScientificValue(value=0, unit="mg", value_type=ValueType.ASSUMED),
            end=t(60),
            interval=t(15),
        )


def test_window_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError, match="end must be after start"):
        SamplingWindow(start=t(60), end=t(0), interval=t(15))


def test_window_rejects_non_positive_interval() -> None:
    with pytest.raises(ValidationError, match="interval must be positive"):
        SamplingWindow(start=t(0), end=t(60), interval=t(0))


def test_window_rejects_span_not_a_multiple_of_interval() -> None:
    window = SamplingWindow(start=t(0), end=t(50), interval=t(15))

    with pytest.raises(ValueError, match="exact multiple"):
        window.declared_times("min")


def test_schedule_requires_at_least_one_window() -> None:
    with pytest.raises(ValidationError):
        ObservationSchedule(schedule_id="empty", time_unit="min", windows=())
