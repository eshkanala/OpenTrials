"""Minimal, dependency-free SVG chart rendering for reports.

No plotting library is added as a dependency -- these are small, explicit
SVG templates so the resulting HTML report stays genuinely self-contained
(no external script/image references) without adding a new, heavy
dependency to a project that has stayed deliberately conservative about
its dependency list. Every chart plots values already present in
``ReportData`` -- nothing here recomputes a scientific result.
"""

from __future__ import annotations

from opentrials.reporting.data import ConcentrationTimeSeries

_PALETTE = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2")


def _scale(value: float, minimum: float, maximum: float, lo: float, hi: float) -> float:
    if maximum <= minimum:
        return (lo + hi) / 2
    return lo + (value - minimum) / (maximum - minimum) * (hi - lo)


def concentration_time_chart_svg(
    series: tuple[ConcentrationTimeSeries, ...],
    *,
    width: int = 640,
    height: int = 360,
) -> str:
    """One concentration-time line chart, one line per series (e.g. per arm)."""
    if not series:
        return ""
    margin_left, margin_right, margin_top, margin_bottom = 60, 20, 30, 50
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    all_times = [point[0] for one in series for point in one.points]
    all_values = [point[1] for one in series for point in one.points]
    t_min, t_max = min(all_times), max(all_times)
    v_min, v_max = 0.0, max(all_values)
    time_unit = series[0].time_unit
    unit = series[0].unit

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Concentration-time chart ({unit} vs {time_unit})">',
        f'<rect x="0" y="0" width="{width}" height="{height}" style="fill:var(--svg-bg)"/>',
    ]

    # Axes.
    x0, y0 = margin_left, margin_top + plot_h
    x1, y1 = margin_left + plot_w, margin_top
    parts.append(
        f'<line x1="{x0}" y1="{y0}" x2="{x0+plot_w}" y2="{y0}" style="stroke:var(--svg-axis)"/>'
    )
    parts.append(
        f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" style="stroke:var(--svg-axis)"/>'
    )

    # Y gridlines/labels (5 ticks).
    for i in range(5):
        fraction = i / 4
        value = v_min + fraction * (v_max - v_min)
        y = _scale(value, v_min, v_max, y0, y1)
        parts.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+plot_w}" y2="{y:.1f}" '
            f'style="stroke:var(--svg-grid)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
            f'style="fill:var(--svg-label)">{value:g}</text>'
        )
    parts.append(
        f'<text x="{margin_left-45}" y="{margin_top-10}" font-size="11" '
        f'style="fill:var(--svg-label)">{unit}</text>'
    )
    parts.append(
        f'<text x="{x0+plot_w/2:.1f}" y="{height-10}" text-anchor="middle" font-size="11" '
        f'style="fill:var(--svg-label)">Time ({time_unit})</text>'
    )

    # X tick labels (min/max).
    for time_value in (t_min, t_max):
        x = _scale(time_value, t_min, t_max, x0, x0 + plot_w)
        parts.append(
            f'<text x="{x:.1f}" y="{y0+20}" text-anchor="middle" font-size="11" '
            f'style="fill:var(--svg-label)">{time_value:g}</text>'
        )

    # Series lines + legend.
    for index, one in enumerate(series):
        color = _PALETTE[index % len(_PALETTE)]
        ordered = sorted(one.points)
        path_points = " ".join(
            f"{_scale(t, t_min, t_max, x0, x0 + plot_w):.1f},"
            f"{_scale(v, v_min, v_max, y0, y1):.1f}"
            for t, v in ordered
        )
        parts.append(
            f'<polyline points="{path_points}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        # Markers only for a reasonably sparse series (e.g. a declared
        # observation schedule) -- a dense default solver grid would draw
        # hundreds of overlapping circles, cluttering the chart without
        # adding information the line itself doesn't already show.
        if len(ordered) <= 40:
            for t, v in ordered:
                cx = _scale(t, t_min, t_max, x0, x0 + plot_w)
                cy = _scale(v, v_min, v_max, y0, y1)
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="{color}"/>')
        legend_y = margin_top + index * 16
        parts.append(f'<rect x="{x1-14}" y="{legend_y}" width="10" height="10" fill="{color}"/>')
        parts.append(
            f'<text x="{x1-18}" y="{legend_y+9}" text-anchor="end" font-size="11" '
            f'style="fill:var(--text)">{one.label}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def bar_chart_svg(
    *,
    categories: tuple[str, ...],
    values: tuple[float, ...],
    unit: str,
    title: str,
    width: int = 640,
    height: int = 280,
) -> str:
    """A simple grouped bar chart, one bar per category (e.g. per arm)."""
    if not categories or len(categories) != len(values):
        return ""
    margin_left, margin_right, margin_top, margin_bottom = 60, 20, 36, 40
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    v_max = max(values) if max(values) > 0 else 1.0

    x0, y0 = margin_left, margin_top + plot_h
    bar_width = plot_w / len(categories) * 0.6
    slot = plot_w / len(categories)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" style="fill:var(--svg-bg)"/>',
        f'<text x="{margin_left}" y="18" font-size="12" style="fill:var(--text)" '
        f'font-weight="600">{title}</text>',
        f'<line x1="{x0}" y1="{y0}" x2="{x0+plot_w}" y2="{y0}" style="stroke:var(--svg-axis)"/>',
    ]
    for index, (category, value) in enumerate(zip(categories, values, strict=True)):
        bar_h = plot_h * (value / v_max)
        x = x0 + index * slot + (slot - bar_width) / 2
        y = y0 - bar_h
        color = _PALETTE[index % len(_PALETTE)]
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" '
            f'fill="{color}"/>'
        )
        parts.append(
            f'<text x="{x+bar_width/2:.1f}" y="{y-6:.1f}" text-anchor="middle" font-size="11" '
            f'style="fill:var(--text)">{value:g}</text>'
        )
        parts.append(
            f'<text x="{x+bar_width/2:.1f}" y="{y0+16}" text-anchor="middle" font-size="11" '
            f'style="fill:var(--svg-label)">{category}</text>'
        )
    parts.append(
        f'<text x="{margin_left-45}" y="{margin_top-10}" font-size="11" '
        f'style="fill:var(--svg-label)">{unit}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
