"""Opt-in proof that persisted dose draws drive distinct verified OSP children."""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.adapters.osp import ACICLOVIR_IV_MODEL_SHA256
from opentrials.orchestration import (
    run_aciclovir_iv_dose_uncertainty,
    run_aciclovir_iv_multi_dose_sensitivity_demo,
)
from opentrials.orchestration.uncertainty_dose import PKML_PATH
from opentrials.storage import UncertaintyDrawArtifactStore
from opentrials.uncertainty.contracts import SamplingMethod
from opentrials.uncertainty.execution import (
    MaterializedParameterValue,
    MaterializedUncertaintyDraw,
    MaterializedUncertaintyDrawSet,
)

pytestmark = pytest.mark.osp_integration


def test_persisted_125_and_250_mg_draws_produce_distinct_artifacts(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")
    if not PKML_PATH.is_file():
        pytest.skip(f"Bundled OSP aciclovir PKML is not available: {PKML_PATH}")

    draw_store = UncertaintyDrawArtifactStore(tmp_path / "draws")
    draw_id = "OTUDR-live-dose-125-250"
    draw_store.create_draw_artifact(draw_id)
    draw_store.write_draws(
        draw_id,
        MaterializedUncertaintyDrawSet(
            scenario_id="OTUSC-live-dose-125-250",
            scenario_canonical_sha256="sha256:" + "a" * 64,
            requested_seed=0,
            materializer_seed=0,
            method=SamplingMethod.MONTE_CARLO,
            draws=tuple(
                MaterializedUncertaintyDraw(
                    draw_index=index,
                    assignments=(
                        MaterializedParameterValue(
                            parameter_id="dose",
                            target="intervention.aciclovir_iv.dose",
                            value=dose_mg,
                            unit="mg",
                        ),
                    ),
                )
                for index, dose_mg in enumerate((125.0, 250.0))
            ),
        ),
    )

    execution = run_aciclovir_iv_dose_uncertainty(
        draw_id,
        draw_artifact_root=tmp_path / "draws",
        output_root=tmp_path / "executions",
        target_model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        r_libs_user=r_libs_user,
    )
    rows = pq.read_table(execution.execution_directory / "executions.parquet").to_pylist()

    assert [row["requested_value"] for row in rows] == [125.0, 250.0]
    assert [row["executed_value"] for row in rows] == [0.000125, 0.00025]
    assert rows[0]["verification_status"] == rows[1]["verification_status"] == "VERIFIED"
    assert rows[0]["result_semantic_sha256"] != rows[1]["result_semantic_sha256"]
    assert rows[0]["endpoint_semantic_sha256"] != rows[1]["endpoint_semantic_sha256"]
    assert (rows[0]["cmax"], rows[0]["tmax"], rows[0]["auc_0_last"]) != (
        rows[1]["cmax"],
        rows[1]["tmax"],
        rows[1]["auc_0_last"],
    )


def test_declared_multi_dose_demo_executes_otus_to_otsens(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")
    if not PKML_PATH.is_file():
        pytest.skip(f"Bundled OSP aciclovir PKML is not available: {PKML_PATH}")

    demo = run_aciclovir_iv_multi_dose_sensitivity_demo(
        output_root=tmp_path / "multi-dose-demo", r_libs_user=r_libs_user
    )

    rows = pq.read_table(
        demo.sensitivity.sensitivity_directory / "sensitivities.parquet"
    ).to_pylist()
    assert demo.execution.manifest.executions.rows == 8
    assert {(row["output_id"], row["rank"]) for row in rows} == {
        ("cmax", 1),
        ("auc_0_last", 1),
    }
    assert demo.sensitivity.manifest.source_execution_id == demo.execution.execution_id
