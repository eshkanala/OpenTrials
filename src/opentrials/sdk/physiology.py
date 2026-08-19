"""Researcher-facing prospective physiology-state trial execution.

A thin, researcher-facing wrapper over
``orchestration.physiology_trial_execution.run_physiology_trial_execution`` --
every scientific decision (per-state OTPHYS construction, lineage,
comparison) still happens there, unchanged; this only adapts its bare
stage-name progress callback into structured ``Event`` objects, matching
the exact same pattern ``sdk.trial.run_trial``/``sdk.population.run_population``
already establish. Kept as a separate SDK entry point rather than folded
into ``sdk.project.Project.run()``: a physiology-state trial always runs
the *whole* population at every declared state (states are not a partition,
unlike trial arms -- see the orchestration module's own docstring), so it
is not a variant of the existing population/trial routing, it is a third,
genuinely different execution mode a researcher opts into explicitly.
"""

from __future__ import annotations

from pathlib import Path

from opentrials.events import EventSink, stage_progress_adapter
from opentrials.models.capability import ModelCapabilityProfile
from opentrials.orchestration.physiology_trial_execution import (
    PhysiologyStateDeclaration,
    PhysiologyTrialExecutionRun,
    run_physiology_trial_execution,
)
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.physiology import PhysiologyPopulationArtifactStore
from opentrials.storage.physiology_comparison import PhysiologyComparisonArtifactStore
from opentrials.storage.physiology_trial import (
    PhysiologyTrialArtifactManifest,
    PhysiologyTrialArtifactStore,
)
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.trials.schedule import ObservationSchedule


def run_trial_physiology_states(
    *,
    model_capability_profile: ModelCapabilityProfile,
    population_generation_id: str,
    population_root: str | Path,
    physiology_root: str | Path,
    states: tuple[PhysiologyStateDeclaration, ...],
    baseline_state_id: str,
    dose_mg: float,
    output_root: str | Path,
    r_libs_user: str,
    observation_schedule: ObservationSchedule | None = None,
    events: EventSink | None = None,
) -> PhysiologyTrialExecutionRun:
    """Execute one prospective trial across every declared physiological state.

    Every state runs the same intervention/dose/route/declared observation
    schedule against the *whole* verified population. Returns the top-level
    ``PhysiologyTrialExecutionRun`` record (run directory, trial/comparison
    artifact IDs) -- call ``verify_physiology_states`` afterward for the
    real, re-verified per-state provenance a caller would want to display.

    Unlike ``sdk.trial.run_trial``/``sdk.population.run_population``, this
    does not accept ``rscript_path``/``dotnet_root`` overrides --
    ``orchestration.physiology_trial_execution`` does not yet expose them
    (it always uses OpenTrials' own compiled-in default runtime location),
    a genuine pre-existing gap, not one this wrapper papers over.
    """
    return run_physiology_trial_execution(
        model_capability_profile=model_capability_profile,
        population_generation_id=population_generation_id,
        population_root=Path(population_root),
        physiology_root=Path(physiology_root),
        states=states,
        baseline_state_id=baseline_state_id,
        dose_mg=dose_mg,
        output_root=Path(output_root),
        r_libs_user=r_libs_user,
        observation_schedule=observation_schedule,
        progress=stage_progress_adapter(events),
    )


def verify_physiology_states(
    run: PhysiologyTrialExecutionRun,
    *,
    population_root: str | Path,
    physiology_root: str | Path,
) -> PhysiologyTrialArtifactManifest:
    """Re-verify and return the full per-state provenance record for a completed run.

    Re-derives every hash from disk via
    ``PhysiologyTrialArtifactStore.verify_physiology_trial`` -- never trusts
    the in-memory ``run`` object beyond the IDs/paths it needs to know
    where to look, the same discipline every other artifact read in this
    project follows. Per-state endpoint stores are reconstructed from each
    state's own recorded ``executed_run_id``, matching exactly where
    ``run_physiology_trial_execution`` itself wrote them
    (``<run_directory>/states/<executed_run_id>/endpoints``).
    """
    trial_run_store = PhysiologyTrialArtifactStore(run.run_directory / "trial_run")
    manifest = trial_run_store.read_manifest(run.trial_run_id)
    endpoint_stores = {
        state.state_id: PkEndpointArtifactStore(
            run.run_directory / "states" / state.executed_run_id / "endpoints"
        )
        for state in manifest.states
    }
    return trial_run_store.verify_physiology_trial(
        run.trial_run_id,
        population_store=PopulationArtifactStore(Path(population_root)),
        physiology_store=PhysiologyPopulationArtifactStore(Path(physiology_root)),
        endpoint_stores=endpoint_stores,
        comparison_store=PhysiologyComparisonArtifactStore(run.run_directory / "comparison"),
    )
