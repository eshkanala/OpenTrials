"""Aciclovir IV PBPK execution over a physiology-state-overridden OTPHYS population.

verified OTPGEN population (unchanged, the source of truth for lineage)
    -> verified OTPHYS population (one column scaled by a PhysiologicalStateOverride)
    -> one verified intervention mutation applied to the loaded simulation
    -> single batched runSimulations(simulations=, population=) call over OTPHYS
    -> strict IndividualId -> *original OTPGEN* row lineage resolution
    -> lineage-aware normalized OTRES and OTPK v2 artifacts

Lineage is deliberately resolved against the *original* OTPGEN table, not the
OTPHYS table: ``PhysiologyPopulationArtifactStore`` guarantees identical row
order to its source population, so the same individual's
``source_population_row_index``/``source_population_row_sha256`` are
identical across every physiology state built from the same OTPGEN
generation. That is what lets endpoints from different states be compared
against literally the same subjects rather than merely the same population.

This module owns one narrow protocol, mirroring
``orchestration.aciclovir_iv_population`` but sourcing its executed table
from a verified OTPHYS artifact instead of OTPGEN directly. The external
worker boundary is kept in ``_execute_osp_population`` so contract tests can
replace it without requiring R.
"""

from __future__ import annotations

import platform
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

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
    physiology_coverage_for,
    resolve_osp_physiology_column,
    resolve_population_execution_lineage,
)
from opentrials.analysis.pk import PkEndpointResult, calculate_pk_endpoints
from opentrials.compound.compound import Compound, CompoundIdentity
from opentrials.compound.intervention import Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import SHA256_PATTERN, ModelPackage
from opentrials.patient.population import PopulationSpec
from opentrials.physiology.overrides import PhysiologicalStateOverride
from opentrials.simulation.engine import PreparedRun, RawSimulationResult
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.physiology import (
    PhysiologyPopulationArtifactManifest,
    PhysiologyPopulationArtifactStore,
)
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.results import (
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
)
from opentrials.trials.endpoints import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
)
from opentrials.trials.schedule import ObservationSchedule
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

PKML_PATH = Path("/Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/Aciclovir.pkml")
PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"
SUPPORTED_DOSES_MG = (125.0, 250.0)

ProgressCallback = Callable[[str], None]


class AciclovirIvPhysiologyPopulationRun(BaseModel):
    """Locations and derived per-subject endpoints from one physiology-state run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    result_directory: Path
    endpoint_directory: Path
    physiology_population_id: str = Field(pattern=r"^OTPHYS-[A-Za-z0-9_-]+$")
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    population_count: int = Field(gt=0)
    endpoints: tuple[PkEndpointResult, ...] = Field(min_length=1)
    physiology_state_verified: bool
    observation_schedule_verified: bool | None = None
    result_id: str = Field(pattern=r"^OTRES-[A-Za-z0-9_-]+$")
    result_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    raw_response_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_verification_sha256: str = Field(pattern=SHA256_PATTERN)


def build_physiology_population(
    *,
    physiology_population_id: str,
    physiology_root: Path,
    population_generation_id: str,
    population_root: Path,
    override: PhysiologicalStateOverride,
) -> PhysiologyPopulationArtifactManifest:
    """Verify one OTPGEN population and apply one verified override to it.

    This is the only place an OpenTrials-level physiology ``target`` is
    resolved to an OSP parameter path: the OSP-specific mapping
    (``adapters.osp.physiology_targets``) is looked up here, in
    orchestration, and handed to the engine-agnostic
    ``PhysiologyPopulationArtifactStore`` as an already-resolved value --
    storage itself never imports an OSP adapter.
    """
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(population_generation_id)
    population_table = pq.read_table(
        population_root / population_generation_id / population_manifest.individuals.path
    )
    source_columns = tuple(population_table.column_names)
    source_rows = tuple(dict(row) for row in population_table.to_pylist())

    osp_parameter_path = resolve_osp_physiology_column(override.target)
    coverage = physiology_coverage_for(override.target)

    physiology_store = PhysiologyPopulationArtifactStore(physiology_root)
    physiology_store.create_physiology_population(physiology_population_id)
    return physiology_store.write_physiology_population(
        physiology_population_id,
        source_population_manifest=population_manifest,
        source_column_names=source_columns,
        source_rows=source_rows,
        override=override,
        osp_parameter_path=osp_parameter_path,
        coverage=coverage,
    )


def run_aciclovir_iv_physiology_population(
    *,
    physiology_population_id: str,
    physiology_root: Path,
    population_root: Path,
    dose_mg: float,
    output_root: Path,
    r_libs_user: str,
    observation_schedule: ObservationSchedule | None = None,
    transport: Literal["json", "csv"] = "json",
    progress: ProgressCallback | None = None,
) -> AciclovirIvPhysiologyPopulationRun:
    """Execute the pinned Aciclovir IV model over one verified OTPHYS population.

    ``physiology_root`` must contain the already-written OTPHYS artifact;
    ``population_root`` must contain its declared source OTPGEN artifact.
    Both are independently re-verified here -- the OSP worker performs no
    trust decision of its own, and endpoint lineage is resolved against the
    re-verified *original* OTPGEN table, not the OTPHYS table. The declared
    physiology-state column is also read back from the actual reconstructed
    OSP population (not merely the request payload) and verified to match
    what OTPHYS declared, exactly the same "verify rather than trust"
    discipline used for dose and observation-schedule execution. ``transport``
    selects the Python<->R population/result transport (see HANDOFF v0.6-C);
    ``"json"`` is the unchanged default, ``"csv"`` is the faster file-based
    alternative -- both produce identical downstream scientific results.
    """
    _notify(progress, "verifying_physiology_population")
    physiology_store = PhysiologyPopulationArtifactStore(physiology_root)
    physiology_manifest = physiology_store.verify_physiology_population(physiology_population_id)
    physiology_table = pq.read_table(
        physiology_root / physiology_population_id / physiology_manifest.individuals.path
    )
    executed_columns = tuple(physiology_table.column_names)
    executed_rows = tuple(dict(row) for row in physiology_table.to_pylist())

    _notify(progress, "verifying_source_population")
    source_generation_id = physiology_manifest.source_generation_id
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(source_generation_id)
    if (
        population_manifest.individuals.semantic_content_sha256
        != physiology_manifest.source_population_semantic_sha256
    ):
        raise ValueError("OTPHYS source population hash does not match its declared OTPGEN.")
    source_table = pq.read_table(
        population_root / source_generation_id / population_manifest.individuals.path
    )
    source_columns = tuple(source_table.column_names)
    source_rows = tuple(dict(row) for row in source_table.to_pylist())

    if dose_mg not in SUPPORTED_DOSES_MG:
        raise ValueError("This workflow accepts only 125 mg or 250 mg infusions.")

    _notify(progress, "translating_intervention")
    package = _model_package()
    intervention = _intervention(dose_mg)
    translation = OspInterventionTranslator(_intervention_profile()).translate(intervention)
    assert translation.plan is not None

    run_id = f"OTR-aciclovir-iv-physiology-{uuid.uuid4().hex}"
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    _write_document(
        run_directory / "physiology_population_manifest.json",
        document("opentrials.physiology-population-artifact", physiology_manifest),
    )

    output_intervals = (
        _to_osp_output_intervals(observation_schedule)
        if observation_schedule is not None
        else ()
    )
    declared_times_min = (
        _declared_times_minutes(observation_schedule)
        if observation_schedule is not None
        else ()
    )

    _notify(progress, "executing_population")
    prepared = PreparedRun(
        run_id=run_id,
        trial=_execution_trial(physiology_manifest.individuals.rows, dose_mg),
        model_packages=(package,),
        seed=0,
    )
    raw_result = _execute_osp_population(
        prepared_run=prepared,
        population_columns=executed_columns,
        population_rows=executed_rows,
        expected_population_count=physiology_manifest.individuals.rows,
        assignments=translation.plan.assignments,
        output_intervals=output_intervals,
        population_readback_columns=(physiology_manifest.osp_parameter_path,),
        transport=transport,
        r_libs_user=r_libs_user,
    )
    _verify_population_raw_result(raw_result, run_id, physiology_manifest.individuals.rows)
    physiology_state_verified = _verify_physiology_state_readback(
        raw_result, executed_rows, physiology_manifest.osp_parameter_path
    )
    observation_schedule_verified: bool | None = None
    if observation_schedule is not None:
        _verify_output_schedule(raw_result, declared_times_min)
        observation_schedule_verified = True

    _notify(progress, "persisting_raw")
    raw_document = document("opentrials.osp-population-response", raw_result)
    raw_path = run_directory / "raw" / "osp_response.json"
    _write_document(raw_path, raw_document)
    raw_response_sha256 = raw_document.sha256()
    verification_hash = sha256(raw_result.payload["execution_verification"])

    rows = _selected_raw_rows(raw_result.payload)
    selection = ResultSelectionMapping(
        source_path=TOTAL_PLASMA_PATH,
        analyte="aciclovir",
        matrix="peripheral venous plasma",
        fraction="total",
        measurement="concentration",
        time_unit="min",
    )
    result_id = f"OTRES-{run_id.removeprefix('OTR-')}"
    result_store = ResultArtifactStore(run_directory / "normalized")
    result_directory = result_store.create_result(result_id)
    _notify(progress, "normalizing_results")
    result_manifest = result_store.write_concentration_time(
        result_id,
        source_raw_result=raw_document,
        raw_rows=rows,
        engine_id="osp",
        model_id=package.manifest.id,
        run_id=run_id,
        selection=selection,
    )
    result_store.verify_result(result_id)

    normalized_rows = normalize_osp_concentration_time_rows(rows, selection)
    endpoints = calculate_pk_endpoints(
        normalized_rows, result_manifest.concentration_time.semantic_content_sha256
    )

    _notify(progress, "resolving_lineage")
    result_individual_ids = raw_result.payload["result_individual_ids"]
    assert isinstance(result_individual_ids, Sequence)
    full_lineage = resolve_population_execution_lineage(
        population_manifest,
        source_columns,
        source_rows,
        tuple(int(individual_id) for individual_id in result_individual_ids),
    )
    endpoint_subjects = {endpoint.subject_id for endpoint in endpoints}
    subject_lineage = {subject_id: full_lineage[subject_id] for subject_id in endpoint_subjects}

    endpoint_id = f"OTPK-{run_id.removeprefix('OTR-')}"
    endpoint_store = PkEndpointArtifactStore(run_directory / "endpoints")
    endpoint_directory = endpoint_store.create_endpoint_artifact(endpoint_id)
    _notify(progress, "calculating_endpoints")
    endpoint_manifest = endpoint_store.write_endpoints(
        endpoint_id,
        endpoints=endpoints,
        source_result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
        source_result_id=result_id,
        run_id=run_id,
        source_engine_id="osp",
        source_model_id=package.manifest.id,
        subject_lineage=subject_lineage,
    )
    endpoint_store.verify_endpoints(endpoint_id)

    _notify(progress, "writing_manifest")
    manifest = document(
        "opentrials.aciclovir-iv-physiology-population-run",
        {
            "run_id": run_id,
            "physiology_population_id": physiology_population_id,
            "physiology_population_semantic_sha256": (
                physiology_manifest.individuals.semantic_content_sha256
            ),
            "source_generation_id": source_generation_id,
            "source_population_semantic_sha256": (
                population_manifest.individuals.semantic_content_sha256
            ),
            "override_target": physiology_manifest.override.target,
            "override_scale_factor": physiology_manifest.override.scale_factor,
            "population_count": physiology_manifest.individuals.rows,
            "dose_mg": dose_mg,
            "model_sha256": package.artifact_hash,
            "result_artifact_semantic_sha256": (
                result_manifest.concentration_time.semantic_content_sha256
            ),
            "endpoint_semantic_sha256": endpoint_manifest.endpoints.semantic_content_sha256,
            "verification_evidence_sha256": verification_hash,
            "physiology_state_verified": physiology_state_verified,
            "observation_schedule_verified": observation_schedule_verified,
            "software_versions": _software_versions(r_libs_user),
            "artifacts": {
                "physiology_population_manifest": "physiology_population_manifest.json",
                "raw_response": "raw/osp_response.json",
                "result": f"normalized/{result_id}",
                "endpoints": f"endpoints/{endpoint_id}",
            },
            "created_at": datetime.now(UTC),
        },
    )
    _write_document(run_directory / "manifest.json", manifest)
    _notify(progress, "completed")
    return AciclovirIvPhysiologyPopulationRun(
        run_id=run_id,
        run_directory=run_directory,
        result_directory=result_directory,
        endpoint_directory=endpoint_directory,
        physiology_population_id=physiology_population_id,
        source_generation_id=source_generation_id,
        population_count=physiology_manifest.individuals.rows,
        endpoints=endpoints,
        physiology_state_verified=physiology_state_verified,
        observation_schedule_verified=observation_schedule_verified,
        result_id=result_id,
        result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
        endpoint_id=endpoint_id,
        endpoint_semantic_sha256=endpoint_manifest.endpoints.semantic_content_sha256,
        raw_response_sha256=raw_response_sha256,
        execution_verification_sha256=verification_hash,
    )


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


def _intervention(dose_mg: float) -> Intervention:
    def assumed(value: float, unit: str) -> ScientificValue:
        return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)

    return Intervention(
        intervention_id="aciclovir-iv-physiology-population",
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


def _execution_trial(population_count: int, dose_mg: float) -> Trial:
    """A minimal, valid Trial to satisfy PreparedRun; execution uses explicit args."""

    def assumed(value: float, unit: str) -> ScientificValue:
        return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)

    return Trial(
        trial_id="ACICLOVIR-IV-PHYSIOLOGY-POPULATION-EXECUTION",
        title="Aciclovir IV physiology-state population execution",
        question_of_interest=(
            "Population-linked PBPK execution over a physiologically perturbed population."
        ),
        population=PopulationSpec(
            id="aciclovir-iv-physiology-population",
            size=population_count,
            seed=0,
            generator_version="0.1.0",
        ),
        arms=(
            TrialArm(
                arm_id="iv", name="IV", intervention=_intervention(dose_mg), allocation=1.0
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


def _intervention_profile() -> OspInterventionProfile:
    return OspInterventionProfile(
        compound_mappings=(
            OspCompoundMapping(opentrials_compound_id="aciclovir", osp_molecule_id="Aciclovir"),
        ),
        administration_targets=(
            OspAdministrationTarget(
                target_id="iv-250mg-10min",
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
    population_readback_columns: tuple[str, ...] = (),
    transport: Literal["json", "csv"] = "json",
    r_libs_user: str,
) -> RawSimulationResult:
    """Perform the external population execution; kept separate as the test seam."""
    engine = OspSimulationEngine(r_libs_user=r_libs_user)
    method = engine.run_population_csv if transport == "csv" else engine.run_population
    return method(
        prepared_run,
        population_columns=population_columns,
        population_rows=population_rows,
        expected_population_count=expected_population_count,
        expected_pkml_sha256=PKML_SHA256,
        expected_administration_container=IV_CONTAINER,
        parameter_assignments=assignments,
        output_intervals=output_intervals,
        population_readback_columns=population_readback_columns,
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


def _verify_physiology_state_readback(
    result: RawSimulationResult,
    executed_rows: tuple[Mapping[str, object], ...],
    osp_parameter_path: str,
    *,
    tolerance: float = 1e-8,
) -> bool:
    """Confirm the *actually reconstructed* OSP population carries the declared state.

    Reads ``population_readback`` -- built from ``populationToDataFrame()``
    on the real ``Population`` object the worker executed, not an echo of
    the request -- and checks every individual's value for
    ``osp_parameter_path`` against what OTPHYS declared for that same
    individual. Raises rather than silently trusting the request on any
    missing or mismatched subject.
    """
    readback = result.payload.get("population_readback")
    if not isinstance(readback, Sequence) or isinstance(readback, (str, bytes)) or not readback:
        raise ValueError(
            "OSP execution did not report a physiology-state population read-back."
        )
    declared_by_id: dict[int, float] = {}
    for row in executed_rows:
        raw_id = row["IndividualId"]
        raw_value = row[osp_parameter_path]
        if isinstance(raw_id, bool) or not isinstance(raw_id, int):
            raise ValueError("Executed population row has a non-integer IndividualId.")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("Executed population row has a non-numeric physiology-state value.")
        declared_by_id[raw_id] = float(raw_value)

    readback_ids: set[int] = set()
    for entry in readback:
        if not isinstance(entry, Mapping):
            raise ValueError("Physiology-state population read-back row is malformed.")
        individual_id = entry.get("IndividualId")
        if isinstance(individual_id, bool) or not isinstance(individual_id, int):
            raise ValueError("Physiology-state population read-back row has no IndividualId.")
        actual_value = entry.get(osp_parameter_path)
        if isinstance(actual_value, bool) or not isinstance(actual_value, (int, float)):
            raise ValueError(
                f"Physiology-state population read-back is missing {osp_parameter_path!r}."
            )
        expected_value = declared_by_id.get(individual_id)
        if expected_value is None:
            raise ValueError(
                f"Physiology-state population read-back has an unexpected IndividualId: "
                f"{individual_id}."
            )
        if abs(float(actual_value) - expected_value) > tolerance:
            raise ValueError(
                f"Physiology-state read-back for individual {individual_id} does not match "
                f"the declared OTPHYS value: expected {expected_value}, executed {actual_value}."
            )
        readback_ids.add(individual_id)

    if readback_ids != set(declared_by_id):
        raise ValueError(
            "Physiology-state population read-back does not cover exactly the executed "
            "population."
        )
    return True


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
        raise ValueError("OSP population execution count does not match the verified population.")
    result_individual_ids = result.payload.get("result_individual_ids")
    if (
        not isinstance(result_individual_ids, Sequence)
        or isinstance(result_individual_ids, (str, bytes))
        or len(result_individual_ids) != expected_population_count
    ):
        raise ValueError(
            "OSP population execution did not return exactly one IndividualId per population "
            "member."
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
