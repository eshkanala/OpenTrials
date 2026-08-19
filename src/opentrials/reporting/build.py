"""Assemble a ``ReportData`` purely from independently re-verified artifacts on disk.

Deliberately does not trust anything the SDK or a previous process claimed
about a run: every artifact ID this module needs is re-derived from the run
directory's own name using the same deterministic naming convention
``orchestration.population_execution``/``orchestration.trial_execution``
already use (confirmed by reading their source, not assumed), and every
value placed into ``ReportData`` comes from a store's own ``verify_*()``
call. Nothing here recomputes PK endpoints, comparisons, or a scientific
conclusion -- it reads what verified artifacts already contain.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from opentrials.core.serialization import SchemaDocument
from opentrials.models.registry import ModelCapabilityRegistry
from opentrials.reporting.data import (
    ArmSummarySection,
    ConcentrationTimeSeries,
    EndpointSummaryRow,
    ExecutionVerificationRow,
    ModelSummarySection,
    ObservationScheduleSection,
    PairwiseComparisonRow,
    PopulationSummarySection,
    ProvenanceSection,
    ReportData,
    ReportHeader,
)
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.arm_comparison_artifacts import ArmComparisonArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.results import ResultArtifactStore
from opentrials.storage.trial_run import TrialRunArtifactStore

_STANDARD_LIMITATIONS = (
    "This is a computational simulation result, not a clinical or diagnostic finding.",
    "OpenTrials is for research and educational use only.",
)


def build_trial_report(
    run_directory: str | Path,
    population_root: str | Path,
    *,
    registry: ModelCapabilityRegistry | None = None,
) -> ReportData:
    """Build a report for a multi-arm trial run, re-verifying the whole chain.

    The registered model is resolved from the manifest's own ``model_id``
    (never a caller-supplied guess), then cross-checked against
    ``model_sha256`` -- the registered profile's declared artifact hash
    must match what the manifest recorded as actually executed.
    """
    from opentrials.sdk.registry import default_model_registry

    registry = registry if registry is not None else default_model_registry()
    run_directory = Path(run_directory)
    population_root = Path(population_root)
    run_id = run_directory.name
    trial_run_id = f"OTTRIAL-{run_id.removeprefix('OTR-')}"
    comparison_id = f"OTACMP-{run_id.removeprefix('OTR-')}"

    trial_run_store = TrialRunArtifactStore(run_directory / "trial_run")
    discovered = trial_run_store.read_manifest(trial_run_id)
    arm_ids = tuple(arm.arm_id for arm in discovered.arms)

    population_store = PopulationArtifactStore(population_root)
    allocation_store = TrialArmAllocationArtifactStore(
        run_directory / "allocation", population_store=population_store
    )
    comparison_store = ArmComparisonArtifactStore(run_directory / "comparison")
    endpoint_stores = {
        arm_id: PkEndpointArtifactStore(run_directory / "arms" / arm_id / "endpoints")
        for arm_id in arm_ids
    }

    manifest = trial_run_store.verify_trial_run(
        trial_run_id,
        population_store=population_store,
        allocation_store=allocation_store,
        endpoint_stores=endpoint_stores,
        comparison_store=comparison_store,
    )
    population_manifest = population_store.verify_population(manifest.source_generation_id)
    comparison_manifest = comparison_store.verify_comparison(comparison_id)

    model_capability_profile = registry.get(manifest.model_id)
    if model_capability_profile.package.artifact_hash != manifest.model_sha256:
        raise ValueError(
            f"Registered model {manifest.model_id!r}'s artifact hash does not match the "
            "hash this run actually executed against -- the registry may have changed "
            "since this run was produced."
        )

    arms: list[ArmSummarySection] = []
    execution_verification: list[ExecutionVerificationRow] = []
    concentration_time_series: list[ConcentrationTimeSeries] = []
    for arm_record in manifest.arms:
        arm_directory = run_directory / "arms" / arm_record.arm_id
        result_store = ResultArtifactStore(arm_directory / "normalized")
        result_manifest = result_store.verify_result(arm_record.result_id)
        rows = _read_parquet_rows(
            arm_directory
            / "normalized"
            / arm_record.result_id
            / result_manifest.concentration_time.path
        )
        arms.append(
            ArmSummarySection(
                arm_id=arm_record.arm_id,
                dose_amount=arm_record.requested_dose_mg,
                dose_unit="mg",
                route="INTRAVENOUS",
                participant_count=arm_record.participant_count,
            )
        )
        concentration_time_series.append(
            _mean_concentration_time_series(arm_record.arm_id, rows)
        )
        execution_verification.append(
            _execution_verification_row(
                arm_record.arm_id,
                arm_directory / "raw" / "osp_response.json",
                expected_sha256=result_manifest.source_raw_result_sha256,
            )
        )

    endpoints = tuple(
        EndpointSummaryRow(
            arm_id=_row_str(row, "arm_id"),
            endpoint_type=_row_str(row, "endpoint_type"),
            unit=_row_str(row, "unit"),
            n=_row_int(row, "n"),
            mean=_row_float(row, "mean"),
            sample_standard_deviation=_row_optional_float(row, "sample_standard_deviation"),
            coefficient_of_variation=_row_optional_float(row, "coefficient_of_variation"),
            minimum=_row_float(row, "minimum"),
            maximum=_row_float(row, "maximum"),
            p25=_row_float(row, "p25"),
            p50=_row_float(row, "p50"),
            p75=_row_float(row, "p75"),
        )
        for row in _read_parquet_rows(
            run_directory / "comparison" / comparison_id / comparison_manifest.arm_summaries.path
        )
    )
    comparisons = tuple(
        PairwiseComparisonRow(
            arm_a_id=_row_str(row, "arm_a_id"),
            arm_b_id=_row_str(row, "arm_b_id"),
            endpoint_type=_row_str(row, "endpoint_type"),
            unit=_row_str(row, "unit"),
            arm_a_mean=_row_float(row, "arm_a_mean"),
            arm_b_mean=_row_float(row, "arm_b_mean"),
            absolute_difference=_row_float(row, "absolute_difference"),
            relative_difference=_row_optional_float(row, "relative_difference"),
        )
        for row in _read_parquet_rows(
            run_directory
            / "comparison"
            / comparison_id
            / comparison_manifest.pairwise_comparisons.path
        )
        if comparison_manifest.pairwise_comparisons.rows > 0
    )

    limitations: tuple[str, ...] = (*_STANDARD_LIMITATIONS, comparison_manifest.interpretation_note)
    if manifest.observation_schedule is None:
        limitations = (
            *limitations,
            "No observation schedule was declared; the solver's default output grid was used.",
        )

    return ReportData(
        header=ReportHeader(
            report_type="trial",
            run_id=run_id,
            title=manifest.trial_id,
            trial_id=manifest.trial_id,
            generated_at=datetime.now(UTC),
        ),
        model=ModelSummarySection(
            model_id=model_capability_profile.package.manifest.id,
            engine=model_capability_profile.package.manifest.engine,
            version=model_capability_profile.package.manifest.version,
            artifact_hash=model_capability_profile.package.artifact_hash,
        ),
        population=PopulationSummarySection(
            generation_id=manifest.source_generation_id,
            participant_count=population_manifest.actual_count,
            reference_population=population_manifest.generator.population_model,
            requested_seed=population_manifest.generation.requested_seed,
            determinism_level=population_manifest.generation.determinism_level,
        ),
        arms=tuple(arms),
        observation_schedule=(
            ObservationScheduleSection(
                schedule_id=manifest.observation_schedule.schedule_id,
                declared_times_min=manifest.observation_schedule.declared_times_min,
            )
            if manifest.observation_schedule is not None
            else None
        ),
        endpoints=endpoints,
        comparisons=comparisons,
        concentration_time_series=tuple(concentration_time_series),
        execution_verification=tuple(execution_verification),
        provenance=ProvenanceSection(
            model_sha256=manifest.model_sha256,
            population_generation_id=manifest.source_generation_id,
            population_semantic_sha256=manifest.source_population_semantic_sha256,
            trial_sha256=manifest.trial_sha256,
            allocation_id=manifest.allocation_id,
            allocation_semantic_sha256=manifest.allocation_semantic_sha256,
            comparison_id=manifest.comparison_id,
            comparison_semantic_sha256=manifest.comparison_semantic_sha256,
            software_versions=manifest.software_versions,
            created_at=manifest.created_at,
        ),
        limitations=limitations,
        reproducibility=_reproducibility_lines(run_directory, population_root, kind="trial"),
        source_run_directory=run_directory,
        source_population_root=population_root,
    )


def build_population_report(
    run_directory: str | Path,
    population_root: str | Path,
    *,
    registry: ModelCapabilityRegistry | None = None,
) -> ReportData:
    """Build a report for a single-dose, whole-population run, re-verifying the chain.

    The registered model is resolved from the persisted result artifact's
    own ``model_id`` (never a caller-supplied guess), then cross-checked
    against the actual bundled model referenced there.
    """
    from opentrials.analysis.descriptive import calculate_descriptive_summary
    from opentrials.sdk.registry import default_model_registry

    registry = registry if registry is not None else default_model_registry()
    run_directory = Path(run_directory)
    population_root = Path(population_root)
    run_id = run_directory.name
    result_id = f"OTRES-{run_id.removeprefix('OTR-')}"
    endpoint_id = f"OTPK-{run_id.removeprefix('OTR-')}"

    population_store = PopulationArtifactStore(population_root)
    endpoint_store = PkEndpointArtifactStore(run_directory / "endpoints")
    endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
    if endpoint_manifest.source_generation_id is None:
        raise ValueError(
            "Population run endpoint artifact is missing its source population lineage."
        )
    population_manifest = population_store.verify_population(
        endpoint_manifest.source_generation_id
    )

    result_store = ResultArtifactStore(run_directory / "normalized")
    result_manifest = result_store.verify_result(result_id)
    concentration_rows = _read_parquet_rows(
        run_directory / "normalized" / result_id / result_manifest.concentration_time.path
    )
    endpoint_rows = endpoint_store.read_rows(endpoint_id)

    model_capability_profile = registry.get(result_manifest.model_id)
    if model_capability_profile.package.manifest.id != result_manifest.model_id:
        raise ValueError(
            f"Registered model {result_manifest.model_id!r} does not match the model "
            "this run actually executed against."
        )
    top_manifest = _read_top_manifest(run_directory)
    dose_mg = float(top_manifest["dose_mg"])

    by_type: dict[str, list[float]] = {}
    for row in endpoint_rows:
        by_type.setdefault(_row_str(row, "endpoint_type"), []).append(_row_float(row, "value"))
    unit_by_type = {str(row["endpoint_type"]): str(row["unit"]) for row in endpoint_rows}
    endpoints = tuple(
        _endpoint_summary_from_values(
            arm_id=None,
            endpoint_type=endpoint_type,
            unit=unit_by_type[endpoint_type],
            values=values,
            summarize=calculate_descriptive_summary,
        )
        for endpoint_type, values in sorted(by_type.items())
    )

    execution_verification = (
        _execution_verification_row(
            None,
            run_directory / "raw" / "osp_response.json",
            expected_sha256=result_manifest.source_raw_result_sha256,
        ),
    )

    return ReportData(
        header=ReportHeader(
            report_type="population",
            run_id=run_id,
            title=f"Population dose run ({dose_mg:g} mg)",
            trial_id=None,
            generated_at=datetime.now(UTC),
        ),
        model=ModelSummarySection(
            model_id=model_capability_profile.package.manifest.id,
            engine=model_capability_profile.package.manifest.engine,
            version=model_capability_profile.package.manifest.version,
            artifact_hash=model_capability_profile.package.artifact_hash,
        ),
        population=PopulationSummarySection(
            generation_id=population_manifest.generation_id,
            participant_count=population_manifest.actual_count,
            reference_population=population_manifest.generator.population_model,
            requested_seed=population_manifest.generation.requested_seed,
            determinism_level=population_manifest.generation.determinism_level,
        ),
        arms=(
            ArmSummarySection(
                arm_id="population",
                dose_amount=dose_mg,
                dose_unit="mg",
                route="INTRAVENOUS",
                participant_count=population_manifest.actual_count,
            ),
        ),
        observation_schedule=None,
        endpoints=endpoints,
        comparisons=(),
        concentration_time_series=(
            _mean_concentration_time_series("population", concentration_rows),
        ),
        execution_verification=execution_verification,
        provenance=ProvenanceSection(
            model_sha256=model_capability_profile.package.artifact_hash,
            population_generation_id=population_manifest.generation_id,
            population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
        ),
        limitations=(
            *_STANDARD_LIMITATIONS,
            "No observation schedule was declared; the solver's default output grid was used.",
        ),
        reproducibility=_reproducibility_lines(run_directory, population_root, kind="population"),
        source_run_directory=run_directory,
        source_population_root=population_root,
    )


def _endpoint_summary_from_values(
    *, arm_id: str | None, endpoint_type: str, unit: str, values: list[float], summarize: Any
) -> EndpointSummaryRow:
    summary = summarize(values)
    return EndpointSummaryRow(
        arm_id=arm_id,
        endpoint_type=endpoint_type,
        unit=unit,
        n=summary.n,
        mean=summary.mean,
        sample_standard_deviation=summary.sample_standard_deviation,
        coefficient_of_variation=summary.coefficient_of_variation,
        minimum=summary.minimum,
        maximum=summary.maximum,
        p25=summary.p25,
        p50=summary.p50,
        p75=summary.p75,
    )


def _read_top_manifest(run_directory: Path) -> dict[str, Any]:
    """Read the top-level run manifest's own payload (not independently re-verified --
    only used here for the one field, ``dose_mg``, no other artifact carries)."""
    parsed: Any = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    envelope = SchemaDocument.model_validate(parsed)
    return dict(envelope.payload)


def _mean_concentration_time_series(
    label: str, rows: tuple[dict[str, object], ...]
) -> ConcentrationTimeSeries:
    by_time: dict[float, list[float]] = {}
    for row in rows:
        by_time.setdefault(_row_float(row, "time"), []).append(_row_float(row, "value"))
    points = tuple(
        (time, sum(values) / len(values)) for time, values in sorted(by_time.items())
    )
    return ConcentrationTimeSeries(
        label=label,
        time_unit=str(rows[0]["time_unit"]),
        unit=str(rows[0]["unit"]),
        points=points,
    )


def _row_str(row: dict[str, object], key: str) -> str:
    return str(row[key])


def _row_int(row: dict[str, object], key: str) -> int:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric value for column {key!r}, got {value!r}.")
    return int(value)


def _row_float(row: dict[str, object], key: str) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric value for column {key!r}, got {value!r}.")
    return float(value)


def _row_optional_float(row: dict[str, object], key: str) -> float | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric value for column {key!r}, got {value!r}.")
    return float(value)


def _read_parquet_rows(path: Path) -> tuple[dict[str, object], ...]:
    table = pq.read_table(path)
    return tuple(dict(row) for row in table.to_pylist())


def _execution_verification_row(
    arm_id: str | None, raw_response_path: Path, *, expected_sha256: str
) -> ExecutionVerificationRow:
    parsed: Any = json.loads(raw_response_path.read_text(encoding="utf-8"))
    envelope = SchemaDocument.model_validate(parsed)
    if envelope.sha256() != expected_sha256:
        raise ValueError(f"Raw OSP response hash does not match its manifest: {raw_response_path}")
    inner_payload = envelope.payload.get("payload")
    if not isinstance(inner_payload, dict):
        raise ValueError(f"Raw OSP response is missing its inner payload: {raw_response_path}")
    verification = inner_payload.get("execution_verification")
    if not isinstance(verification, dict):
        raise ValueError(f"Raw OSP response is missing execution_verification: {raw_response_path}")
    model_hash = verification.get("model_hash_verification", {})
    route = verification.get("route_container_verification", {})
    model_hash_verified = (
        bool(model_hash.get("verified")) if isinstance(model_hash, dict) else False
    )
    route_verified = bool(route.get("verified")) if isinstance(route, dict) else False
    return ExecutionVerificationRow(
        arm_id=arm_id,
        model_hash_verified=model_hash_verified,
        route_container_verified=route_verified,
        solver_executed=bool(verification.get("solver_executed")),
    )


def _reproducibility_lines(
    run_directory: Path, population_root: Path, *, kind: str
) -> tuple[str, ...]:
    return (
        f"Run directory: {run_directory}",
        f"Population root: {population_root}",
        f"Re-verify this run: opentrials report {run_directory} "
        f"--population-root {population_root}",
        f"Report kind: {kind}",
    )
