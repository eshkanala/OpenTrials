from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opentrials.adapters.osp import OspSimulationEngine, OspWorkerError
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType
from opentrials.patient import PopulationSpec
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

HASH = "sha256:" + "a" * 64


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def one_person_trial() -> Trial:
    intervention = Intervention(
        intervention_id="aciclovir-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="single-dose",
            doses=(
                Dose(
                    amount=observed(250, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=observed(0, "hour"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="aciclovir-demo",
        title="One individual aciclovir execution",
        question_of_interest="Can the OSP worker execute a packaged PBPK model?",
        population=PopulationSpec(id="one-adult", size=1, seed=42, generator_version="0.1.0"),
        arms=(
            TrialArm(arm_id="treatment", name="Treatment", intervention=intervention, allocation=1),
        ),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma concentration",
                time_window=TimeWindow(start=observed(0, "hour"), end=observed(24, "hour")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="raw OSP result",
                unit="umol/L",
            ),
        ),
        seed=42,
    )


def osp_package(pkml_path: Path) -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="osp.aciclovir.vergin-1995-iv",
            version="1.0.0",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("existing_pkml",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "umol/L"},
            applicability=Applicability(species=("human",)),
            license="GPL-2.0-only",
        ),
        artifact_uri=pkml_path.as_uri(),
        artifact_hash=HASH,
        parameter_set_id="as-packaged",
        parameter_hash=HASH,
        package_hash=HASH,
    )


def test_osp_adapter_rejects_population_execution_before_population_support(tmp_path: Path) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    trial = one_person_trial().model_copy(
        update={
            "population": PopulationSpec(
                id="two-adults", size=2, seed=42, generator_version="0.1.0"
            )
        }
    )

    validation = OspSimulationEngine().validate((osp_package(pkml_path),), trial)

    assert validation.is_valid is False
    assert "exactly one individual" in validation.errors[0]


def test_osp_adapter_runs_versioned_worker_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    worker_path = tmp_path / "run_simulation.R"
    worker_path.touch()

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "schema": "opentrials.osp.worker-response",
                    "schema_version": "1.0.0",
                    "payload": {
                        "status": "SUCCEEDED",
                        "run_id": "OTR-osp-001",
                        "engine_id": "osp",
                        "generated_at": "2026-08-17T12:00:00Z",
                        "r_version": "R version 4.6.1",
                        "ospsuite_version": "12.4.4",
                        "simulation_name": "Vergin 1995 IV",
                        "individual_count": 1,
                        "raw_result_rows": [{"Time": 0, "simulationValues": 0}],
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opentrials.adapters.osp.engine.subprocess.run", fake_run)
    engine = OspSimulationEngine(rscript_path=rscript_path, worker_path=worker_path)
    prepared = engine.prepare("OTR-osp-001", (osp_package(pkml_path),), one_person_trial())

    raw_result = engine.run(prepared)
    result = engine.extract(raw_result)

    assert raw_result.payload["simulation_name"] == "Vergin 1995 IV"
    assert raw_result.payload["raw_result_rows"] == [{"Time": 0, "simulationValues": 0}]
    assert "normalization is pending" in result.warnings[0]


def test_osp_adapter_rejects_mismatched_worker_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    worker_path = tmp_path / "run_simulation.R"
    worker_path.touch()

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "schema": "opentrials.osp.worker-response",
                    "schema_version": "1.0.0",
                    "payload": {
                        "status": "SUCCEEDED",
                        "run_id": "OTR-wrong",
                        "generated_at": "2026-08-17T12:00:00Z",
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opentrials.adapters.osp.engine.subprocess.run", fake_run)
    engine = OspSimulationEngine(rscript_path=rscript_path, worker_path=worker_path)
    prepared = engine.prepare("OTR-osp-002", (osp_package(pkml_path),), one_person_trial())

    with pytest.raises(OspWorkerError, match="run ID"):
        engine.run(prepared)
