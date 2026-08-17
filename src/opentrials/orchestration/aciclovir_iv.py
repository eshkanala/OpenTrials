"""Reproducible single-subject Aciclovir IV engineering workflow.

This module deliberately owns one narrow, verified protocol rather than being a
second general-purpose simulation API.  Its external-worker boundary is kept in
``_execute_osp_engine`` so contract tests can replace it without requiring R.
"""

from __future__ import annotations

import platform
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp import (
    OspAdministrationTarget,
    OspCompoundMapping,
    OspInterventionProfile,
    OspInterventionTranslator,
    OspParameterAssignment,
    OspSimulationEngine,
)
from opentrials.analysis.pk import PkEndpointResult, calculate_pk_endpoints
from opentrials.compound.intervention import Route
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.results import (
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
)
from opentrials.trials.trial import Trial

DEMO_TRIAL_ID = "ACICLOVIR-IV-ENGINEERING-DEMO"
PKML_PATH = Path("/Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/Aciclovir.pkml")
PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"

ProgressCallback = Callable[[str], None]


class AciclovirIvEngineeringRun(BaseModel):
    """Locations and derived endpoint values from one immutable engineering run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(pattern=r"^OTR-[A-Za-z0-9_-]+$")
    run_directory: Path
    result_directory: Path
    endpoint_directory: Path
    endpoints: tuple[PkEndpointResult, ...] = Field(min_length=1)


def run_aciclovir_iv_engineering(
    trial: Trial,
    *,
    output_root: Path,
    r_libs_user: str,
    progress: ProgressCallback | None = None,
) -> AciclovirIvEngineeringRun:
    """Execute and persist the narrowly pinned Aciclovir IV engineering protocol.

    ``r_libs_user`` is supplied explicitly to avoid importing or probing R until
    the OSP worker is invoked.  Every persisted JSON object uses a canonical
    OpenTrials schema envelope.
    """
    _notify(progress, "validating_trial")
    intervention = _validate_trial(trial)
    package = _model_package()
    translation = OspInterventionTranslator(_intervention_profile()).translate(intervention)
    assert translation.plan is not None

    run_id = f"OTR-aciclovir-iv-{uuid.uuid4().hex}"
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    _write_document(run_directory / "trial.json", document("opentrials.trial", trial))

    _notify(progress, "preparing_engine")
    raw_result = _execute_osp_engine(
        run_id=run_id,
        trial=trial,
        package=package,
        assignments=translation.plan.assignments,
        r_libs_user=r_libs_user,
    )
    _verify_raw_result(raw_result, run_id)

    _notify(progress, "persisting_raw")
    raw_document = document("opentrials.osp-response", raw_result)
    raw_path = run_directory / "raw" / "osp_response.json"
    _write_document(raw_path, raw_document)
    raw_hash = raw_document.sha256()
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
    )
    endpoint_store.verify_endpoints(endpoint_id)

    _notify(progress, "writing_manifest")
    trial_document = document("opentrials.trial", trial)
    run_hash = sha256(
        {
            "trial_sha256": trial_document.sha256(),
            "model_package_sha256": sha256(package),
            "seed": trial.seed,
            "population_seed": trial.population.seed,
        }
    )
    manifest = document(
        "opentrials.aciclovir-iv-engineering-run",
        {
            "run_id": run_id,
            "run_sha256": run_hash,
            "trial_sha256": trial_document.sha256(),
            "model_sha256": package.artifact_hash,
            "raw_sha256": raw_hash,
            "result_artifact_semantic_sha256": (
                result_manifest.concentration_time.semantic_content_sha256
            ),
            "endpoint_semantic_sha256": endpoint_manifest.endpoints.semantic_content_sha256,
            "verification_evidence_sha256": verification_hash,
            "software_versions": _software_versions(r_libs_user),
            "seeds": {"trial": trial.seed, "population": trial.population.seed},
            "artifacts": {
                "trial": "trial.json",
                "raw_response": "raw/osp_response.json",
                "result": f"normalized/{result_id}",
                "endpoints": f"endpoints/{endpoint_id}",
            },
            "created_at": datetime.now(UTC),
        },
    )
    _write_document(run_directory / "manifest.json", manifest)
    _notify(progress, "completed")
    return AciclovirIvEngineeringRun(
        run_id=run_id,
        run_directory=run_directory,
        result_directory=result_directory,
        endpoint_directory=endpoint_directory,
        endpoints=endpoints,
    )


def _validate_trial(trial: Trial) -> Any:
    if trial.trial_id != DEMO_TRIAL_ID:
        raise ValueError(f"This workflow accepts only trial_id {DEMO_TRIAL_ID!r}.")
    if trial.population.size != 1:
        raise ValueError("This workflow accepts exactly one person.")
    if len(trial.arms) != 1:
        raise ValueError("This workflow accepts exactly one trial arm.")
    intervention = trial.arms[0].intervention
    if intervention.compound.identity.compound_id != "aciclovir":
        raise ValueError("This workflow accepts only an aciclovir intervention.")
    if len(intervention.regimen.doses) != 1:
        raise ValueError("This workflow accepts exactly one IV infusion.")
    dose = intervention.regimen.doses[0]
    if dose.route is not Route.INTRAVENOUS:
        raise ValueError("This workflow accepts only intravenous administration.")
    amount_mg = dose.amount.to("mg").value
    if amount_mg not in {125.0, 250.0}:
        raise ValueError("This workflow accepts only 125 mg or 250 mg infusions.")
    if dose.administration_time.to("min").value != 0.0:
        raise ValueError("This workflow requires administration at 0 min.")
    if dose.infusion_duration is None or dose.infusion_duration.to("min").value != 10.0:
        raise ValueError("This workflow requires a 10 min IV infusion.")
    return intervention


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


def _execute_osp_engine(
    *,
    run_id: str,
    trial: Trial,
    package: ModelPackage,
    assignments: tuple[OspParameterAssignment, ...],
    r_libs_user: str,
) -> RawSimulationResult:
    """Perform the external execution; kept separate as the unit-test seam."""
    engine = OspSimulationEngine(r_libs_user=r_libs_user)
    prepared = engine.prepare(run_id, (package,), trial)
    return engine.run(
        prepared,
        expected_pkml_sha256=PKML_SHA256,
        expected_administration_container=IV_CONTAINER,
        parameter_assignments=assignments,
    )


def _verify_raw_result(result: RawSimulationResult, expected_run_id: str) -> None:
    if result.run_id != expected_run_id or result.engine_id != "osp":
        raise ValueError("OSP execution result does not match the prepared run.")
    verification = result.payload.get("execution_verification")
    if not isinstance(verification, Mapping):
        raise ValueError("OSP execution did not provide verification evidence.")
    for key in ("model_hash_verification", "route_container_verification"):
        value = verification.get(key)
        if not isinstance(value, Mapping) or value.get("verified") is not True:
            raise ValueError(f"OSP execution verification failed for {key!r}.")
    if verification.get("solver_executed") is not True:
        raise ValueError("OSP execution verification did not confirm solver execution.")
    assignments = verification.get("parameter_assignments")
    if not isinstance(assignments, Sequence) or not assignments:
        raise ValueError("OSP execution verification has no parameter assignments.")
    if any(
        not isinstance(item, Mapping) or item.get("verified") is not True for item in assignments
    ):
        raise ValueError("OSP execution verification did not confirm every parameter assignment.")


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
