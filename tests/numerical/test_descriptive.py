import math

import pytest

from opentrials.analysis.descriptive import calculate_descriptive_summary


def test_descriptive_summary_matches_hand_computed_values() -> None:
    summary = calculate_descriptive_summary([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])

    assert summary.n == 8
    assert summary.mean == pytest.approx(5.0)
    assert summary.sample_standard_deviation == pytest.approx(2.13809, rel=1e-4)
    assert summary.coefficient_of_variation == pytest.approx(2.13809 / 5.0, rel=1e-4)
    assert summary.minimum == 2.0
    assert summary.maximum == 9.0
    # Linear-interpolated (inclusive) quartiles over 8 ordered values.
    assert summary.p25 == pytest.approx(4.0)
    assert summary.p50 == pytest.approx(4.5)
    assert summary.p75 == pytest.approx(5.5)


def test_single_value_sample_has_no_variance_statistics() -> None:
    summary = calculate_descriptive_summary([3.0])

    assert summary.n == 1
    assert summary.mean == 3.0
    assert summary.sample_standard_deviation is None
    assert summary.coefficient_of_variation is None
    assert summary.minimum == summary.maximum == 3.0
    assert summary.p25 == summary.p50 == summary.p75 == 3.0


def test_zero_mean_sample_has_no_coefficient_of_variation() -> None:
    summary = calculate_descriptive_summary([-1.0, 0.0, 1.0])

    assert summary.mean == pytest.approx(0.0)
    assert summary.sample_standard_deviation is not None
    assert summary.coefficient_of_variation is None


def test_descriptive_summary_rejects_empty_and_non_finite_input() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        calculate_descriptive_summary([])
    with pytest.raises(ValueError, match="finite"):
        calculate_descriptive_summary([1.0, math.inf])
    with pytest.raises(ValueError, match="numeric"):
        calculate_descriptive_summary([1.0, True])  # type: ignore[list-item]
