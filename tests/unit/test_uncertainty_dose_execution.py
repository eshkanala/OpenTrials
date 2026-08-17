"""Contract tests for persisted, verified dose-only uncertainty execution."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.adapters.osp import ACICLOVIR_IV_MODEL_SHA256, OspParameterAssignment
from opentrials.orchestration import run_aciclovir_iv_dose_uncertainty
from opentrials.orchestration.uncertainty_dose import TOTAL_PLASMA_PATH
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    UncertaintyDrawArtifactStore,
    UncertaintyExecutionArtifactStore,
)
from opentrials.uncertainty.contracts import SamplingMethod
from opentrials.uncertainty.execution import (
    MaterializedParameterValue,
    MaterializedUncertaintyDraw,
    MaterializedUncertaintyDrawSet,
)


def persisted_draws(root: Path, *, target: str = "intervention.aciclovir_iv.dose") -> str:
    draws = MaterializedUncertaintyDrawSet(
        scenario_id="OTUSC-dose-execution",
        scenario_canonical_sha256="sha256:" + "a" * 64,
        requested_seed=7,
        materializer_seed=7,
        method=SamplingMethod.MONTE_CARLO,
        draws=(
            MaterializedUncertaintyDraw(
                draw_index=0,
                assignments=(
                    MaterializedParameterValue(
                        parameter_id="dose", target=target, value=125.0, unit="mg"
                    ),
                ),
            ),
            MaterializedUncertaintyDraw(
                draw_index=1,
                assignments=(
                    MaterializedParameterValue(
                        parameter_id="dose", target=target, value=250.0, unit="mg"
                    ),
                ),
            ),
        ),
    )
    store = UncertaintyDrawArtifactStore(root)
    artifact_id = "OTUDR-dose-execution"
    store.create_draw_artifact(artifact_id)
    store.write_draws(artifact_id, draws)
    return artifact_id


def fake_execution(
    *, run_id: str, assignment: OspParameterAssignment, **_: object
) -> RawSimulationResult:
    value = assignment.value
    concentration = value * 1_000_000
    return RawSimulationResult(
        run_id=run_id,
        engine_id="osp",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True, "executed": {"value": value}}],
            },
            "raw_result_rows": [
                {
                    "IndividualId": 1,
                    "Time": 0,
                    "simulationValues": 0.0,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                },
                {
                    "IndividualId": 1,
                    "Time": 60,
                    "simulationValues": concentration,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                },
            ],
        },
    )


def test_persisted_draws_execute_as_isolated_verified_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draw_root = tmp_path / "draws"
    draw_id = persisted_draws(draw_root)
    monkeypatch.setattr(
        "opentrials.orchestration.uncertainty_dose._execute_osp_engine", fake_execution
    )

    execution = run_aciclovir_iv_dose_uncertainty(
        draw_id,
        draw_artifact_root=draw_root,
        output_root=tmp_path / "executions",
        target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        r_libs_user="/not-used",
    )

    assert execution.manifest.source_draw_artifact_id == draw_id
    assert execution.manifest.executions.rows == 2
    reloaded = UncertaintyExecutionArtifactStore(tmp_path / "executions").verify_execution(
        execution.execution_id
    )
    assert reloaded == execution.manifest
    import pyarrow.parquet as pq

    rows = pq.read_table(execution.execution_directory / "executions.parquet").to_pylist()
    assert [row["draw_id"] for row in rows] == ["DRAW-000001", "DRAW-000002"]
    assert [row["requested_value"] for row in rows] == [125.0, 250.0]
    assert [row["executed_value"] for row in rows] == [0.000125, 0.00025]
    assert [row["verification_status"] for row in rows] == ["VERIFIED", "VERIFIED"]
    assert rows[0]["cmax"] != rows[1]["cmax"]
    for row in rows:
        child = execution.execution_directory / "children" / row["child_run_id"]
        assert (child / "raw" / "osp_response.json").is_file()
        assert (child / "normalized" / row["result_id"] / "concentration_time.parquet").is_file()
        assert (child / "endpoints" / row["endpoint_id"] / "endpoints.parquet").is_file()


def test_wrong_model_hash_is_rejected_before_worker(tmp_path: Path) -> None:
    draw_root = tmp_path / "draws"
    draw_id = persisted_draws(draw_root)
    with pytest.raises(ValueError, match="Target model hash"):
        run_aciclovir_iv_dose_uncertainty(
            draw_id,
            draw_artifact_root=draw_root,
            output_root=tmp_path / "executions",
            target_model_sha256="sha256:" + "b" * 64,
            r_libs_user="/not-used",
        )
    assert not (tmp_path / "executions").exists()


def test_unsupported_target_is_rejected_before_execution(tmp_path: Path) -> None:
    draw_root = tmp_path / "draws"
    draw_id = persisted_draws(draw_root, target="population.weight")
    with pytest.raises(ValueError, match="No verified OSP execution mapping"):
        run_aciclovir_iv_dose_uncertainty(
            draw_id,
            draw_artifact_root=draw_root,
            output_root=tmp_path / "executions",
            target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
            r_libs_user="/not-used",
        )
    assert not (tmp_path / "executions").exists()
