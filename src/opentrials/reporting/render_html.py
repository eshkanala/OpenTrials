"""Render a ``ReportData`` as one self-contained HTML file.

Self-contained means exactly that: inline CSS, inline SVG figures, no
external script/stylesheet/font/image references -- the file can be
emailed, archived, or opened offline with nothing else needed.
"""

from __future__ import annotations

import html

from opentrials.reporting.data import ReportData
from opentrials.reporting.plots import bar_chart_svg, concentration_time_chart_svg

_STYLE = """
:root {
  --page-bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0; --text: #0f172a;
  --text-muted: #475569; --text-faint: #64748b; --code-bg: #f1f5f9;
  --pill-ok-bg: #dcfce7; --pill-ok-text: #166534;
  --pill-fail-bg: #fee2e2; --pill-fail-text: #991b1b;
  --svg-bg: #ffffff; --svg-axis: #94a3b8; --svg-grid: #e2e8f0; --svg-label: #475569;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --page-bg: #0b1220; --surface: #111827; --border: #263244; --text: #e5e9f0;
    --text-muted: #9aa7bb; --text-faint: #7d8aa0; --code-bg: #1a2332;
    --pill-ok-bg: #113322; --pill-ok-text: #86efac;
    --pill-fail-bg: #3a1414; --pill-fail-text: #fca5a5;
    --svg-bg: #111827; --svg-axis: #46536a; --svg-grid: #1f2937; --svg-label: #9aa7bb;
  }
}
:root[data-theme="dark"] {
  --page-bg: #0b1220; --surface: #111827; --border: #263244; --text: #e5e9f0;
  --text-muted: #9aa7bb; --text-faint: #7d8aa0; --code-bg: #1a2332;
  --pill-ok-bg: #113322; --pill-ok-text: #86efac;
  --pill-fail-bg: #3a1414; --pill-fail-text: #fca5a5;
  --svg-bg: #111827; --svg-axis: #46536a; --svg-grid: #1f2937; --svg-label: #9aa7bb;
}
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color: var(--text);
       background: var(--page-bg); margin: 0; padding: 2rem; }
main { max-width: 880px; margin: 0 auto; background: var(--surface);
       border: 1px solid var(--border); border-radius: 8px; padding: 2rem 2.5rem; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; text-wrap: balance; }
h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid var(--border);
     padding-bottom: 0.4rem; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-weight: 600; }
code { background: var(--code-bg); padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.85em; }
.meta-list { list-style: none; padding: 0; margin: 0.5rem 0; }
.meta-list li { padding: 0.15rem 0; }
.meta-list b { color: var(--text-muted); font-weight: 600; }
.figure { margin: 1rem 0; overflow-x: auto; }
.figure-caption { font-size: 0.8rem; color: var(--text-faint); margin-top: 0.25rem; }
.pill { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.8rem; }
.pill-ok { background: var(--pill-ok-bg); color: var(--pill-ok-text); }
.pill-fail { background: var(--pill-fail-bg); color: var(--pill-fail-text); }
.disclaimer { font-size: 0.85rem; color: var(--text-muted); background: var(--page-bg);
              border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem 1rem;
              margin-top: 0.5rem; }
"""


def render_html(data: ReportData) -> str:
    body = [
        "<main>",
        f"<h1>{_esc(data.header.title)}</h1>",
        f'<p style="color:#64748b">Run <code>{_esc(data.header.run_id)}</code> &middot; '
        f"generated {_esc(data.header.generated_at.isoformat())}</p>",
        *_overview(data),
        *_model(data),
        *_population(data),
        *_arms(data),
        *_observation_schedule(data),
        *_concentration_time_figures(data),
        *_endpoints(data),
        *_comparison_figures(data),
        *_comparisons(data),
        *_execution_verification(data),
        *_limitations(data),
        *_provenance(data),
        *_reproducibility(data),
        "</main>",
    ]
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{_esc(data.header.title)}</title><style>{_STYLE}</style></head>"
        f"<body>{''.join(body)}</body></html>\n"
    )


def _esc(value: object) -> str:
    return html.escape(str(value))


def _format_optional(value: float | None) -> str:
    return f"{value:g}" if value is not None else "—"


def _overview(data: ReportData) -> list[str]:
    items = [f"<li><b>Run type:</b> {_esc(data.header.report_type)}</li>"]
    if data.header.trial_id:
        items.append(f"<li><b>Trial ID:</b> {_esc(data.header.trial_id)}</li>")
    return ["<h2>Overview</h2>", f"<ul class='meta-list'>{''.join(items)}</ul>"]


def _model(data: ReportData) -> list[str]:
    model = data.model
    items = "".join(
        [
            f"<li><b>Model ID:</b> <code>{_esc(model.model_id)}</code></li>",
            f"<li><b>Engine:</b> {_esc(model.engine)}</li>",
            f"<li><b>Version:</b> {_esc(model.version)}</li>",
            f"<li><b>Artifact hash:</b> <code>{_esc(model.artifact_hash)}</code></li>",
        ]
    )
    return ["<h2>Model</h2>", f"<ul class='meta-list'>{items}</ul>"]


def _population(data: ReportData) -> list[str]:
    population = data.population
    items = "".join(
        [
            f"<li><b>Participants:</b> {population.participant_count}</li>",
            f"<li><b>Reference population:</b> {_esc(population.reference_population)}</li>",
            f"<li><b>Generation ID:</b> <code>{_esc(population.generation_id)}</code></li>",
            f"<li><b>Requested seed:</b> {population.requested_seed}</li>",
            f"<li><b>Determinism level:</b> {_esc(population.determinism_level)}</li>",
        ]
    )
    return ["<h2>Population</h2>", f"<ul class='meta-list'>{items}</ul>"]


def _arms(data: ReportData) -> list[str]:
    rows = "".join(
        f"<tr><td>{_esc(arm.arm_id)}</td><td>{arm.dose_amount:g} {_esc(arm.dose_unit)}</td>"
        f"<td>{_esc(arm.route)}</td><td>{arm.participant_count}</td></tr>"
        for arm in data.arms
    )
    return [
        "<h2>Interventions / Arms</h2>",
        "<table><thead><tr><th>Arm</th><th>Dose</th><th>Route</th>"
        f"<th>Participants</th></tr></thead><tbody>{rows}</tbody></table>",
    ]


def _observation_schedule(data: ReportData) -> list[str]:
    if data.observation_schedule is None:
        return []
    schedule = data.observation_schedule
    times = ", ".join(f"{t:g}" for t in schedule.declared_times_min)
    return [
        "<h2>Observation Schedule</h2>",
        f"<ul class='meta-list'><li><b>Schedule ID:</b> <code>{_esc(schedule.schedule_id)}"
        f"</code></li><li><b>Declared sample times (min):</b> {_esc(times)}</li></ul>",
    ]


def _concentration_time_figures(data: ReportData) -> list[str]:
    if not data.concentration_time_series:
        return []
    svg = concentration_time_chart_svg(data.concentration_time_series)
    return [
        "<h2>Concentration-Time Curves</h2>",
        f"<div class='figure'>{svg}"
        "<div class='figure-caption'>Mean concentration by declared sample time, "
        "one line per arm/population, from the verified normalized result artifact.</div></div>",
    ]


def _endpoints(data: ReportData) -> list[str]:
    rows = []
    for row in data.endpoints:
        sd = _format_optional(row.sample_standard_deviation)
        cv = _format_optional(row.coefficient_of_variation)
        rows.append(
            f"<tr><td>{_esc(row.arm_id or '—')}</td><td>{_esc(row.endpoint_type)} "
            f"({_esc(row.unit)})</td><td>{row.n}</td><td>{row.mean:g}</td><td>{sd}</td>"
            f"<td>{cv}</td><td>{row.minimum:g}</td><td>{row.p50:g}</td><td>{row.maximum:g}</td></tr>"
        )
    return [
        "<h2>PK Endpoints</h2>",
        "<table><thead><tr><th>Arm</th><th>Endpoint</th><th>n</th><th>Mean</th><th>SD</th>"
        "<th>CV</th><th>Min</th><th>Median</th><th>Max</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
    ]


def _comparison_figures(data: ReportData) -> list[str]:
    if not data.endpoints or len(data.arms) < 2:
        return []
    figures = []
    endpoint_types = sorted({row.endpoint_type for row in data.endpoints})
    for endpoint_type in endpoint_types:
        rows = [row for row in data.endpoints if row.endpoint_type == endpoint_type]
        if len(rows) < 2:
            continue
        svg = bar_chart_svg(
            categories=tuple(row.arm_id or "—" for row in rows),
            values=tuple(row.mean for row in rows),
            unit=rows[0].unit,
            title=f"Mean {endpoint_type} by arm",
        )
        figures.append(f"<div class='figure'>{svg}</div>")
    if not figures:
        return []
    return ["<h2>Endpoint Comparisons</h2>", *figures]


def _comparisons(data: ReportData) -> list[str]:
    if not data.comparisons:
        return []
    rows = []
    for row in data.comparisons:
        relative = f"{row.relative_difference:.2%}" if row.relative_difference is not None else "—"
        rows.append(
            f"<tr><td>{_esc(row.arm_a_id)}</td><td>{_esc(row.arm_b_id)}</td>"
            f"<td>{_esc(row.endpoint_type)} ({_esc(row.unit)})</td><td>{row.arm_a_mean:g}</td>"
            f"<td>{row.arm_b_mean:g}</td><td>{row.absolute_difference:g}</td><td>{relative}</td></tr>"
        )
    return [
        "<h2>Arm Comparisons</h2>",
        "<table><thead><tr><th>Arm A</th><th>Arm B</th><th>Endpoint</th><th>A mean</th>"
        "<th>B mean</th><th>Abs. diff</th><th>Rel. diff</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
    ]


def _execution_verification(data: ReportData) -> list[str]:
    rows = "".join(
        f"<tr><td>{_esc(row.arm_id or '—')}</td><td>{_pill(row.model_hash_verified)}</td>"
        f"<td>{_pill(row.route_container_verified)}</td><td>{_pill(row.solver_executed)}</td></tr>"
        for row in data.execution_verification
    )
    return [
        "<h2>Execution Verification</h2>",
        "<table><thead><tr><th>Arm</th><th>Model hash verified</th>"
        "<th>Route/container verified</th><th>Solver executed</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>",
    ]


def _pill(value: bool) -> str:
    cls = "pill-ok" if value else "pill-fail"
    label = "verified" if value else "not verified"
    return f"<span class='pill {cls}'>{label}</span>"


def _limitations(data: ReportData) -> list[str]:
    items = "".join(f"<li>{_esc(item)}</li>" for item in data.limitations)
    return [
        "<h2>Scope and Limitations</h2>",
        f"<div class='disclaimer'><ul>{items}</ul></div>",
    ]


def _provenance(data: ReportData) -> list[str]:
    provenance = data.provenance
    items = [
        f"<li><b>Model hash:</b> <code>{_esc(provenance.model_sha256)}</code></li>",
        f"<li><b>Population generation ID:</b> "
        f"<code>{_esc(provenance.population_generation_id)}</code></li>",
        f"<li><b>Population content hash:</b> "
        f"<code>{_esc(provenance.population_semantic_sha256)}</code></li>",
    ]
    if provenance.trial_sha256:
        items.append(f"<li><b>Trial hash:</b> <code>{_esc(provenance.trial_sha256)}</code></li>")
    if provenance.allocation_id:
        items.append(
            f"<li><b>Allocation:</b> <code>{_esc(provenance.allocation_id)}</code> "
            f"(<code>{_esc(provenance.allocation_semantic_sha256)}</code>)</li>"
        )
    if provenance.comparison_id:
        items.append(
            f"<li><b>Comparison:</b> <code>{_esc(provenance.comparison_id)}</code> "
            f"(<code>{_esc(provenance.comparison_semantic_sha256)}</code>)</li>"
        )
    if provenance.created_at:
        items.append(f"<li><b>Executed at:</b> {_esc(provenance.created_at.isoformat())}</li>")
    if provenance.software_versions:
        versions = ", ".join(f"{k}={v}" for k, v in sorted(provenance.software_versions.items()))
        items.append(f"<li><b>Software versions:</b> {_esc(versions)}</li>")
    return ["<h2>Provenance</h2>", f"<ul class='meta-list'>{''.join(items)}</ul>"]


def _reproducibility(data: ReportData) -> list[str]:
    items = "".join(f"<li>{_esc(item)}</li>" for item in data.reproducibility)
    return ["<h2>Reproducibility</h2>", f"<ul class='meta-list'>{items}</ul>"]
