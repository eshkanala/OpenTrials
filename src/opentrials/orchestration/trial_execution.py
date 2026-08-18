"""Prospective multi-arm trial execution with preserved lineage, generic over any model.

verified OTPGEN population
    -> deterministic OTALLOC arm allocation (largest-remainder + seeded shuffle)
    -> per-arm verified intervention translation
    -> per-arm batched population-linked PBPK execution (each arm's allocated subset)
    -> lineage resolved against the FULL population, not the arm subset
    -> per-arm lineage-aware OTRES/OTPK v2 artifacts

This is the prospective sibling of ``orchestration.population_execution``:
instead of one dose applied to the whole population, this executes a real
``Trial`` with two or more declared arms, each receiving its own verified
intervention against its own reproducibly allocated subset of participants.
No repeated/multi-dose regimen support is implied or added here -- each arm
remains exactly one verified single infusion, matching the one
administration target a registered model declares it has actually verified
against OSP.

v0.7-B: this module used to be ``orchestration.aciclovir_iv_trial``, with
the pinned Aciclovir model hard-coded. Every model-specific value now comes
from a ``ModelCapabilityProfile`` passed in by the caller.
"""

from __future__ import annotations

import platform
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp import (
    OspInterventionTranslator,
    OspOutputInterval,
    OspParameterAssignment,
    OspSimulationEngine,
    resolve_population_execution_lineage,
)
from opentrials.adapters.osp.capability import osp_intervention_profile_from_capability
from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT
from opentrials.analysis.pk import PkEndpointResult, calculate_pk_endpoints
from opentrials.compound.intervention import Intervention
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.capability import AdministrationCapability, ModelCapabilityProfile
from opentrials.simulation.engine import PreparedRun, RawSimulationResult
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.arm_comparison_artifacts import ArmComparisonArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.results import (
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
)
from opentrials.storage.trial_run import (
    ArmRunRecord,
    ObservationScheduleRecord,
    TrialRunArtifactStore,
    VirtualTrialArtifactManifest,
)
from opentrials.trials.arm_comparison import compare_trial_arms
from opentrials.trials.schedule import ObservationSchedule
from opentrials.trials.trial import RandomizationType, Trial

ProgressCallback = Callable[[str], None]


class ArmExecutionResult(BaseModel):
    """Locations and derived endpoints for one arm's verified execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    dose_mg: float = Field(gt=0)
    participant_count: int = Field(gt=0)
    result_id: str = Field(pattern=r"^OTRES-[A-Za-z0-9_-]+$")
    result_directory: Path
    endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    endpoint_directory: Path
    endpoints: tuple[PkEndpointResult, ...] = Field(min_length=1)


class TrialExecutionRun(BaseModel):
    """Locations and per-arm outcomes from one immutable multi-arm trial run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    trial_id: str = Field(min_length=1)
    population_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    population_count: int = Field(gt=0)
    allocation_id: str = Field(pattern=r"^OTALLOC-[A-Za-z0-9_-]+$")
    comparison_id: str = Field(pattern=r"^OTACMP-[A-Za-z0-9_-]+$")
    trial_run_id: str = Field(pattern=r"^OTTRIAL-[A-Za-z0-9_-]+$")
    arms: tuple[ArmExecutionResult, ...] = Field(min_length=2)


def run_trial_execution(
    trial: Trial,
    *,
    model_capability_profile: ModelCapabilityProfile,
    population_generation_id: str,
    population_root: Path,
    output_root: Path,
    r_libs_user: str,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
    observation_schedule: ObservationSchedule | None = None,
    progress: ProgressCallback | None = None,
) -> TrialExecutionRun:
    """Execute a real prospective multi-arm trial through verified OSP.

    ``population_root`` must contain the ``population_generation_id`` OTPGEN
    artifact already written by ``PopulationArtifactStore``; it is verified
    before any row is handed to allocation or the OSP worker. Every arm's
    intervention must match the one administration this model's
    ``ModelCapabilityProfile`` declares it has actually verified against
    OSP -- the dose amount itself is unconstrained (subject to any declared
    ``supported_doses``).

    ``observation_schedule``, when supplied, declares the trial-wide sample
    timeline (separate from each arm's dosing timing) and is applied
    identically to every arm's solver execution. The solver's actual output
    times are read back and must match the declared schedule exactly (see
    HANDOFF v0.5-B); PK endpoints are then computed only from those declared
    sample times, not the solver's default dense grid. When omitted, the
    solver's own default output grid is used, exactly as before this
    parameter existed.
    """
    administration = model_capability_profile.administrations[0]
    output = model_capability_profile.outputs[0]
    package = model_capability_profile.package

    _notify(progress, "validating_trial")
    if trial.randomization is not RandomizationType.PARALLEL:
        raise ValueError("This workflow requires a PARALLEL-randomized, multi-arm trial.")
    arm_doses = {
        arm.arm_id: _validate_arm_intervention(
            model_capability_profile, administration, arm.intervention
        )
        for arm in trial.arms
    }

    _notify(progress, "verifying_population")
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(population_generation_id)
    population_table = pq.read_table(
        population_root / population_generation_id / population_manifest.individuals.path
    )
    population_columns = tuple(population_table.column_names)
    population_rows = tuple(dict(row) for row in population_table.to_pylist())

    run_id = f"OTR-trial-{uuid.uuid4().hex}"
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    _write_document(run_directory / "trial.json", document("opentrials.trial", trial))
    _write_document(
        run_directory / "population_manifest.json",
        document("opentrials.population-artifact", population_manifest),
    )

    _notify(progress, "allocating_arms")
    allocation_store = TrialArmAllocationArtifactStore(
        run_directory / "allocation", population_store=population_store
    )
    allocation_id = f"OTALLOC-{run_id.removeprefix('OTR-')}"
    allocation_store.create_allocation(allocation_id)
    allocation_store.write_allocation(
        allocation_id, trial=trial, generation_id=population_generation_id
    )

    output_intervals = (
        _to_osp_output_intervals(observation_schedule) if observation_schedule is not None else ()
    )
    declared_times_min = (
        _declared_times_minutes(observation_schedule) if observation_schedule is not None else ()
    )

    osp_profile = osp_intervention_profile_from_capability(model_capability_profile)
    arm_results: list[ArmExecutionResult] = []
    arm_run_records: list[ArmRunRecord] = []
    endpoint_stores: dict[str, PkEndpointArtifactStore] = {}
    for arm in trial.arms:
        _notify(progress, f"executing_arm:{arm.arm_id}")
        allocated_rows = allocation_store.read_rows_for_arm(allocation_id, arm.arm_id)
        arm_row_indexes = sorted(_as_int(row["source_row_index"]) for row in allocated_rows)
        if not arm_row_indexes:
            raise ValueError(f"Arm {arm.arm_id!r} was allocated zero participants.")
        arm_population_rows = tuple(population_rows[index] for index in arm_row_indexes)

        translation = OspInterventionTranslator(osp_profile).translate(arm.intervention)
        assert translation.plan is not None
        arm_run_id = f"{run_id}-arm-{arm.arm_id}"
        raw_result = _execute_osp_population(
            prepared_run=PreparedRun(
                run_id=arm_run_id, trial=trial, model_packages=(package,), seed=trial.seed
            ),
            population_columns=population_columns,
            population_rows=arm_population_rows,
            expected_population_count=len(arm_population_rows),
            assignments=translation.plan.assignments,
            expected_pkml_sha256=package.artifact_hash.removeprefix("sha256:"),
            expected_administration_container=administration.administration_container_path,
            output_intervals=output_intervals,
            r_libs_user=r_libs_user,
            rscript_path=rscript_path,
            dotnet_root=dotnet_root,
        )
        _verify_population_raw_result(raw_result, arm_run_id, len(arm_population_rows))
        schedule_verified: bool | None = None
        if observation_schedule is not None:
            _verify_output_schedule(raw_result, declared_times_min)
            schedule_verified = True

        arm_directory = run_directory / "arms" / arm.arm_id
        raw_document = document("opentrials.osp-population-response", raw_result)
        _write_document(arm_directory / "raw" / "osp_response.json", raw_document)
        raw_response_sha256 = raw_document.sha256()
        execution_verification_sha256 = sha256(raw_result.payload["execution_verification"])

        rows = _selected_raw_rows(raw_result.payload, output.parameter_path)
        selection = ResultSelectionMapping(
            source_path=output.parameter_path,
            analyte=output.analyte,
            matrix=output.matrix,
            fraction=output.fraction,
            measurement=output.measurement,
            time_unit=output.time_unit,
        )
        result_id = f"OTRES-{run_id.removeprefix('OTR-')}-{arm.arm_id}"
        result_store = ResultArtifactStore(arm_directory / "normalized")
        result_directory = result_store.create_result(result_id)
        result_manifest = result_store.write_concentration_time(
            result_id,
            source_raw_result=raw_document,
            raw_rows=rows,
            engine_id="osp",
            model_id=package.manifest.id,
            run_id=arm_run_id,
            selection=selection,
        )
        result_store.verify_result(result_id)

        normalized_rows = normalize_osp_concentration_time_rows(rows, selection)
        endpoints = calculate_pk_endpoints(
            normalized_rows, result_manifest.concentration_time.semantic_content_sha256
        )

        result_individual_ids = raw_result.payload["result_individual_ids"]
        assert isinstance(result_individual_ids, Sequence)
        full_lineage = resolve_population_execution_lineage(
            population_manifest,
            population_columns,
            population_rows,
            tuple(int(individual_id) for individual_id in result_individual_ids),
            require_full_coverage=False,
        )
        endpoint_subjects = {endpoint.subject_id for endpoint in endpoints}
        subject_lineage = {
            subject_id: full_lineage[subject_id] for subject_id in endpoint_subjects
        }

        endpoint_id = f"OTPK-{run_id.removeprefix('OTR-')}-{arm.arm_id}"
        endpoint_store = PkEndpointArtifactStore(arm_directory / "endpoints")
        endpoint_directory = endpoint_store.create_endpoint_artifact(endpoint_id)
        endpoint_store.write_endpoints(
            endpoint_id,
            endpoints=endpoints,
            source_result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
            source_result_id=result_id,
            run_id=arm_run_id,
            source_engine_id="osp",
            source_model_id=package.manifest.id,
            subject_lineage=subject_lineage,
        )
        arm_endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
        endpoint_stores[arm.arm_id] = endpoint_store

        arm_results.append(
            ArmExecutionResult(
                arm_id=arm.arm_id,
                dose_mg=arm_doses[arm.arm_id],
                participant_count=len(arm_population_rows),
                result_id=result_id,
                result_directory=result_directory,
                endpoint_id=endpoint_id,
                endpoint_directory=endpoint_directory,
                endpoints=endpoints,
            )
        )
        arm_run_records.append(
            ArmRunRecord(
                arm_id=arm.arm_id,
                requested_dose_mg=arm_doses[arm.arm_id],
                participant_count=len(arm_population_rows),
                executed_run_id=arm_run_id,
                raw_response_sha256=raw_response_sha256,
                execution_verification_sha256=execution_verification_sha256,
                observation_schedule_verified=schedule_verified,
                result_id=result_id,
                result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
                endpoint_id=endpoint_id,
                endpoint_semantic_sha256=arm_endpoint_manifest.endpoints.semantic_content_sha256,
            )
        )

    _notify(progress, "writing_manifest")
    manifest = document(
        "opentrials.trial-execution-run",
        {
            "run_id": run_id,
            "model_id": package.manifest.id,
            "trial_id": trial.trial_id,
            "trial_sha256": sha256(trial),
            "population_generation_id": population_generation_id,
            "population_semantic_sha256": population_manifest.individuals.semantic_content_sha256,
            "population_count": population_manifest.actual_count,
            "allocation_id": allocation_id,
            "observation_schedule": (
                {
                    "schedule_id": observation_schedule.schedule_id,
                    "declared_times_min": list(declared_times_min),
                }
                if observation_schedule is not None
                else None
            ),
            "arms": {
                arm.arm_id: {
                    "dose_mg": arm_doses[arm.arm_id],
                    "participant_count": result.participant_count,
                }
                for arm, result in zip(trial.arms, arm_results, strict=True)
            },
            "software_versions": _software_versions(r_libs_user, rscript_path, dotnet_root),
            "created_at": datetime.now(UTC),
        },
    )
    _write_document(run_directory / "manifest.json", manifest)

    _notify(progress, "comparing_arms")
    comparison_result = compare_trial_arms(
        allocation_id=allocation_id,
        arm_endpoint_ids={record.arm_id: record.endpoint_id for record in arm_run_records},
        allocation_store=allocation_store,
        endpoint_stores=endpoint_stores,
    )
    comparison_store = ArmComparisonArtifactStore(run_directory / "comparison")
    comparison_id = f"OTACMP-{run_id.removeprefix('OTR-')}"
    comparison_store.create_comparison(comparison_id)
    comparison_manifest = comparison_store.write_comparison(comparison_id, comparison_result)

    _notify(progress, "writing_trial_record")
    verified_allocation = allocation_store.verify_allocation(allocation_id)
    trial_run_store = TrialRunArtifactStore(run_directory / "trial_run")
    trial_run_id = f"OTTRIAL-{run_id.removeprefix('OTR-')}"
    trial_run_store.create_trial_run(trial_run_id)
    trial_run_store.write_trial_run(
        trial_run_id,
        VirtualTrialArtifactManifest(
            trial_run_id=trial_run_id,
            trial_id=trial.trial_id,
            trial_sha256=sha256(trial),
            source_generation_id=population_generation_id,
            source_population_semantic_sha256=(
                population_manifest.individuals.semantic_content_sha256
            ),
            allocation_id=allocation_id,
            allocation_semantic_sha256=verified_allocation.allocation.semantic_content_sha256,
            allocation_seed=verified_allocation.requested_seed,
            allocation_apportionment_method=verified_allocation.apportionment_method,
            model_id=package.manifest.id,
            model_sha256=package.artifact_hash,
            observation_schedule=(
                ObservationScheduleRecord(
                    schedule_id=observation_schedule.schedule_id,
                    declared_times_min=declared_times_min,
                )
                if observation_schedule is not None
                else None
            ),
            arms=tuple(arm_run_records),
            comparison_id=comparison_id,
            comparison_semantic_sha256=comparison_manifest.arm_summaries.semantic_content_sha256,
            software_versions=_software_versions(r_libs_user, rscript_path, dotnet_root),
            created_at=datetime.now(UTC),
        ),
    )

    _notify(progress, "completed")
    return TrialExecutionRun(
        run_id=run_id,
        run_directory=run_directory,
        trial_id=trial.trial_id,
        population_generation_id=population_generation_id,
        population_count=population_manifest.actual_count,
        allocation_id=allocation_id,
        comparison_id=comparison_id,
        trial_run_id=trial_run_id,
        arms=tuple(arm_results),
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer source_row_index in an allocation row.")
    return value


def _validate_arm_intervention(
    profile: ModelCapabilityProfile,
    administration: AdministrationCapability,
    intervention: Intervention,
) -> float:
    """Return the dose in mg if the arm matches the one verified administration target."""
    compound_ids = {compound.compound_id for compound in profile.compounds}
    if intervention.compound.identity.compound_id not in compound_ids:
        raise ValueError(
            f"This model only accepts interventions for compounds {sorted(compound_ids)!r}."
        )
    if len(intervention.regimen.doses) != 1:
        raise ValueError("This workflow accepts exactly one dose per arm.")
    dose = intervention.regimen.doses[0]
    if dose.route is not administration.route:
        raise ValueError(f"This workflow accepts only {administration.route} administration.")
    if (
        administration.fixed_administration_time_min is not None
        and dose.administration_time.to("min").value != administration.fixed_administration_time_min
    ):
        raise ValueError(
            f"This workflow requires administration at "
            f"{administration.fixed_administration_time_min} min."
        )
    if administration.fixed_infusion_duration_min is not None:
        if (
            dose.infusion_duration is None
            or dose.infusion_duration.to("min").value != administration.fixed_infusion_duration_min
        ):
            raise ValueError(
                f"This workflow requires a {administration.fixed_infusion_duration_min} min "
                "infusion."
            )
    return dose.amount.to(administration.supported_dose_unit or "mg").value


def _execute_osp_population(
    *,
    prepared_run: PreparedRun,
    population_columns: tuple[str, ...],
    population_rows: tuple[Mapping[str, object], ...],
    expected_population_count: int,
    assignments: tuple[OspParameterAssignment, ...],
    expected_pkml_sha256: str,
    expected_administration_container: str,
    output_intervals: tuple[OspOutputInterval, ...] = (),
    r_libs_user: str,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
) -> RawSimulationResult:
    """Perform the external population execution; kept separate as the test seam."""
    engine = OspSimulationEngine(
        r_libs_user=r_libs_user, rscript_path=rscript_path, dotnet_root=dotnet_root
    )
    return engine.run_population(
        prepared_run,
        population_columns=population_columns,
        population_rows=population_rows,
        expected_population_count=expected_population_count,
        expected_pkml_sha256=expected_pkml_sha256,
        expected_administration_container=expected_administration_container,
        parameter_assignments=assignments,
        output_intervals=output_intervals,
    )


def _to_osp_output_intervals(schedule: ObservationSchedule) -> tuple[OspOutputInterval, ...]:
    """Convert a declared ObservationSchedule into OSP output-grid windows (minutes)."""
    return tuple(
        OspOutputInterval(
            start_time=window.start.to("min").value,
            end_time=window.end.to("min").value,
            resolution=1.0 / window.interval.to("min").value,
            interval_name=f"{schedule.schedule_id}-{index}",
        )
        for index, window in enumerate(schedule.windows)
    )


def _declared_times_minutes(schedule: ObservationSchedule) -> tuple[float, ...]:
    """The schedule's declared sample times in minutes, matching the OSP time axis."""
    times: set[float] = set()
    for window in schedule.windows:
        times.update(window.declared_times("min"))
    return tuple(sorted(times))


def _verify_output_schedule(
    result: RawSimulationResult, declared_times_min: Sequence[float]
) -> None:
    """Reject a run whose solver output times do not exactly match the declared schedule."""
    if result.payload.get("output_schedule_applied") is not True:
        raise ValueError("OSP execution did not apply the declared observation schedule.")
    observed = result.payload.get("observed_output_times")
    if not isinstance(observed, Sequence) or isinstance(observed, (str, bytes)):
        raise ValueError("OSP execution did not report observed output times.")
    observed_sorted = sorted(float(value) for value in observed)
    declared_sorted = sorted(declared_times_min)
    if len(observed_sorted) != len(declared_sorted) or any(
        abs(a - b) > 1e-6 for a, b in zip(observed_sorted, declared_sorted, strict=True)
    ):
        raise ValueError(
            "OSP solver output times do not match the declared observation schedule: "
            f"observed {observed_sorted!r} vs. declared {declared_sorted!r}."
        )


def _verify_population_raw_result(
    result: RawSimulationResult, expected_run_id: str, expected_population_count: int
) -> None:
    if result.run_id != expected_run_id or result.engine_id != "osp":
        raise ValueError("OSP population execution result does not match the prepared run.")
    verification = result.payload.get("execution_verification")
    if not isinstance(verification, Mapping):
        raise ValueError("OSP population execution did not provide verification evidence.")
    for key in ("model_hash_verification", "route_container_verification"):
        value = verification.get(key)
        if not isinstance(value, Mapping) or value.get("verified") is not True:
            raise ValueError(f"OSP population execution verification failed for {key!r}.")
    if verification.get("solver_executed") is not True:
        raise ValueError("OSP population execution verification did not confirm solver execution.")
    assignments = verification.get("parameter_assignments")
    if not isinstance(assignments, Sequence) or not assignments:
        raise ValueError("OSP population execution verification has no parameter assignments.")
    if any(
        not isinstance(item, Mapping) or item.get("verified") is not True for item in assignments
    ):
        raise ValueError(
            "OSP population execution verification did not confirm every parameter assignment."
        )
    if result.payload.get("population_count") != expected_population_count:
        raise ValueError("OSP population execution count does not match the allocated arm.")
    result_individual_ids = result.payload.get("result_individual_ids")
    if (
        not isinstance(result_individual_ids, Sequence)
        or isinstance(result_individual_ids, (str, bytes))
        or len(result_individual_ids) != expected_population_count
    ):
        raise ValueError(
            "OSP population execution did not return exactly one IndividualId per allocated "
            "arm participant."
        )


def _selected_raw_rows(
    payload: Mapping[str, Any], output_path: str
) -> tuple[Mapping[str, object], ...]:
    raw_rows = payload.get("raw_result_rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("OSP response is missing raw_result_rows.")
    selected = tuple(
        row for row in raw_rows if isinstance(row, Mapping) and row.get("paths") == output_path
    )
    if not selected:
        raise ValueError("OSP response has no rows for the verified declared output path.")
    return selected


def _software_versions(
    r_libs_user: str,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
) -> dict[str, str]:
    versions = OspSimulationEngine(
        r_libs_user=r_libs_user, rscript_path=rscript_path, dotnet_root=dotnet_root
    ).version_info()
    return {**versions, "python": platform.python_version(), "platform": platform.platform()}


def _write_document(path: Path, value: SchemaDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.canonical_json() + "\n", encoding="utf-8")


def _notify(progress: ProgressCallback | None, stage: str) -> None:
    if progress is not None:
        progress(stage)
