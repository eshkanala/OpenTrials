"""Researcher-facing multi-arm trial execution."""

from __future__ import annotations

from pathlib import Path

from opentrials.events import EventSink, stage_progress_adapter
from opentrials.models.capability import ModelCapabilityProfile
from opentrials.orchestration.trial_execution import run_trial_execution
from opentrials.sdk.run import TrialRun
from opentrials.trials.schedule import ObservationSchedule
from opentrials.trials.trial import Trial


def run_trial(
    trial: Trial,
    *,
    model_capability_profile: ModelCapabilityProfile,
    population_generation_id: str,
    population_root: Path,
    output_root: Path,
    r_libs_user: str,
    observation_schedule: ObservationSchedule | None = None,
    events: EventSink | None = None,
) -> TrialRun:
    """Execute a real prospective multi-arm trial (two or more declared arms).

    A thin, researcher-facing wrapper over
    ``orchestration.trial_execution.run_trial_execution`` -- every
    scientific decision (allocation, per-arm verified execution, lineage,
    comparison) still happens there, unchanged; this only adapts its
    result into ``sdk.run.TrialRun`` and its bare stage-name progress
    callback into structured ``Event`` objects.
    """
    execution = run_trial_execution(
        trial,
        model_capability_profile=model_capability_profile,
        population_generation_id=population_generation_id,
        population_root=population_root,
        output_root=output_root,
        r_libs_user=r_libs_user,
        observation_schedule=observation_schedule,
        progress=stage_progress_adapter(events),
    )
    return TrialRun(
        execution,
        model_capability_profile=model_capability_profile,
        population_root=population_root,
    )
