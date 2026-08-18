"""Population-linked Aciclovir IV PBPK execution with preserved OTPGEN lineage.

verified OTPGEN population
    -> reconstructed OSP population (populationFromDataFrame, proven bit-identical)
    -> one verified intervention mutation applied to the loaded simulation
    -> single batched runSimulations(simulations=, population=) call
    -> strict IndividualId -> OTPGEN row lineage resolution
    -> lineage-aware normalized OTRES and OTPK v2 artifacts

This module owns one narrow protocol, mirroring ``orchestration.aciclovir_iv``
but for a whole persisted population rather than one ad hoc individual. The
external-worker boundary is kept in ``_execute_osp_population`` so contract
tests can replace it without requiring R.
"""

from __future__ import annotations

import platform
import time
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
    OspParameterAssignment,
    OspSimulationEngine,
    resolve_population_execution_lineage,
)
from opentrials.analysis.pk import PkEndpointResult, calculate_pk_endpoints
from opentrials.compound.compound import Compound, CompoundIdentity
from opentrials.compound.intervention import Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.patient.population import PopulationSpec
from opentrials.simulation.engine import PreparedRun, RawSimulationResult
from opentrials.storage.endpoints import PkEndpointArtifactStore
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
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

PKML_PATH = Path("/Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/Aciclovir.pkml")
PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"
SUPPORTED_DOSES_MG = (125.0, 250.0)

ProgressCallback = Callable[[str], None]


class AciclovirIvPopulationRun(BaseModel):
    """Locations and derived per-subject endpoints from one immutable population run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    result_directory: Path
    endpoint_directory: Path
    population_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    population_count: int = Field(gt=0)
    endpoints: tuple[PkEndpointResult, ...] = Field(min_length=1)
    stage_seconds: dict[str, float] = Field(default_factory=dict)


def run_aciclovir_iv_population(
    *,
    population_generation_id: str,
    population_root: Path,
    dose_mg: float,
    output_root: Path,
    r_libs_user: str,
    transport: Literal["json", "csv"] = "json",
    progress: ProgressCallback | None = None,
) -> AciclovirIvPopulationRun:
    """Execute the pinned Aciclovir IV model over one whole verified OTPGEN population.

    ``population_root`` must contain the ``population_generation_id`` artifact
    already written by ``PopulationArtifactStore``. This function verifies it
    before ever handing the table to the OSP worker; the worker performs no
    trust decision of its own. ``transport`` selects how the population/result
    tables cross the Python<->R boundary: ``"json"`` (default, unchanged
    since v0.1) embeds them in the request/response JSON; ``"csv"`` (v0.6-C)
    uses OSP's own ``loadPopulation()``/``exportResultsToCSV()`` file-based
    transport, which a capability probe measured as dramatically faster at
    scale with identical downstream scientific results -- see HANDOFF v0.6-C.
    """
    stage_seconds: dict[str, float] = {}
    stage_started = time.perf_counter()

    def _mark(stage: str) -> None:
        nonlocal stage_started
        now = time.perf_counter()
        stage_seconds[stage] = now - stage_started
        stage_started = now

    _notify(progress, "verifying_population")
    population_store = PopulationArtifactStore(population_root)
    population_manifest = population_store.verify_population(population_generation_id)
    population_table = pq.read_table(
        population_root / population_generation_id / population_manifest.individuals.path
    )
    population_columns = tuple(population_table.column_names)
    population_rows = tuple(dict(row) for row in population_table.to_pylist())
    _mark("verify_otpgen")

    if dose_mg not in SUPPORTED_DOSES_MG:
        raise ValueError("This workflow accepts only 125 mg or 250 mg infusions.")

    _notify(progress, "translating_intervention")
    package = _model_package()
    intervention = _intervention(dose_mg)
    translation = OspInterventionTranslator(_intervention_profile()).translate(intervention)
    assert translation.plan is not None
    _mark("translate_intervention")

    run_id = f"OTR-aciclovir-iv-population-{uuid.uuid4().hex}"
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    _write_document(
        run_directory / "population_manifest.json",
        document("opentrials.population-artifact", population_manifest),
    )

    _notify(progress, "executing_population")
    prepared = PreparedRun(
        run_id=run_id,
        trial=_execution_trial(population_manifest.actual_count, dose_mg),
        model_packages=(package,),
        seed=0,
    )
    raw_result = _execute_osp_population(
        prepared_run=prepared,
        population_columns=population_columns,
        population_rows=population_rows,
        expected_population_count=population_manifest.actual_count,
        assignments=translation.plan.assignments,
        transport=transport,
        r_libs_user=r_libs_user,
    )
    _verify_population_raw_result(raw_result, run_id, population_manifest.actual_count)
    _mark("execute_population")
    # CSV transport reports its own internal R-side and Python-side stage
    # timing (see HANDOFF v0.6-C); fold it in as detail without double
    # counting it into the stage totals above.
    r_timing = raw_result.payload.get("timing")
    python_transport_timing = raw_result.payload.get("python_timing")
    if isinstance(r_timing, dict):
        stage_seconds.update({f"r_{key}": value for key, value in r_timing.items()})
    if isinstance(python_transport_timing, dict):
        stage_seconds.update(
            {f"python_{key}": value for key, value in python_transport_timing.items()}
        )

    _notify(progress, "persisting_raw")
    raw_document = document("opentrials.osp-population-response", raw_result)
    raw_path = run_directory / "raw" / "osp_response.json"
    _write_document(raw_path, raw_document)
    raw_hash = raw_document.sha256()
    verification_hash = sha256(raw_result.payload["execution_verification"])
    _mark("persist_raw")

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
    _mark("normalize_results")

    normalized_rows = normalize_osp_concentration_time_rows(rows, selection)
    endpoints = calculate_pk_endpoints(
        normalized_rows, result_manifest.concentration_time.semantic_content_sha256
    )
    _mark("pk_analysis")

    _notify(progress, "resolving_lineage")
    result_individual_ids = raw_result.payload["result_individual_ids"]
    assert isinstance(result_individual_ids, Sequence)
    full_lineage = resolve_population_execution_lineage(
        population_manifest,
        population_columns,
        population_rows,
        tuple(int(individual_id) for individual_id in result_individual_ids),
    )
    endpoint_subjects = {endpoint.subject_id for endpoint in endpoints}
    subject_lineage = {subject_id: full_lineage[subject_id] for subject_id in endpoint_subjects}
    _mark("resolve_lineage")

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
    _mark("persist_endpoints")
    stage_seconds["total"] = sum(
        value for key, value in stage_seconds.items() if not key.startswith(("r_", "python_"))
    )

    _notify(progress, "writing_manifest")
    manifest = document(
        "opentrials.aciclovir-iv-population-run",
        {
            "run_id": run_id,
            "population_generation_id": population_generation_id,
            "population_semantic_sha256": population_manifest.individuals.semantic_content_sha256,
            "population_count": population_manifest.actual_count,
            "dose_mg": dose_mg,
            "transport": transport,
            "model_sha256": package.artifact_hash,
            "raw_sha256": raw_hash,
            "result_artifact_semantic_sha256": (
                result_manifest.concentration_time.semantic_content_sha256
            ),
            "endpoint_semantic_sha256": endpoint_manifest.endpoints.semantic_content_sha256,
            "verification_evidence_sha256": verification_hash,
            "software_versions": _software_versions(r_libs_user),
            "stage_seconds": stage_seconds,
            "artifacts": {
                "population_manifest": "population_manifest.json",
                "raw_response": "raw/osp_response.json",
                "result": f"normalized/{result_id}",
                "endpoints": f"endpoints/{endpoint_id}",
            },
            "created_at": datetime.now(UTC),
        },
    )
    _write_document(run_directory / "manifest.json", manifest)
    _notify(progress, "completed")
    return AciclovirIvPopulationRun(
        run_id=run_id,
        run_directory=run_directory,
        result_directory=result_directory,
        endpoint_directory=endpoint_directory,
        population_generation_id=population_generation_id,
        population_count=population_manifest.actual_count,
        endpoints=endpoints,
        stage_seconds=stage_seconds,
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
        intervention_id="aciclovir-iv-population",
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
        trial_id="ACICLOVIR-IV-POPULATION-EXECUTION",
        title="Aciclovir IV population execution",
        question_of_interest="Population-linked PBPK execution through verified OSP batching.",
        population=PopulationSpec(
            id="aciclovir-iv-population", size=population_count, seed=0, generator_version="0.1.0"
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
