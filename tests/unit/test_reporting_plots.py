"""Contract tests for the dependency-free SVG chart primitives."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from opentrials.reporting.data import ConcentrationTimeSeries
from opentrials.reporting.plots import bar_chart_svg, concentration_time_chart_svg


def _series(label: str, points: tuple[tuple[float, float], ...]) -> ConcentrationTimeSeries:
    return ConcentrationTimeSeries(label=label, time_unit="h", unit="umol/L", points=points)


def test_concentration_time_chart_is_well_formed_svg() -> None:
    svg = concentration_time_chart_svg(
        (_series("low", ((0.0, 1.0), (1.0, 5.0), (2.0, 3.0))),)
    )
    ET.fromstring(svg)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")


def test_concentration_time_chart_handles_multiple_series() -> None:
    svg = concentration_time_chart_svg(
        (
            _series("low", ((0.0, 1.0), (1.0, 5.0))),
            _series("high", ((0.0, 2.0), (1.0, 8.0))),
        )
    )
    ET.fromstring(svg)
    assert "low" in svg
    assert "high" in svg


def test_concentration_time_chart_empty_series_returns_empty_string() -> None:
    assert concentration_time_chart_svg(()) == ""


def test_concentration_time_chart_suppresses_markers_for_dense_series() -> None:
    dense_points = tuple((float(i), float(i) % 10) for i in range(200))
    sparse_points = tuple((float(i), float(i) % 10) for i in range(10))

    dense_svg = concentration_time_chart_svg((_series("dense", dense_points),))
    sparse_svg = concentration_time_chart_svg((_series("sparse", sparse_points),))

    assert dense_svg.count("<circle") == 0
    assert sparse_svg.count("<circle") == 10


def test_bar_chart_is_well_formed_svg() -> None:
    svg = bar_chart_svg(
        categories=("low", "high"), values=(10.0, 25.0), unit="umol/L", title="Mean CMAX by arm"
    )
    ET.fromstring(svg)
    assert "low" in svg
    assert "high" in svg


def test_bar_chart_rejects_mismatched_lengths() -> None:
    assert (
        bar_chart_svg(categories=("a", "b"), values=(1.0,), unit="x", title="t") == ""
    )


def test_bar_chart_empty_categories_returns_empty_string() -> None:
    assert bar_chart_svg(categories=(), values=(), unit="x", title="t") == ""
