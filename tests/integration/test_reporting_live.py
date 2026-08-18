"""Opt-in live proof: v0.9-B reporting against a real, freshly executed run.

Runs the exact shipped example project through the real SDK/OSP path, then
builds and renders both Markdown and self-contained HTML reports purely by
re-verifying the persisted artifacts on disk -- proving the reporting
layer against real numbers, not a fixture.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from opentrials.reporting import build_trial_report, render_html, render_markdown
from opentrials.sdk.project import Project

EXAMPLE_PROJECT = (
    Path(__file__).resolve().parents[2] / "examples" / "aciclovir_dose_comparison.yaml"
)

pytestmark = pytest.mark.osp_integration


def test_report_reflects_a_real_executed_trial_end_to_end(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    project = Project.load(EXAMPLE_PROJECT)
    run = project.run(output_root=tmp_path / "runs", r_libs_user=r_libs_user)

    # Both from the live run's own .report() and re-derived independently
    # from disk -- they must describe the same real executed trial.
    from_method = run.report()
    from_disk = build_trial_report(run.run_directory, run.artifacts.population_store.root)
    assert from_method.model_copy(update={"header": None}) == from_disk.model_copy(
        update={"header": None}
    )

    assert from_disk.population.participant_count == 20
    assert {arm.arm_id for arm in from_disk.arms} == {"low", "high"}
    assert all(row.model_hash_verified for row in from_disk.execution_verification)
    assert all(row.solver_executed for row in from_disk.execution_verification)

    markdown = render_markdown(from_disk)
    assert "ACICLOVIR-DOSE-COMPARISON" in markdown
    assert "## Arm Comparisons" in markdown

    html_document = render_html(from_disk)
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html_document)
    svgs = re.findall(r"<svg.*?</svg>", html_document, re.S)
    assert len(svgs) >= 2
    for svg in svgs:
        ET.fromstring(svg)

    report_path = tmp_path / "report.html"
    report_path.write_text(html_document, encoding="utf-8")
    print(
        "\nLive v0.9-B reporting proof -- wrote a",
        len(html_document),
        "byte self-contained HTML report to",
        report_path,
    )
