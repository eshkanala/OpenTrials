"""Contract tests for the isolated Aciclovir IV engineering workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.orchestration.aciclovir_iv import (
    DEMO_TRIAL_ID,
    TOTAL_PLASMA_PATH,
    run_aciclovir_iv_engineering,
)
from opentrials.patient import PopulationSpec
from opentrials.simulation.engine import RawSimulationResult
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    RandomizationType,
    TimeWindow,
    Trial,
    TrialArm,
)


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def engineering_trial(*, dose_mg: float = 250.0, trial_id: str = DEMO_TRIAL_ID) -> Trial:
    intervention = Intervention(
        intervention_id="aciclovir-iv",
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
    return Trial(
        trial_id=trial_id,
        title="Aciclovir IV engineering",
        question_of_interest="Can the verified IV model be executed?",
        population=PopulationSpec(id="one-adult", size=1, seed=17, generator_version="0.1.0"),
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
        seed=17,
    )


def fake_execution(*, run_id: str, **_: object) -> RawSimulationResult:
    return RawSimulationResult(
        run_id=run_id,
        engine_id="osp",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True}] * 3,
            },
            "raw_result_rows": [
                {
                    "IndividualId": 1,
                    "Time": 0,
                    "simulationValues": 2.0,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                },
                {
                    "IndividualId": 1,
                    "Time": 60,
                    "simulationValues": 1.0,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                },
            ],
        },
    )


def test_run_persists_canonical_artifacts_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("opentrials.orchestration.aciclovir_iv._execute_osp_engine", fake_execution)
    stages: list[str] = []

    result = run_aciclovir_iv_engineering(
        engineering_trial(),
        output_root=tmp_path,
        r_libs_user="/fake/r/libs",
        progress=stages.append,
    )

    assert stages == [
        "validating_trial",
        "preparing_engine",
        "persisting_raw",
        "normalizing_results",
        "calculating_endpoints",
        "writing_manifest",
        "completed",
    ]
    assert result.run_directory == tmp_path / result.run_id
    assert result.result_directory.is_dir()
    assert result.endpoint_directory.is_dir()
    assert {endpoint.endpoint_type.value: endpoint.value for endpoint in result.endpoints} == {
        "CMAX": 2.0,
        "TMAX": 0.0,
        "AUC_0_LAST": 90.0,
    }

    trial_document = json.loads((result.run_directory / "trial.json").read_text())
    raw_document = json.loads((result.run_directory / "raw" / "osp_response.json").read_text())
    manifest = json.loads((result.run_directory / "manifest.json").read_text())
    assert trial_document["schema"] == "opentrials.trial"
    assert raw_document["schema"] == "opentrials.osp-response"
    assert manifest["schema"] == "opentrials.aciclovir-iv-engineering-run"
    payload = manifest["payload"]
    assert payload["raw_sha256"].startswith("sha256:")
    assert payload["result_artifact_semantic_sha256"].startswith("sha256:")
    assert payload["endpoint_semantic_sha256"].startswith("sha256:")
    assert payload["verification_evidence_sha256"].startswith("sha256:")
    assert payload["seeds"] == {"population": 17, "trial": 17}
    assert (result.result_directory / "concentration_time.parquet").is_file()
    assert (result.endpoint_directory / "endpoints.parquet").is_file()


def test_run_rejects_any_trial_id_other_than_the_engineering_demo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="accepts only trial_id"):
        run_aciclovir_iv_engineering(
            engineering_trial(trial_id="other"), output_root=tmp_path, r_libs_user="/fake/r/libs"
        )
