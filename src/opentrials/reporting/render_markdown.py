"""Render a ``ReportData`` as portable Markdown."""

from __future__ import annotations

from opentrials.reporting.data import ReportData


def render_markdown(data: ReportData) -> str:
    lines: list[str] = [f"# {data.header.title}", ""]
    lines.extend(_overview_section(data))
    lines.extend(_model_section(data))
    lines.extend(_population_section(data))
    lines.extend(_arms_section(data))
    if data.observation_schedule is not None:
        lines.extend(_observation_schedule_section(data))
    lines.extend(_endpoints_section(data))
    if data.comparisons:
        lines.extend(_comparisons_section(data))
    lines.extend(_execution_verification_section(data))
    lines.extend(_limitations_section(data))
    lines.extend(_provenance_section(data))
    lines.extend(_reproducibility_section(data))
    return "\n".join(lines) + "\n"


def _overview_section(data: ReportData) -> list[str]:
    lines = ["## Overview", ""]
    lines.append(f"- **Run type:** {data.header.report_type}")
    lines.append(f"- **Run ID:** `{data.header.run_id}`")
    if data.header.trial_id:
        lines.append(f"- **Trial ID:** {data.header.trial_id}")
    lines.append(f"- **Report generated:** {data.header.generated_at.isoformat()}")
    lines.append("")
    return lines


def _model_section(data: ReportData) -> list[str]:
    model = data.model
    return [
        "## Model",
        "",
        f"- **Model ID:** `{model.model_id}`",
        f"- **Engine:** {model.engine}",
        f"- **Version:** {model.version}",
        f"- **Artifact hash:** `{model.artifact_hash}`",
        "",
    ]


def _population_section(data: ReportData) -> list[str]:
    population = data.population
    return [
        "## Population",
        "",
        f"- **Participants:** {population.participant_count}",
        f"- **Reference population:** {population.reference_population}",
        f"- **Generation ID:** `{population.generation_id}`",
        f"- **Requested seed:** {population.requested_seed}",
        f"- **Determinism level:** {population.determinism_level}",
        "",
    ]


def _arms_section(data: ReportData) -> list[str]:
    lines = [
        "## Interventions / Arms",
        "",
        "| Arm | Dose | Route | Participants |",
        "| --- | --- | --- | --- |",
    ]
    for arm in data.arms:
        lines.append(
            f"| {arm.arm_id} | {arm.dose_amount:g} {arm.dose_unit} | {arm.route} | "
            f"{arm.participant_count} |"
        )
    lines.append("")
    return lines


def _observation_schedule_section(data: ReportData) -> list[str]:
    schedule = data.observation_schedule
    assert schedule is not None
    times = ", ".join(f"{t:g}" for t in schedule.declared_times_min)
    return [
        "## Observation Schedule",
        "",
        f"- **Schedule ID:** `{schedule.schedule_id}`",
        f"- **Declared sample times (min):** {times}",
        "",
    ]


def _endpoints_section(data: ReportData) -> list[str]:
    lines = [
        "## PK Endpoints",
        "",
        "| Arm | Endpoint | n | Mean | SD | CV | Min | Median | Max |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data.endpoints:
        sd = _format_optional(row.sample_standard_deviation)
        cv = _format_optional(row.coefficient_of_variation)
        lines.append(
            f"| {row.arm_id or '—'} | {row.endpoint_type} ({row.unit}) | {row.n} | "
            f"{row.mean:g} | {sd} | {cv} | {row.minimum:g} | {row.p50:g} | {row.maximum:g} |"
        )
    lines.append("")
    return lines


def _comparisons_section(data: ReportData) -> list[str]:
    lines = [
        "## Arm Comparisons",
        "",
        "| Arm A | Arm B | Endpoint | A mean | B mean | Abs. diff | Rel. diff |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data.comparisons:
        relative = f"{row.relative_difference:.2%}" if row.relative_difference is not None else "—"
        lines.append(
            f"| {row.arm_a_id} | {row.arm_b_id} | {row.endpoint_type} ({row.unit}) | "
            f"{row.arm_a_mean:g} | {row.arm_b_mean:g} | {row.absolute_difference:g} | {relative} |"
        )
    lines.append("")
    return lines


def _execution_verification_section(data: ReportData) -> list[str]:
    lines = [
        "## Execution Verification",
        "",
        "| Arm | Model hash verified | Route/container verified | Solver executed |",
        "| --- | --- | --- | --- |",
    ]
    for row in data.execution_verification:
        lines.append(
            f"| {row.arm_id or '—'} | {_check(row.model_hash_verified)} | "
            f"{_check(row.route_container_verified)} | {_check(row.solver_executed)} |"
        )
    lines.append("")
    return lines


def _limitations_section(data: ReportData) -> list[str]:
    lines = ["## Scope and Limitations", ""]
    lines.extend(f"- {item}" for item in data.limitations)
    lines.append("")
    return lines


def _provenance_section(data: ReportData) -> list[str]:
    provenance = data.provenance
    lines = [
        "## Provenance",
        "",
        f"- **Model hash:** `{provenance.model_sha256}`",
        f"- **Population generation ID:** `{provenance.population_generation_id}`",
        f"- **Population content hash:** `{provenance.population_semantic_sha256}`",
    ]
    if provenance.trial_sha256:
        lines.append(f"- **Trial hash:** `{provenance.trial_sha256}`")
    if provenance.allocation_id:
        lines.append(
            f"- **Allocation:** `{provenance.allocation_id}` "
            f"(`{provenance.allocation_semantic_sha256}`)"
        )
    if provenance.comparison_id:
        lines.append(
            f"- **Comparison:** `{provenance.comparison_id}` "
            f"(`{provenance.comparison_semantic_sha256}`)"
        )
    if provenance.created_at:
        lines.append(f"- **Executed at:** {provenance.created_at.isoformat()}")
    if provenance.software_versions:
        versions = ", ".join(f"{k}={v}" for k, v in sorted(provenance.software_versions.items()))
        lines.append(f"- **Software versions:** {versions}")
    lines.append("")
    return lines


def _reproducibility_section(data: ReportData) -> list[str]:
    lines = ["## Reproducibility", ""]
    lines.extend(f"- {item}" for item in data.reproducibility)
    lines.append("")
    return lines


def _check(value: bool) -> str:
    return "✓" if value else "✗"


def _format_optional(value: float | None) -> str:
    return f"{value:g}" if value is not None else "—"
