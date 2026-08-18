"""Researcher-facing population generation: hides the OSP translate/generate/persist dance.

Every live test and integration proof in this project has, until now,
repeated the same seven-step dance by hand: translate a ``PopulationSpec``
into an OSP request, run the OSP generator, then persist the result through
``PopulationArtifactStore`` with its own generator/generation provenance
records. That is exactly the artifact plumbing a researcher should not have
to reconstruct themselves -- this module is that dance, done once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
    OspPopulationGenerator,
)
from opentrials.adapters.osp.population import (
    OspHumanPopulation,
    OspPopulationProfile,
    OspPopulationTranslator,
)
from opentrials.core.serialization import document
from opentrials.events import Event, EventSink, EventStatus, stage_progress_adapter
from opentrials.models.capability import ModelCapabilityProfile
from opentrials.orchestration.population_execution import run_population_execution
from opentrials.patient.population import PopulationSpec
from opentrials.sdk.run import PopulationRun
from opentrials.storage.populations import (
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

DEFAULT_REFERENCE_POPULATION = OspHumanPopulation.EUROPEAN_ICRP_2002


def generate_population(
    spec: PopulationSpec,
    *,
    population_root: Path,
    r_libs_user: str,
    reference_population: OspHumanPopulation = DEFAULT_REFERENCE_POPULATION,
    events: EventSink | None = None,
) -> PopulationArtifactManifest:
    """Translate, generate through real OSP, and immutably persist one population.

    ``generation_id`` is derived from ``spec.id`` as ``OTPGEN-{spec.id}``,
    the same convention every existing live test already uses by hand.
    Returns the persisted, hash-verified manifest -- ready to pass straight
    into ``sdk.trial.run_trial``/``sdk.population.run_population`` as
    ``population_generation_id``/``population_root``.
    """
    generation_id = f"OTPGEN-{spec.id}"
    _emit(events, "translating_population_specification", EventStatus.STARTED)
    translation = OspPopulationTranslator(
        OspPopulationProfile(reference_population=reference_population)
    ).translate(spec)
    _emit(
        events,
        "translating_population_specification",
        EventStatus.COMPLETED,
        {"reference_population": reference_population.value},
    )

    _emit(events, "generating_population", EventStatus.STARTED)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translation)
    _emit(
        events,
        "generating_population",
        EventStatus.COMPLETED,
        {"population_count": len(result.raw_rows), "engine_seed": result.engine_seed},
    )

    _emit(events, "persisting_population", EventStatus.STARTED)
    store = PopulationArtifactStore(population_root)
    store.create_generation(generation_id)
    manifest = store.write_population(
        generation_id,
        population_id=result.population_id,
        source_request=document(
            POPULATION_WORKER_REQUEST_SCHEMA,
            translation.request,
            POPULATION_WORKER_SCHEMA_VERSION,
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp",
            population_model=translation.request.reference_population.value,
            software_versions={"ospsuite": result.ospsuite_version, "r": result.r_version},
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=result.requested_seed,
            engine_seed=result.engine_seed,
            determinism_level=result.determinism_level.value,
        ),
        requested_count=translation.request.number_of_individuals,
        column_names=result.column_names,
        rows=result.raw_rows,
    )
    _emit(
        events,
        "persisting_population",
        EventStatus.COMPLETED,
        {"generation_id": generation_id, "actual_count": manifest.actual_count},
    )
    return manifest


def run_population(
    *,
    model_capability_profile: ModelCapabilityProfile,
    population_generation_id: str,
    population_root: Path,
    dose_mg: float,
    output_root: Path,
    r_libs_user: str,
    transport: Literal["json", "csv"] = "json",
    events: EventSink | None = None,
) -> PopulationRun:
    """Execute one verified dose across a whole already-generated population.

    A thin, researcher-facing wrapper over
    ``orchestration.population_execution.run_population_execution`` --
    every scientific decision (verification, lineage, endpoint
    calculation) still happens there, unchanged; this only adapts its
    result into ``sdk.run.PopulationRun`` and its bare stage-name progress
    callback into structured ``Event`` objects.
    """
    execution = run_population_execution(
        model_capability_profile=model_capability_profile,
        population_generation_id=population_generation_id,
        population_root=population_root,
        dose_mg=dose_mg,
        output_root=output_root,
        r_libs_user=r_libs_user,
        transport=transport,
        progress=stage_progress_adapter(events),
    )
    return PopulationRun(
        execution,
        model_capability_profile=model_capability_profile,
        population_root=population_root,
    )


def _emit(
    events: EventSink | None,
    stage: str,
    status: EventStatus,
    detail: dict[str, object] | None = None,
) -> None:
    if events is None:
        return
    events(Event(stage=stage, status=status, timestamp=datetime.now(UTC), detail=detail or {}))
