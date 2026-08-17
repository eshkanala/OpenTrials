import pytest
from pydantic import ValidationError

from opentrials.core.distributions import Distribution, DistributionType


def test_normal_distribution_serializes_deterministically() -> None:
    first = Distribution(
        distribution_type=DistributionType.NORMAL,
        unit="mL/min",
        parameters={"mean": 95.0, "standard_deviation": 12.0},
    )
    second = Distribution(
        distribution_type=DistributionType.NORMAL,
        unit="mL/min",
        parameters={"standard_deviation": 12.0, "mean": 95.0},
    )

    assert first.canonical_json() == second.canonical_json()


def test_rejects_invalid_distribution_parameters() -> None:
    with pytest.raises(ValidationError, match="requires exactly parameter keys"):
        Distribution(
            distribution_type=DistributionType.NORMAL,
            unit="mg",
            parameters={"mean": 4.0},
        )


def test_rejects_non_positive_standard_deviation() -> None:
    with pytest.raises(ValidationError, match="Standard deviation"):
        Distribution(
            distribution_type=DistributionType.LOG_NORMAL,
            unit="ng/mL",
            parameters={"log_mean": 2.0, "log_standard_deviation": 0.0},
        )


def test_empirical_distribution_requires_values() -> None:
    with pytest.raises(ValidationError, match="require at least one value"):
        Distribution(distribution_type=DistributionType.EMPIRICAL, unit="mg")
