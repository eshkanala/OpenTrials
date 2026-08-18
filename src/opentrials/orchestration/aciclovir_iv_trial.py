"""Prospective multi-arm Aciclovir IV trial execution with preserved lineage.

verified OTPGEN population
    -> deterministic OTALLOC arm allocation (largest-remainder + seeded shuffle)
    -> per-arm verified intervention translation
    -> per-arm batched population-linked PBPK execution (each arm's allocated subset)
    -> lineage resolved against the FULL population, not the arm subset
    -> per-arm lineage-aware OTRES/OTPK v2 artifacts

This is the prospective sibling of ``orchestration.aciclovir_iv_population``:
instead of one dose applied to the whole population, this executes a real
``Trial`` with two or more declared arms, each receiving its own verified
intervention against its own reproducibly allocated subset of participants.
No repeated/multi-dose regimen support is implied or added here -- each arm
remains exactly one verified single IV infusion, matching the one
administration target this project has actually verified against OSP.
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
    OspAdministrationTarget,
    OspCompoundMapping,
    OspInterventionProfile,
    OspInterventionTranslator,
    OspOutputInterval,
    OspParameterAssignment,
    OspSimulationEngine,
    resolve_population_execution_lineage,
)
from opentrials.analysis.pk import PkEndpointResult, calculate_pk_endpoints
from opentrials.compound.intervention import Intervention, Route
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.simulation.engine import PreparedRun, RawSimulationResult
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.results import (
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
)
from opentrials.trials.schedule import ObservationSchedule
from opentrials.trials.trial import RandomizationType, Trial

PKML_PATH = Path("/Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/Aciclovir.pkml")
PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"

ProgressCallback = Callable[[str], None]


class ArmExecutionResult(BaseModel):
    """Locations and derived endpoints for one arm's verified execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    dose_mg: float = Field(gt=0)
    participant_count: int = Field(gt=0)
    result_directory: Path
    endpoint_directory: Path
    endpoints: tuple[PkEndpointResult, ...] = Field(min_length=1)


class AciclovirIvTrialRun(BaseModel):
    """Locations and per-arm outcomes from one immutable multi-arm trial run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    trial_id: str = Field(min_length=1)
    population_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    population_count: int = Field(gt=0)
    allocation_id: str = Field(pattern=r"^OTALLOC-[A-Za-z0-9_-]+$")
    arms: tuple[ArmExecutionResult, ...] = Field(min_length=2)


def run_aciclovir_iv_trial(
    trial: Trial,
    *,
    population_generation_id: str,
    population_root: Path,
    output_root: Path,
    r_libs_user: str,
    observation_schedule: ObservationSchedule | None = None,
    progress: ProgressCallback | None = None,
) -> AciclovirIvTrialRun:
    """Execute a real prospective multi-arm aciclovir IV trial through verified OSP.

    ``population_root`` must contain the ``population_generation_id`` OTPGEN
    artifact already written by ``PopulationArtifactStore``; it is verified
    before any row is handed to allocation or the OSP worker. Every arm's
    intervention must be exactly one IV aciclovir infusion at 0 min over
    10 min -- the one administration target this project has verified
    against OSP -- the dose amount itself is unconstrained.

    ``observation_schedule``, when supplied, declares the trial-wide sample
    timeline (separate from each arm's dosing timing) and is applied
    identically to every arm's solver execution. The solver's actual output
    times are read back and must match the declared schedule exactly (see
    HANDOFF v0.5-B); PK endpoints are then computed only from those declared
    sample times, not the solver's default dense grid. When omitted, the
    solver's own default output grid is used, exactly as before this
    parameter existed.
    """
    _notify(progress, "validating_trial")
    if trial.randomization is not RandomizationType.PARALLEL:
        raise ValueError("This workflow requires a PARALLEL-randomized, multi-arm trial.")
    arm_doses = {arm.arm_id: _validate_arm_intervention(arm.intervention) for arm in trial.arms}

    _notify(progress, "verifying_population")
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(population_generation_id)
    population_table = pq.read_table(
        population_root / population_generation_id / population_manifest.individuals.path
    )
    population_columns = tuple(population_table.column_names)
    population_rows = tuple(dict(row) for row in population_table.to_pylist())

    run_id = f"OTR-aciclovir-iv-trial-{uuid.uuid4().hex}"
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

    package = _model_package()
    arm_results: list[ArmExecutionResult] = []
    for arm in trial.arms:
        _notify(progress, f"executing_arm:{arm.arm_id}")
        allocated_rows = allocation_store.read_rows_for_arm(allocation_id, arm.arm_id)
        arm_row_indexes = sorted(_as_int(row["source_row_index"]) for row in allocated_rows)
        if not arm_row_indexes:
            raise ValueError(f"Arm {arm.arm_id!r} was allocated zero participants.")
        arm_population_rows = tuple(population_rows[index] for index in arm_row_indexes)

        translation = OspInterventionTranslator(_intervention_profile()).translate(
            arm.intervention
        )
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
            output_intervals=output_intervals,
            r_libs_user=r_libs_user,
        )
        _verify_population_raw_result(raw_result, arm_run_id, len(arm_population_rows))
        if observation_schedule is not None:
            _verify_output_schedule(raw_result, declared_times_min)

        arm_directory = run_directory / "arms" / arm.arm_id
        raw_document = document("opentrials.osp-population-response", raw_result)
        _write_document(arm_directory / "raw" / "osp_response.json", raw_document)

        rows = _selected_raw_rows(raw_result.payload)
        selection = ResultSelectionMapping(
            source_path=TOTAL_PLASMA_PATH,
            analyte="aciclovir",
            matrix="peripheral venous plasma",
            fraction="total",
            measurement="concentration",
            time_unit="min",
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
        endpoint_store.verify_endpoints(endpoint_id)

        arm_results.append(
            ArmExecutionResult(
                arm_id=arm.arm_id,
                dose_mg=arm_doses[arm.arm_id],
                participant_count=len(arm_population_rows),
                result_directory=result_directory,
                endpoint_directory=endpoint_directory,
                endpoints=endpoints,
            )
        )

    _notify(progress, "writing_manifest")
    manifest = document(
        "opentrials.aciclovir-iv-trial-run",
        {
            "run_id": run_id,
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
            "software_versions": _software_versions(r_libs_user),
            "created_at": datetime.now(UTC),
        },
    )
    _write_document(run_directory / "manifest.json", manifest)
    _notify(progress, "completed")
    return AciclovirIvTrialRun(
        run_id=run_id,
        run_directory=run_directory,
        trial_id=trial.trial_id,
        population_generation_id=population_generation_id,
        population_count=population_manifest.actual_count,
        allocation_id=allocation_id,
        arms=tuple(arm_results),
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer source_row_index in an allocation row.")
    return value


def _validate_arm_intervention(intervention: Intervention) -> float:
    """Return the dose in mg if the arm matches the one verified administration target."""
    if intervention.compound.identity.compound_id != "aciclovir":
        raise ValueError("This workflow accepts only aciclovir arm interventions.")
    if len(intervention.regimen.doses) != 1:
        raise ValueError("This workflow accepts exactly one IV infusion per arm.")
    dose = intervention.regimen.doses[0]
    if dose.route is not Route.INTRAVENOUS:
        raise ValueError("This workflow accepts only intravenous administration.")
    if dose.administration_time.to("min").value != 0.0:
        raise ValueError("This workflow requires administration at 0 min.")
    if dose.infusion_duration is None or dose.infusion_duration.to("min").value != 10.0:
        raise ValueError("This workflow requires a 10 min IV infusion.")
    return dose.amount.to("mg").value


def _model_package() -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="osp.aciclovir.vergin-1995-iv",
            version="12.4.4",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "umol/L"},
            applicability=Applicability(species=("human",)),
            license="Bundled ospsuite example; redistribution not asserted.",
        ),
        artifact_uri=PKML_PATH.as_uri(),
        artifact_hash=f"sha256:{PKML_SHA256}",
        parameter_set_id="vergin-1995-iv-as-packaged",
        parameter_hash=f"sha256:{PKML_SHA256}",
        package_hash=f"sha256:{PKML_SHA256}",
    )


def _intervention_profile() -> OspInterventionProfile:
    return OspInterventionProfile(
        compound_mappings=(
            OspCompoundMapping(opentrials_compound_id="aciclovir", osp_molecule_id="Aciclovir"),
        ),
        administration_targets=(
            OspAdministrationTarget(
                target_id="iv-any-dose-10min",
                osp_molecule_id="Aciclovir",
                route=Route.INTRAVENOUS,
                dose_parameter_path=f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Dose",
                dose_unit="kg",
                administration_time_parameter_path=(
                    f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Start time"
                ),
                administration_time_unit="min",
                infusion_duration_parameter_path=(
                    f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Infusion time"
                ),
                infusion_duration_unit="min",
            ),
        ),
    )


def _execute_osp_population(
    *,
    prepared_run: PreparedRun,
    population_columns: tuple[str, ...],
    population_rows: tuple[Mapping[str, object], ...],
    expected_population_count: int,
    assignments: tuple[OspParameterAssignment, ...],
    output_intervals: tuple[OspOutputInterval, ...] = (),
    r_libs_user: str,
) -> RawSimulationResult:
    """Perform the external population execution; kept separate as the test seam."""
    engine = OspSimulationEngine(r_libs_user=r_libs_user)
    return engine.run_population(
        prepared_run,
        population_columns=population_columns,
        population_rows=population_rows,
        expected_population_count=expected_population_count,
        expected_pkml_sha256=PKML_SHA256,
        expected_administration_container=IV_CONTAINER,
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


def _selected_raw_rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, object], ...]:
    raw_rows = payload.get("raw_result_rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("OSP response is missing raw_result_rows.")
    selected = tuple(
        row
        for row in raw_rows
        if isinstance(row, Mapping) and row.get("paths") == TOTAL_PLASMA_PATH
    )
    if not selected:
        raise ValueError("OSP response has no rows for the verified total plasma output path.")
    return selected


def _software_versions(r_libs_user: str) -> dict[str, str]:
    versions = OspSimulationEngine(r_libs_user=r_libs_user).version_info()
    return {**versions, "python": platform.python_version(), "platform": platform.platform()}


def _write_document(path: Path, value: SchemaDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.canonical_json() + "\n", encoding="utf-8")


def _notify(progress: ProgressCallback | None, stage: str) -> None:
    if progress is not None:
        progress(stage)
