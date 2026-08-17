"""Contract tests for persisted OTSENS sensitivity analyses."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.adapters.osp import ACICLOVIR_IV_MODEL_SHA256, OspParameterAssignment
from opentrials.orchestration import (
    analyze_verified_uncertainty_execution,
    run_aciclovir_iv_dose_uncertainty,
    run_aciclovir_iv_multi_dose_sensitivity_demo,
)
from opentrials.orchestration.uncertainty_dose import TOTAL_PLASMA_PATH
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    ENGINEERING_DEMONSTRATION_INTERPRETATION,
    UncertaintyDrawArtifactStore,
    UncertaintySensitivityArtifactStore,
)
from opentrials.uncertainty.contracts import SamplingMethod
from opentrials.uncertainty.execution import (
    MaterializedParameterValue,
    MaterializedUncertaintyDraw,
    MaterializedUncertaintyDrawSet,
)


def _persisted_draws(root: Path) -> str:
    draws = MaterializedUncertaintyDrawSet(
        scenario_id="OTUSC-sensitivity-source",
        scenario_canonical_sha256="sha256:" + "a" * 64,
        requested_seed=7,
        materializer_seed=7,
        method=SamplingMethod.MONTE_CARLO,
        draws=tuple(
            MaterializedUncertaintyDraw(
                draw_index=index,
                assignments=(
                    MaterializedParameterValue(
                        parameter_id="dose",
                        target="intervention.aciclovir_iv.dose",
                        value=dose,
                        unit="mg",
                    ),
                ),
            )
            for index, dose in enumerate((75.0, 125.0, 175.0, 250.0))
        ),
    )
    store = UncertaintyDrawArtifactStore(root)
    artifact_id = "OTUDR-sensitivity-source"
    store.create_draw_artifact(artifact_id)
    store.write_draws(artifact_id, draws)
    return artifact_id


def _fake_execution(
    *, run_id: str, assignment: OspParameterAssignment, **_: object
) -> RawSimulationResult:
    dose = assignment.value
    return RawSimulationResult(
        run_id=run_id,
        engine_id="osp",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True, "executed": {"value": dose}}],
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
                    "simulationValues": dose * 1_000_000,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                },
            ],
        },
    )


def _execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    draw_id = _persisted_draws(tmp_path / "draws")
    monkeypatch.setattr(
        "opentrials.orchestration.uncertainty_dose._execute_osp_engine", _fake_execution
    )
    return run_aciclovir_iv_dose_uncertainty(
        draw_id,
        draw_artifact_root=tmp_path / "draws",
        output_root=tmp_path / "executions",
        target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        r_libs_user="/not-used",
    )


def test_otsens_uses_only_verified_otuex_rows_and_is_reloadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution = _execution(tmp_path, monkeypatch)

    analysis = analyze_verified_uncertainty_execution(
        execution.execution_id,
        execution_artifact_root=tmp_path / "executions",
        output_root=tmp_path / "sensitivities",
    )

    assert analysis.manifest.source_execution_id == execution.execution_id
    assert (
        analysis.manifest.source_execution_semantic_sha256
        == execution.manifest.executions.semantic_content_sha256
    )
    assert analysis.manifest.interpretation == ENGINEERING_DEMONSTRATION_INTERPRETATION
    assert (
        UncertaintySensitivityArtifactStore(tmp_path / "sensitivities").verify_sensitivity(
            analysis.sensitivity_id
        )
        == analysis.manifest
    )
    rows = pq.read_table(analysis.sensitivity_directory / "sensitivities.parquet").to_pylist()
    assert [(row["output_id"], row["rank"]) for row in rows] == [
        ("auc_0_last", 1),
        ("cmax", 1),
    ]
    assert {row["input_id"] for row in rows} == {"dose"}
    assert all(row["correlation"] == pytest.approx(1.0) for row in rows)


def test_otsens_rejects_tampered_otuex_before_reading_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution = _execution(tmp_path, monkeypatch)
    parquet_path = execution.execution_directory / "executions.parquet"
    table = pq.read_table(parquet_path)
    pq.write_table(table, parquet_path, compression="snappy")

    with pytest.raises(ValueError, match="file hash"):
        analyze_verified_uncertainty_execution(
            execution.execution_id,
            execution_artifact_root=tmp_path / "executions",
            output_root=tmp_path / "sensitivities",
        )
    assert not (tmp_path / "sensitivities").exists()


def test_multi_dose_demo_persists_otus_to_otudr_to_otuex_to_otsens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "opentrials.orchestration.uncertainty_dose._execute_osp_engine", _fake_execution
    )

    demo = run_aciclovir_iv_multi_dose_sensitivity_demo(
        output_root=tmp_path / "demo", r_libs_user="/not-used"
    )

    scenario = demo.scenario_id
    draws = UncertaintyDrawArtifactStore(tmp_path / "demo" / "draws").verify_draw_artifact(
        demo.draw_artifact_id
    )
    assert scenario == draws.draws.scenario_id
    assert len(draws.draws.draws) == 8
    assert demo.execution.manifest.executions.rows == 8
    assert demo.sensitivity.manifest.source_execution_id == demo.execution.execution_id
    assert demo.sensitivity.manifest.interpretation == ENGINEERING_DEMONSTRATION_INTERPRETATION
