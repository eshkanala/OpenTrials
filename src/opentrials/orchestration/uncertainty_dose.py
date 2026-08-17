"""Verified, dose-only OSP execution for persisted uncertainty draws."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp import (
    ACICLOVIR_IV_MODEL_SHA256,
    OspSimulationEngine,
    resolve_aciclovir_iv_dose_uncertainty,
)
from opentrials.adapters.osp.intervention import OspParameterAssignment
from opentrials.analysis.pk import PkEndpointType, calculate_pk_endpoints
from opentrials.compound.compound import Compound, CompoundIdentity
from opentrials.compound.intervention import Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document, sha256
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.patient.population import PopulationSpec
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PkEndpointArtifactStore,
    ResultArtifactStore,
    ResultSelectionMapping,
    UncertaintyDrawArtifactStore,
)
from opentrials.storage.uncertainty_executions import (
    UncertaintyExecutionArtifactManifest,
    UncertaintyExecutionArtifactStore,
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
PKML_SHA256 = ACICLOVIR_IV_MODEL_SHA256.removeprefix("sha256:")
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"


class DoseUncertaintyExecution(BaseModel):
    """Locations and manifest for a completed immutable OTUEX execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str = Field(pattern=r"^OTUEX-[A-Za-z0-9_-]+$")
    execution_directory: Path
    manifest: UncertaintyExecutionArtifactManifest


def run_aciclovir_iv_dose_uncertainty(
    draw_artifact_id: str,
    *,
    draw_artifact_root: Path,
    output_root: Path,
    target_model_sha256: str,
    r_libs_user: str,
) -> DoseUncertaintyExecution:
    """Run every verified OTUDR draw in isolated OSP child executions.

    This is intentionally not a general uncertainty executor. It accepts exactly
    one mass-compatible assignment per draw and delegates target/model validation
    to the verified Aciclovir IV resolver before any OSP process is created.
    """
    draw_manifest = UncertaintyDrawArtifactStore(draw_artifact_root).verify_draw_artifact(
        draw_artifact_id
    )
    if target_model_sha256 != ACICLOVIR_IV_MODEL_SHA256:
        raise ValueError("Target model hash does not match the verified Aciclovir PKML.")

    resolved_draws = []
    for draw in draw_manifest.draws.draws:
        draw_id = f"DRAW-{draw.draw_index + 1:06d}"
        if len(draw.assignments) != 1:
            raise ValueError(
                "Dose-only uncertainty execution requires exactly one assignment per draw."
            )
        resolved_draws.append(
            (
                draw,
                resolve_aciclovir_iv_dose_uncertainty(
                    draw_id, draw.assignments[0], model_sha256=target_model_sha256
                ),
            )
        )

    execution_id = f"OTUEX-aciclovir-iv-dose-{uuid.uuid4().hex}"
    execution_store = UncertaintyExecutionArtifactStore(output_root)
    execution_directory = execution_store.create_execution(execution_id)
    index_rows: list[dict[str, object]] = []
    package = _model_package()
    for draw, resolved in resolved_draws:
        child_run_id = f"OTR-{execution_id.removeprefix('OTUEX-')}-draw-{draw.draw_index + 1:06d}"
        child_directory = execution_directory / "children" / child_run_id
        child_directory.mkdir(parents=True, exist_ok=False)
        raw_result = _execute_osp_engine(
            run_id=child_run_id,
            package=package,
            r_libs_user=r_libs_user,
            assignment=resolved.assignment,
        )
        _verify_raw_result(raw_result, child_run_id)
        raw_document = document("opentrials.osp-response", raw_result)
        raw_path = child_directory / "raw" / "osp_response.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw_document.canonical_json() + "\n", encoding="utf-8")

        selected_rows = _selected_raw_rows(raw_result.payload)
        result_id = f"OTRES-{child_run_id.removeprefix('OTR-')}"
        result_store = ResultArtifactStore(child_directory / "normalized")
        result_store.create_result(result_id)
        result_manifest = result_store.write_concentration_time(
            result_id,
            source_raw_result=raw_document,
            raw_rows=selected_rows,
            engine_id="osp",
            model_id=package.manifest.id,
            run_id=child_run_id,
            selection=_selection(),
        )
        result_store.verify_result(result_id)
        normalized_rows = _normalized_rows(selected_rows)
        endpoints = calculate_pk_endpoints(
            normalized_rows, result_manifest.concentration_time.semantic_content_sha256
        )
        endpoint_id = f"OTPK-{child_run_id.removeprefix('OTR-')}"
        endpoint_store = PkEndpointArtifactStore(child_directory / "endpoints")
        endpoint_store.create_endpoint_artifact(endpoint_id)
        endpoint_manifest = endpoint_store.write_endpoints(
            endpoint_id,
            endpoints=endpoints,
            source_result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
            source_result_id=result_id,
            run_id=child_run_id,
            source_engine_id="osp",
            source_model_id=package.manifest.id,
        )
        endpoint_store.verify_endpoints(endpoint_id)
        endpoint_values = {endpoint.endpoint_type: endpoint.value for endpoint in endpoints}
        verification = raw_result.payload["execution_verification"]
        assert isinstance(verification, Mapping)
        index_rows.append(
            {
                "draw_id": resolved.draw_id,
                "draw_index": draw.draw_index,
                "parameter_id": draw.assignments[0].parameter_id,
                "parameter_target": draw.assignments[0].target,
                "requested_value": resolved.requested.value,
                "requested_unit": resolved.requested.unit,
                "executed_value": resolved.assignment.value,
                "executed_unit": resolved.assignment.unit,
                "verification_status": "VERIFIED",
                "verification_evidence_sha256": sha256(verification),
                "child_run_id": child_run_id,
                "child_raw_sha256": raw_document.sha256(),
                "result_id": result_id,
                "result_semantic_sha256": (
                    result_manifest.concentration_time.semantic_content_sha256
                ),
                "endpoint_id": endpoint_id,
                "endpoint_semantic_sha256": endpoint_manifest.endpoints.semantic_content_sha256,
                "cmax": endpoint_values[PkEndpointType.CMAX],
                "tmax": endpoint_values[PkEndpointType.TMAX],
                "auc_0_last": endpoint_values[PkEndpointType.AUC_0_LAST],
            }
        )
    manifest = execution_store.write_execution_index(
        execution_id,
        source_draw_artifact_id=draw_artifact_id,
        source_draws_canonical_sha256=draw_manifest.draws_canonical_sha256,
        source_draw_table_semantic_sha256=draw_manifest.table.semantic_content_sha256,
        target_model_sha256=target_model_sha256,
        model_id=package.manifest.id,
        rows=index_rows,
    )
    execution_store.verify_execution(execution_id)
    return DoseUncertaintyExecution(
        execution_id=execution_id, execution_directory=execution_directory, manifest=manifest
    )


def _execute_osp_engine(
    *, run_id: str, package: ModelPackage, r_libs_user: str, assignment: OspParameterAssignment
) -> RawSimulationResult:
    """External worker seam retained for contract tests."""
    engine = OspSimulationEngine(r_libs_user=r_libs_user)
    prepared = engine.prepare(run_id, (package,), _execution_trial())
    return engine.run(
        prepared,
        expected_pkml_sha256=PKML_SHA256,
        expected_administration_container=IV_CONTAINER,
        parameter_assignments=(assignment,),
    )


def _verify_raw_result(result: RawSimulationResult, expected_run_id: str) -> None:
    if result.run_id != expected_run_id or result.engine_id != "osp":
        raise ValueError("OSP execution result does not match its uncertainty child run.")
    verification = result.payload.get("execution_verification")
    if not isinstance(verification, Mapping):
        raise ValueError("OSP execution did not provide verification evidence.")
    for key in ("model_hash_verification", "route_container_verification"):
        item = verification.get(key)
        if not isinstance(item, Mapping) or item.get("verified") is not True:
            raise ValueError(f"OSP execution verification failed for {key!r}.")
    assignments = verification.get("parameter_assignments")
    if (
        verification.get("solver_executed") is not True
        or not isinstance(assignments, Sequence)
        or len(assignments) != 1
        or not isinstance(assignments[0], Mapping)
        or assignments[0].get("verified") is not True
    ):
        raise ValueError("OSP execution did not verify the sole dose assignment and solver state.")


def _selected_raw_rows(payload: Mapping[str, Any]) -> tuple[Mapping[str, object], ...]:
    rows = payload.get("raw_result_rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("OSP response is missing raw_result_rows.")
    selected = tuple(
        row for row in rows if isinstance(row, Mapping) and row.get("paths") == TOTAL_PLASMA_PATH
    )
    if not selected:
        raise ValueError("OSP response has no rows for the verified total plasma output path.")
    return selected


def _selection() -> ResultSelectionMapping:
    return ResultSelectionMapping(
        source_path=TOTAL_PLASMA_PATH,
        analyte="aciclovir",
        matrix="peripheral venous plasma",
        fraction="total",
        measurement="concentration",
        time_unit="min",
    )


def _normalized_rows(rows: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    from opentrials.storage import normalize_osp_concentration_time_rows

    return normalize_osp_concentration_time_rows(rows, _selection())


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
        artifact_hash=ACICLOVIR_IV_MODEL_SHA256,
        parameter_set_id="vergin-1995-iv-as-packaged",
        parameter_hash=ACICLOVIR_IV_MODEL_SHA256,
        package_hash=ACICLOVIR_IV_MODEL_SHA256,
    )


def _execution_trial() -> Trial:
    def assumed(value: float, unit: str) -> ScientificValue:
        return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)

    intervention = Intervention(
        intervention_id="aciclovir-iv-uncertainty",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="single-iv-infusion",
            doses=(
                Dose(
                    amount=assumed(250, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                    infusion_duration=assumed(10, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="ACICLOVIR-IV-UNCERTAINTY-EXECUTION",
        title="Aciclovir IV uncertainty execution",
        question_of_interest="Dose uncertainty through verified OSP execution.",
        population=PopulationSpec(id="one-adult", size=1, seed=0, generator_version="0.1.0"),
        arms=(TrialArm(arm_id="iv", name="IV", intervention=intervention, allocation=1.0),),
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
