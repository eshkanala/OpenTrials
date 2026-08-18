"""Opt-in live proof: the full researcher-facing SDK path against real OSP.

``Project.load`` -> ``project.run()`` -> a real, freshly generated
population -> real multi-arm PBPK execution -> a working ``TrialRun`` --
proves the whole v0.9-A stack end to end, using the exact example shipped
in ``examples/aciclovir_dose_comparison.yaml`` so that example is itself
kept honest by a live test, not just documentation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentrials.events import Event, EventStatus
from opentrials.sdk.project import Project
from opentrials.sdk.run import TrialRun

EXAMPLE_PROJECT = (
    Path(__file__).resolve().parents[2] / "examples" / "aciclovir_dose_comparison.yaml"
)

pytestmark = pytest.mark.osp_integration


def test_project_run_executes_the_shipped_example_end_to_end(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    project = Project.load(EXAMPLE_PROJECT)
    events: list[Event] = []

    run = project.run(
        output_root=tmp_path / "runs", r_libs_user=r_libs_user, events=events.append
    )

    assert isinstance(run, TrialRun)
    assert run.population.participant_count == 20
    assert {arm.arm_id for arm in run.arms} == {"low", "high"}
    assert len(run.endpoints) > 0
    assert run.verify() is True

    # Both the population-generation stages and the trial-execution stages
    # went through the same event sink -- proving the SDK's structured
    # events cover the whole run, not just the final execution step.
    stages = [event.stage for event in events]
    assert "generating_population" in stages
    assert "persisting_population" in stages
    assert "verifying_population" in stages
    assert "comparing_arms" in stages
    assert not any(event.status is EventStatus.FAILED for event in events)

    summary = run.summary()
    print("\nLive v0.9-A SDK proof -- trial summary:\n", summary)
