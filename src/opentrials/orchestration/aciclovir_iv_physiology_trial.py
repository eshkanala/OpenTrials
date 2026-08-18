"""Prospective virtual trial across declared physiological states.

verified OTPGEN population
    -> N declared PhysiologicalStateOverrides (>= 2, including one baseline)
    -> N verified OTPHYS populations, each preserving identical row order
    -> the same intervention/dose/route/observation schedule executed for
       every state, as N independent batched OSP population runs
    -> N lineage-aware OTRES/OTPK artifacts, resolved against the shared
       *original* OTPGEN table so every state carries identical subject
       lineage
    -> one immutable OTPHYCMP paired cross-state comparison (state-level
       descriptive summaries plus subject-level baseline-vs-state deltas)
    -> one immutable, independently re-verifiable OTPHYTRIAL provenance
       record

This is the physiology-state analogue of ``orchestration.aciclovir_iv_trial``
(OTTRIAL): each state is executed as its own OSP run against the whole
population (never a subset -- physiology states, unlike trial arms, are not
a partition of the population), and the top-level record computes nothing
itself, only referencing what every other store already verified.
"""

from __future__ import annotations

import platform
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opentrials.compound.compound import Compound, CompoundIdentity
from opentrials.compound.intervention import Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import sha256
from opentrials.orchestration.aciclovir_iv_physiology_population import (
    PKML_SHA256,
    build_physiology_population,
    run_aciclovir_iv_physiology_population,
)
from opentrials.patient.population import PopulationSpec
from opentrials.physiology.overrides import PhysiologicalStateOverride
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.physiology import PhysiologyPopulationArtifactStore
from opentrials.storage.physiology_comparison import PhysiologyComparisonArtifactStore
from opentrials.storage.physiology_trial import (
    PhysiologyStateRunRecord,
    PhysiologyTrialArtifactManifest,
    PhysiologyTrialArtifactStore,
)
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.trials.endpoints import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
)
from opentrials.trials.physiology_comparison import compare_physiology_states
from opentrials.trials.schedule import ObservationSchedule
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

ProgressCallback = Callable[[str], None]


class PhysiologyStateDeclaration(BaseModel):
    """One declared physiological state to execute the trial under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_id: str = Field(min_length=1)
    override: PhysiologicalStateOverride


class AciclovirIvPhysiologyTrialRun(BaseModel):
    """Top-level locations and identities from one physiology-state trial run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    trial_run_id: str = Field(pattern=r"^OTPHYTRIAL-[A-Za-z0-9_-]+$")
    comparison_id: str = Field(pattern=r"^OTPHYCMP-[A-Za-z0-9_-]+$")
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    baseline_state_id: str = Field(min_length=1)
    state_ids: tuple[str, ...] = Field(min_length=2)


def run_aciclovir_iv_physiology_trial(
    *,
    population_generation_id: str,
    population_root: Path,
    physiology_root: Path,
    states: tuple[PhysiologyStateDeclaration, ...],
    baseline_state_id: str,
    dose_mg: float,
    output_root: Path,
    r_libs_user: str,
    observation_schedule: ObservationSchedule | None = None,
    transport: Literal["json", "csv"] = "json",
    progress: ProgressCallback | None = None,
) -> AciclovirIvPhysiologyTrialRun:
    """Execute one prospective trial across every declared physiological state.

    Every state runs against the *whole* verified population (physiology
    states are not a partition, unlike trial arms) with the same
    intervention, dose, route, and declared observation schedule. Lineage
    is resolved against the shared original OTPGEN for every state, so
    ``trials.physiology_comparison.compare_physiology_states`` can pair
    every subject against themselves across states.
    """
    if len(states) < 2:
        raise ValueError("A physiology-state trial requires at least two declared states.")
    state_ids = [declaration.state_id for declaration in states]
    if len(set(state_ids)) != len(state_ids):
        raise ValueError("Declared physiology-state IDs must be unique.")
    if baseline_state_id not in state_ids:
        raise ValueError("baseline_state_id must be one of the declared states.")

    _notify(progress, "verifying_source_population")
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(population_generation_id)

    run_id = f"OTR-aciclovir-iv-physiology-trial-{uuid.uuid4().hex}"
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    physiology_store = PhysiologyPopulationArtifactStore(physiology_root)

    state_records: list[PhysiologyStateRunRecord] = []
    endpoint_stores: dict[str, PkEndpointArtifactStore] = {}
    state_physiology_population_ids: dict[str, str] = {}
    state_endpoint_ids: dict[str, str] = {}

    for declaration in states:
        _notify(progress, f"building_state:{declaration.state_id}")
        physiology_population_id = f"OTPHYS-{run_id.removeprefix('OTR-')}-{declaration.state_id}"
        physiology_manifest = build_physiology_population(
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_generation_id=population_generation_id,
            population_root=population_root,
            override=declaration.override,
        )
        state_physiology_population_ids[declaration.state_id] = physiology_population_id

        _notify(progress, f"executing_state:{declaration.state_id}")
        state_run = run_aciclovir_iv_physiology_population(
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_root=population_root,
            dose_mg=dose_mg,
            output_root=run_directory / "states",
            r_libs_user=r_libs_user,
            observation_schedule=observation_schedule,
            transport=transport,
            progress=_state_progress(progress, declaration.state_id),
        )
        endpoint_stores[declaration.state_id] = PkEndpointArtifactStore(
            state_run.run_directory / "endpoints"
        )
        state_endpoint_ids[declaration.state_id] = state_run.endpoint_id

        state_records.append(
            PhysiologyStateRunRecord(
                state_id=declaration.state_id,
                physiology_population_id=physiology_population_id,
                physiology_population_semantic_sha256=(
                    physiology_manifest.individuals.semantic_content_sha256
                ),
                override_target=declaration.override.target,
                override_scale_factor=declaration.override.scale_factor,
                executed_run_id=state_run.run_id,
                raw_response_sha256=state_run.raw_response_sha256,
                execution_verification_sha256=state_run.execution_verification_sha256,
                physiology_state_verified=state_run.physiology_state_verified,
                observation_schedule_verified=state_run.observation_schedule_verified,
                result_id=state_run.result_id,
                result_semantic_sha256=state_run.result_semantic_sha256,
                endpoint_id=state_run.endpoint_id,
                endpoint_semantic_sha256=state_run.endpoint_semantic_sha256,
            )
        )

    _notify(progress, "comparing_states")
    comparison_result = compare_physiology_states(
        baseline_state_id=baseline_state_id,
        state_physiology_population_ids=state_physiology_population_ids,
        state_endpoint_ids=state_endpoint_ids,
        physiology_store=physiology_store,
        endpoint_stores=endpoint_stores,
    )
    comparison_store = PhysiologyComparisonArtifactStore(run_directory / "comparison")
    comparison_id = f"OTPHYCMP-{run_id.removeprefix('OTR-')}"
    comparison_store.create_comparison(comparison_id)
    comparison_manifest = comparison_store.write_comparison(comparison_id, comparison_result)

    _notify(progress, "writing_trial_record")
    trial = _trial_declaration(population_manifest.actual_count, dose_mg)
    trial_run_store = PhysiologyTrialArtifactStore(run_directory / "trial_run")
    trial_run_id = f"OTPHYTRIAL-{run_id.removeprefix('OTR-')}"
    trial_run_store.create_trial_run(trial_run_id)
    trial_run_store.write_trial_run(
        trial_run_id,
        PhysiologyTrialArtifactManifest(
            trial_run_id=trial_run_id,
            trial_id=trial.trial_id,
            trial_sha256=sha256(trial),
            source_generation_id=population_generation_id,
            source_population_semantic_sha256=(
                population_manifest.individuals.semantic_content_sha256
            ),
            model_id="osp.aciclovir.vergin-1995-iv",
            model_sha256=f"sha256:{PKML_SHA256}",
            baseline_state_id=baseline_state_id,
            states=tuple(state_records),
            comparison_id=comparison_id,
            comparison_semantic_sha256=comparison_manifest.state_summaries.semantic_content_sha256,
            software_versions=_software_versions(r_libs_user),
            created_at=datetime.now(UTC),
        ),
    )

    _notify(progress, "completed")
    return AciclovirIvPhysiologyTrialRun(
        run_id=run_id,
        run_directory=run_directory,
        trial_run_id=trial_run_id,
        comparison_id=comparison_id,
        source_generation_id=population_generation_id,
        baseline_state_id=baseline_state_id,
        state_ids=tuple(state_ids),
    )


def _trial_declaration(population_count: int, dose_mg: float) -> Trial:
    """A minimal, valid Trial declaration hashed as this physiology trial's identity.

    This intentionally describes the intervention and source population
    only, as a single non-randomized arm -- ``Trial``/``TrialArm`` model a
    population *partition* (v0.5's trial arms), which physiology states are
    not: every state below executes the *same* whole population. The
    physiology-state structure itself is recorded correctly and completely
    in ``PhysiologyTrialArtifactManifest.states``/``baseline_state_id``, not
    forced into this reused type.
    """

    def assumed(value: float, unit: str) -> ScientificValue:
        return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)

    intervention = Intervention(
        intervention_id="aciclovir-iv-physiology-trial",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="single-iv-infusion",
            doses=(
                Dose(
                    amount=assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                    infusion_duration=assumed(10, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="ACICLOVIR-IV-PHYSIOLOGY-STATE-TRIAL",
        title="Aciclovir IV prospective physiological-state trial",
        question_of_interest=(
            "Same population and intervention executed across declared physiological states."
        ),
        population=PopulationSpec(
            id="aciclovir-iv-physiology-trial", size=population_count, seed=0,
            generator_version="0.1.0",
        ),
        arms=(
            TrialArm(
                arm_id="iv", name="IV", intervention=intervention, allocation=1.0
            ),
        ),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=0,
    )


def _software_versions(r_libs_user: str) -> dict[str, str]:
    from opentrials.adapters.osp import OspSimulationEngine

    versions = OspSimulationEngine(r_libs_user=r_libs_user).version_info()
    return {**versions, "python": platform.python_version(), "platform": platform.platform()}


def _notify(progress: ProgressCallback | None, stage: str) -> None:
    if progress is not None:
        progress(stage)


def _state_progress(
    progress: ProgressCallback | None, state_id: str
) -> ProgressCallback | None:
    """Prefix one state's nested progress stages with its state ID, if forwarding."""
    if progress is None:
        return None

    def _forward(stage: str) -> None:
        _notify(progress, f"{state_id}:{stage}")

    return _forward
