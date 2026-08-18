"""Contract tests for the Markdown and HTML report renderers.

Uses a hand-built ``ReportData`` fixture rather than a real run -- these
tests are about rendering correctly given data, not about producing that
data (see ``test_reporting_build.py`` for that). Reuses one trial-shaped
fixture across both renderers so a missing section is caught the same way
in either format.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from opentrials.reporting.data import (
    ArmSummarySection,
    ConcentrationTimeSeries,
    EndpointSummaryRow,
    ExecutionVerificationRow,
    ModelSummarySection,
    ObservationScheduleSection,
    PairwiseComparisonRow,
    PopulationSummarySection,
    ProvenanceSection,
    ReportData,
    ReportHeader,
)
from opentrials.reporting.render_html import render_html
from opentrials.reporting.render_markdown import render_markdown


def _trial_report_data() -> ReportData:
    return ReportData(
        header=ReportHeader(
            report_type="trial",
            run_id="OTR-trial-abc123",
            title="ACICLOVIR-DOSE-COMPARISON",
            trial_id="ACICLOVIR-DOSE-COMPARISON",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        model=ModelSummarySection(
            model_id="osp.aciclovir.vergin-1995-iv",
            engine="osp",
            version="12.4.4",
            artifact_hash="sha256:" + "a" * 64,
        ),
        population=PopulationSummarySection(
            generation_id="OTPGEN-demo",
            participant_count=20,
            reference_population="European_ICRP_2002",
            requested_seed=11,
            determinism_level="STRICT",
        ),
        arms=(
            ArmSummarySection(
                arm_id="low", dose_amount=125.0, dose_unit="mg", route="INTRAVENOUS",
                participant_count=10,
            ),
            ArmSummarySection(
                arm_id="high", dose_amount=250.0, dose_unit="mg", route="INTRAVENOUS",
                participant_count=10,
            ),
        ),
        observation_schedule=ObservationScheduleSection(
            schedule_id="dense-then-sparse", declared_times_min=(0.0, 15.0, 30.0)
        ),
        endpoints=(
            EndpointSummaryRow(
                arm_id="low", endpoint_type="CMAX", unit="umol/L", n=10, mean=28.8,
                sample_standard_deviation=3.4, coefficient_of_variation=0.12,
                minimum=24.9, maximum=35.0, p25=26.0, p50=27.5, p75=30.0,
            ),
            EndpointSummaryRow(
                arm_id="high", endpoint_type="CMAX", unit="umol/L", n=10, mean=55.3,
                sample_standard_deviation=6.1, coefficient_of_variation=0.11,
                minimum=44.2, maximum=67.0, p25=50.0, p50=55.6, p75=60.0,
            ),
        ),
        comparisons=(
            PairwiseComparisonRow(
                arm_a_id="high", arm_b_id="low", endpoint_type="CMAX", unit="umol/L",
                arm_a_mean=55.3, arm_b_mean=28.8, absolute_difference=26.5,
                relative_difference=0.92,
            ),
        ),
        concentration_time_series=(
            ConcentrationTimeSeries(
                label="low", time_unit="min", unit="umol/L",
                points=((0.0, 0.0), (10.0, 28.8), (60.0, 5.0)),
            ),
            ConcentrationTimeSeries(
                label="high", time_unit="min", unit="umol/L",
                points=((0.0, 0.0), (10.0, 55.3), (60.0, 9.0)),
            ),
        ),
        execution_verification=(
            ExecutionVerificationRow(
                arm_id="low", model_hash_verified=True, route_container_verified=True,
                solver_executed=True,
            ),
            ExecutionVerificationRow(
                arm_id="high", model_hash_verified=True, route_container_verified=True,
                solver_executed=True,
            ),
        ),
        provenance=ProvenanceSection(
            model_sha256="sha256:" + "a" * 64,
            population_generation_id="OTPGEN-demo",
            population_semantic_sha256="sha256:" + "b" * 64,
            trial_sha256="sha256:" + "c" * 64,
            allocation_id="OTALLOC-abc123",
            allocation_semantic_sha256="sha256:" + "d" * 64,
            comparison_id="OTACMP-abc123",
            comparison_semantic_sha256="sha256:" + "e" * 64,
            software_versions={"ospsuite": "12.4.4", "r": "4.6.1"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        limitations=(
            "This is a computational simulation result, not a clinical or diagnostic finding.",
            "OpenTrials is for research and educational use only.",
        ),
        reproducibility=("Run directory: /tmp/runs/OTR-trial-abc123",),
        source_run_directory=Path("/tmp/runs/OTR-trial-abc123"),
        source_population_root=Path("/tmp/runs/populations"),
    )


def test_render_markdown_includes_every_section() -> None:
    markdown = render_markdown(_trial_report_data())

    for heading in (
        "## Overview", "## Model", "## Population", "## Interventions / Arms",
        "## Observation Schedule", "## PK Endpoints", "## Arm Comparisons",
        "## Execution Verification", "## Scope and Limitations", "## Provenance",
        "## Reproducibility",
    ):
        assert heading in markdown
    assert "ACICLOVIR-DOSE-COMPARISON" in markdown
    assert "55.3" in markdown


def test_render_markdown_omits_observation_schedule_when_absent() -> None:
    data = _trial_report_data().model_copy(update={"observation_schedule": None})
    markdown = render_markdown(data)
    assert "## Observation Schedule" not in markdown


def test_render_html_is_self_contained() -> None:
    document = render_html(_trial_report_data())

    assert "<script" not in document
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', document)
    assert "ACICLOVIR-DOSE-COMPARISON" in document


def test_render_html_embeds_well_formed_svg_figures() -> None:
    document = render_html(_trial_report_data())
    svgs = re.findall(r"<svg.*?</svg>", document, re.S)

    assert len(svgs) >= 2  # concentration-time chart + at least one comparison bar chart
    for svg in svgs:
        ET.fromstring(svg)


def test_render_html_shows_verification_pills() -> None:
    document = render_html(_trial_report_data())
    assert document.count("class='pill pill-ok'") == 6  # 2 arms x 3 facts, all True
