import pytest

from opentrials.analysis.pk import PkEndpointType, calculate_pk_endpoints

SOURCE_RESULT_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def row(time: float, value: float, **overrides: object) -> dict[str, object]:
    return {
        "subject_id": "subject-1",
        "time": time,
        "time_unit": "h",
        "analyte": "compound-a",
        "matrix": "plasma",
        "fraction": "total",
        "measurement": "concentration",
        "value": value,
        "unit": "mg/L",
        **overrides,
    }


def endpoints_by_type(rows: tuple[dict[str, object], ...]) -> dict[PkEndpointType, object]:
    return {
        result.endpoint_type: result for result in calculate_pk_endpoints(rows, SOURCE_RESULT_HASH)
    }


def test_calculates_known_curve_cmax_tmax_and_auc_0_last() -> None:
    endpoints = endpoints_by_type((row(0, 0), row(1, 2), row(2, 0)))

    assert endpoints[PkEndpointType.CMAX].value == 2.0
    assert endpoints[PkEndpointType.CMAX].unit == "mg/L"
    assert endpoints[PkEndpointType.TMAX].value == 1.0
    assert endpoints[PkEndpointType.TMAX].unit == "h"
    assert endpoints[PkEndpointType.AUC_0_LAST].value == 2.0
    assert endpoints[PkEndpointType.AUC_0_LAST].unit == "mg/L * h"
    assert endpoints[PkEndpointType.AUC_0_LAST].integration_method == "linear_trapezoidal"


def test_tmax_is_earliest_sample_time_with_tied_cmax() -> None:
    endpoints = endpoints_by_type((row(0, 1), row(1, 4), row(2, 4), row(3, 2)))

    assert endpoints[PkEndpointType.CMAX].value == 4.0
    assert endpoints[PkEndpointType.TMAX].value == 1.0


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((row(0, 1), row(1, 2, fraction="unbound")), "fraction.*does not match"),
        ((row(0, 1), row(1, 2, unit="ng/mL")), "unit.*does not match"),
    ],
)
def test_rejects_mixed_combined_series_provenance(
    rows: tuple[dict[str, object], ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_pk_endpoints(rows, SOURCE_RESULT_HASH)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((row(1, 1), row(0, 2)), "unordered time"),
        ((row(0, 1), row(0, 2)), "duplicate time"),
    ],
)
def test_rejects_unordered_or_duplicate_times(
    rows: tuple[dict[str, object], ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_pk_endpoints(rows, SOURCE_RESULT_HASH)
