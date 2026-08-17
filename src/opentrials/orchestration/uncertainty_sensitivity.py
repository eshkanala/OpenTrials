"""OTSENS analysis and engineering demonstration from verified OTUEX artifacts."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp import ACICLOVIR_IV_MODEL_SHA256
from opentrials.analysis import (
    SensitivityInput,
    SensitivityOutput,
    calculate_pearson_sensitivities,
)
from opentrials.core import Distribution, DistributionPurpose, DistributionType
from opentrials.core.serialization import sha256
from opentrials.orchestration.uncertainty_dose import (
    DoseUncertaintyExecution,
    run_aciclovir_iv_dose_uncertainty,
)
from opentrials.storage import (
    UNCERTAINTY_EXECUTION_COLUMNS,
    UncertaintyDrawArtifactStore,
    UncertaintyExecutionArtifactStore,
    UncertaintyScenarioArtifactStore,
)
from opentrials.storage.uncertainty_sensitivity import (
    UncertaintySensitivityArtifactManifest,
    UncertaintySensitivityArtifactStore,
)
from opentrials.uncertainty import (
    SamplingMethod,
    UncertainParameter,
    UncertaintySamplingPlan,
    UncertaintyScenario,
    materialize_uncertainty_draws,
)


class UncertaintySensitivityAnalysis(BaseModel):
    """Locations and manifest for a completed immutable OTSENS analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sensitivity_id: str = Field(pattern=r"^OTSENS-[A-Za-z0-9_-]+$")
    sensitivity_directory: Path
    manifest: UncertaintySensitivityArtifactManifest


class DoseSensitivityEngineeringDemo(BaseModel):
    """The persisted artifact chain for the multi-dose engineering demonstration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(pattern=r"^OTUSC-[A-Za-z0-9_-]+$")
    draw_artifact_id: str = Field(pattern=r"^OTUDR-[A-Za-z0-9_-]+$")
    execution: DoseUncertaintyExecution
    sensitivity: UncertaintySensitivityAnalysis


def analyze_verified_uncertainty_execution(
    execution_id: str,
    *,
    execution_artifact_root: Path,
    output_root: Path,
) -> UncertaintySensitivityAnalysis:
    """Calculate persisted Pearson sensitivities from one verified OTUEX artifact.

    The only inputs accepted here are an OTUEX identifier and its artifact root.
    Values are reloaded from its hash-verified Parquet index, rather than accepted
    as caller-supplied arrays. The current OTUEX contract has one verified dose
    assignment per draw, which makes every endpoint vector unambiguously aligned.
    """
    execution_store = UncertaintyExecutionArtifactStore(execution_artifact_root)
    execution_manifest = execution_store.verify_execution(execution_id)
    execution_path = execution_artifact_root / execution_id / execution_manifest.executions.path
    table = pq.read_table(execution_path)
    if tuple(table.column_names) != UNCERTAINTY_EXECUTION_COLUMNS:
        raise ValueError("Verified OTUEX has an unexpected execution table schema.")
    rows = tuple(dict(row) for row in table.to_pylist())
    aligned_rows = tuple(sorted(rows, key=_draw_index))
    input_id, input_target, input_unit, input_values = _aligned_verified_dose_input(aligned_rows)
    outputs = (
        SensitivityOutput(output_id="cmax", values=_numeric_column(aligned_rows, "cmax")),
        SensitivityOutput(
            output_id="auc_0_last", values=_numeric_column(aligned_rows, "auc_0_last")
        ),
    )
    results = calculate_pearson_sensitivities(
        (SensitivityInput(input_id=input_id, values=input_values),), outputs
    )
    result_rows = _ranked_rows(results, input_target=input_target, input_unit=input_unit)

    sensitivity_id = f"OTSENS-{execution_id.removeprefix('OTUEX-')}-{uuid.uuid4().hex}"
    sensitivity_store = UncertaintySensitivityArtifactStore(output_root)
    sensitivity_directory = sensitivity_store.create_sensitivity(sensitivity_id)
    manifest = sensitivity_store.write_sensitivities(
        sensitivity_id,
        source_execution_id=execution_id,
        source_execution_manifest_canonical_sha256=sha256(execution_manifest),
        source_execution_file_sha256=execution_manifest.executions.file_sha256,
        source_execution_semantic_sha256=execution_manifest.executions.semantic_content_sha256,
        source_draw_artifact_id=execution_manifest.source_draw_artifact_id,
        source_draws_canonical_sha256=execution_manifest.source_draws_canonical_sha256,
        source_draw_table_semantic_sha256=execution_manifest.source_draw_table_semantic_sha256,
        target_model_sha256=execution_manifest.target_model_sha256,
        model_id=execution_manifest.model_id,
        rows=result_rows,
    )
    sensitivity_store.verify_sensitivity(sensitivity_id)
    return UncertaintySensitivityAnalysis(
        sensitivity_id=sensitivity_id,
        sensitivity_directory=sensitivity_directory,
        manifest=manifest,
    )


def run_aciclovir_iv_multi_dose_sensitivity_demo(
    *, output_root: Path, r_libs_user: str
) -> DoseSensitivityEngineeringDemo:
    """Run the declared 8-draw empirical dose engineering demonstration.

    This deliberately uses the uncertainty artifact chain to demonstrate the
    implementation. Its dose distribution is not evidence of biological or
    parameter uncertainty; OTSENS records that limitation in every manifest.
    """
    token = uuid.uuid4().hex
    scenario_id = f"OTUSC-aciclovir-iv-dose-demo-{token}"
    scenario = UncertaintyScenario(
        scenario_id=scenario_id,
        target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        parameters=(
            UncertainParameter(
                parameter_id="intervention_dose",
                target="intervention.aciclovir_iv.dose",
                distribution=Distribution(
                    distribution_type=DistributionType.EMPIRICAL,
                    purpose=DistributionPurpose.PARAMETER_UNCERTAINTY,
                    unit="mg",
                    values=(75.0, 100.0, 125.0, 150.0, 175.0, 200.0, 225.0, 250.0),
                    description=(
                        "Declared engineering perturbation doses; not biological uncertainty."
                    ),
                ),
                evidence_ids=("engineering-demo-dose-grid",),
                provenance_ids=("engineering-demo-declaration",),
            ),
        ),
        sampling=UncertaintySamplingPlan(
            method=SamplingMethod.MONTE_CARLO, requested_draw_count=8, requested_seed=20260317
        ),
        evidence_ids=("engineering-demo-dose-grid",),
        provenance_ids=("engineering-demo-declaration",),
        assumptions=(
            "Intervention dose is a verified engineering perturbation variable, "
            "not genuine biological or parameter uncertainty.",
        ),
    )
    scenario_store = UncertaintyScenarioArtifactStore(output_root / "scenarios")
    scenario_store.create_uncertainty_scenario(scenario_id)
    scenario_store.write_uncertainty_scenario(scenario)
    scenario_store.verify_uncertainty_scenario(scenario_id)

    draws = materialize_uncertainty_draws(scenario)
    draw_id = f"OTUDR-aciclovir-iv-dose-demo-{token}"
    draw_store = UncertaintyDrawArtifactStore(output_root / "draws")
    draw_store.create_draw_artifact(draw_id)
    draw_store.write_draws(draw_id, draws)
    draw_store.verify_draw_artifact(draw_id)

    execution = run_aciclovir_iv_dose_uncertainty(
        draw_id,
        draw_artifact_root=output_root / "draws",
        output_root=output_root / "executions",
        target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        r_libs_user=r_libs_user,
    )
    sensitivity = analyze_verified_uncertainty_execution(
        execution.execution_id,
        execution_artifact_root=output_root / "executions",
        output_root=output_root / "sensitivities",
    )
    return DoseSensitivityEngineeringDemo(
        scenario_id=scenario_id,
        draw_artifact_id=draw_id,
        execution=execution,
        sensitivity=sensitivity,
    )


def _aligned_verified_dose_input(
    rows: Sequence[Mapping[str, object]],
) -> tuple[str, str, str, tuple[float, ...]]:
    if len(rows) < 2:
        raise ValueError("OTSENS requires at least two verified OTUEX execution rows.")
    ordered = tuple(sorted(rows, key=lambda row: _draw_index(row)))
    draw_indices = tuple(_draw_index(row) for row in ordered)
    if len(draw_indices) != len(set(draw_indices)):
        raise ValueError("OTSENS requires exactly one execution row for each draw index.")
    if any(row.get("verification_status") != "VERIFIED" for row in ordered):
        raise ValueError("OTSENS accepts only OTUEX rows with VERIFIED execution status.")
    identities = {
        (row.get("parameter_id"), row.get("parameter_target"), row.get("executed_unit"))
        for row in ordered
    }
    if len(identities) != 1:
        raise ValueError(
            "OTSENS requires one consistently identified verified input per OTUEX draw."
        )
    input_id, target, unit = identities.pop()
    if (
        not isinstance(input_id, str)
        or not input_id.strip()
        or not isinstance(target, str)
        or not target.strip()
        or not isinstance(unit, str)
        or not unit.strip()
    ):
        raise ValueError("OTSENS source OTUEX input identity is invalid.")
    return input_id, target, unit, _numeric_column(ordered, "executed_value")


def _draw_index(row: Mapping[str, object]) -> int:
    value = row.get("draw_index")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("OTSENS source OTUEX draw_index is invalid.")
    return value


def _numeric_column(rows: Sequence[Mapping[str, object]], column: str) -> tuple[float, ...]:
    values: list[float] = []
    for row in rows:
        value = row.get(column)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"OTSENS source OTUEX column {column!r} must contain numeric values.")
        values.append(float(value))
    return tuple(values)


def _ranked_rows(
    results: Sequence[object], *, input_target: str, input_unit: str
) -> tuple[dict[str, object], ...]:
    by_output: dict[str, list[tuple[str, float]]] = {}
    for result in results:
        input_id = getattr(result, "input_id")
        output_id = getattr(result, "output_id")
        correlation = getattr(result, "correlation")
        if (
            not isinstance(input_id, str)
            or not isinstance(output_id, str)
            or not isinstance(correlation, float)
        ):
            raise TypeError("Unexpected Pearson sensitivity result.")
        by_output.setdefault(output_id, []).append((input_id, correlation))
    rows: list[dict[str, object]] = []
    for output_id in sorted(by_output):
        for rank, (input_id, correlation) in enumerate(
            sorted(by_output[output_id], key=lambda item: (-abs(item[1]), item[0])), start=1
        ):
            rows.append(
                {
                    "rank": rank,
                    "input_id": input_id,
                    "input_target": input_target,
                    "input_unit": input_unit,
                    "output_id": output_id,
                    "correlation": correlation,
                    "absolute_correlation": abs(correlation),
                }
            )
    return tuple(rows)
