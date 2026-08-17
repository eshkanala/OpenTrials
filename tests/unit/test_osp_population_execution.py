from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opentrials.adapters.osp import (
    OspExecutionVerificationError,
    OspParameterAssignment,
    OspSimulationEngine,
)
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType
from opentrials.patient import PopulationSpec
from opentrials.simulation.engine import PreparedRun
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


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


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


def minimal_trial() -> Trial:
    intervention = Intervention(
        intervention_id="aciclovir-population",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="single-dose",
            doses=(
                Dose(
                    amount=assumed(250, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="aciclovir-population-demo",
        title="Population execution",
        question_of_interest="Can the whole population be executed in one batch?",
        population=PopulationSpec(id="three-adults", size=3, seed=42, generator_version="0.1.0"),
        arms=(TrialArm(arm_id="iv", name="IV", intervention=intervention, allocation=1.0),),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="raw OSP result",
                unit="umol/L",
            ),
        ),
        seed=42,
    )


def population_rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE"},
        {"IndividualId": 1, "Gender": "MALE"},
        {"IndividualId": 2, "Gender": "FEMALE"},
    )


def success_response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "SUCCEEDED",
        "run_id": "OTR-population-001",
        "engine_id": "osp",
        "generated_at": "2026-08-17T12:00:00Z",
        "r_version": "R version 4.6.1",
        "ospsuite_version": "12.4.4",
        "simulation_name": "Vergin 1995 IV",
        "population_count": 3,
        "result_individual_ids": [0, 1, 2],
        "execution_verification": {
            "model_hash_verification": {"verified": True},
            "route_container_verification": {"verified": True},
            "solver_executed": True,
            "parameter_assignments": [{"verified": True}],
        },
        "raw_result_rows": [{"IndividualId": 0, "Time": 0, "simulationValues": 1.0}],
    }
    payload.update(overrides)
    return {
        "schema": "opentrials.osp.population-execution-worker-response",
        "schema_version": "1.0.0",
        "payload": payload,
    }


def test_run_population_sends_the_verified_table_and_returns_raw_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    population_worker_path = tmp_path / "run_population_simulation.R"
    population_worker_path.touch()

    captured_request: dict[str, object] = {}

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        input_path = Path(command[command.index("--input") + 1])
        captured_request.update(json.loads(input_path.read_text(encoding="utf-8")))
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(json.dumps(success_response()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opentrials.adapters.osp.engine.subprocess.run", fake_run)
    engine = OspSimulationEngine(
        rscript_path=rscript_path, population_worker_path=population_worker_path
    )
    prepared = PreparedRun(
        run_id="OTR-population-001",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    plan_assignment = OspParameterAssignment(
        parameter_path="Events|IV 250mg 10min|Application_1|ProtocolSchemaItem|Dose",
        value=0.00025,
        unit="kg",
        source_field="dose.amount",
    )

    raw_result = engine.run_population(
        prepared,
        population_columns=("IndividualId", "Gender"),
        population_rows=population_rows(),
        expected_population_count=3,
        expected_pkml_sha256="a" * 64,
        expected_administration_container="Events|IV 250mg 10min|",
        parameter_assignments=(plan_assignment,),
    )

    assert raw_result.payload["population_count"] == 3
    assert raw_result.payload["result_individual_ids"] == [0, 1, 2]
    request_payload = captured_request["payload"]
    assert request_payload["population_columns"] == ["IndividualId", "Gender"]
    assert request_payload["population_rows"] == list(population_rows())
    assert request_payload["expected_population_count"] == 3
    assert request_payload["expected_pkml_sha256"] == "a" * 64


def test_run_population_rejects_mismatched_row_count(tmp_path: Path) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    engine = OspSimulationEngine(rscript_path=tmp_path / "Rscript")
    prepared = PreparedRun(
        run_id="OTR-population-002",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    with pytest.raises(ValueError, match="expected_population_count"):
        engine.run_population(
            prepared,
            population_columns=("IndividualId",),
            population_rows=population_rows(),
            expected_population_count=99,
            expected_pkml_sha256="a" * 64,
        )


def test_run_population_surfaces_execution_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    population_worker_path = tmp_path / "run_population_simulation.R"
    population_worker_path.touch()

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                success_response(
                    status="FAILED",
                    error="Input PKML SHA-256 does not match expected_pkml_sha256.",
                    execution_verification={
                        "model_hash_verification": {"verified": False},
                        "route_container_verification": {"verified": None},
                        "solver_executed": False,
                        "parameter_assignments": [],
                    },
                )
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, "", "PKML hash mismatch")

    monkeypatch.setattr("opentrials.adapters.osp.engine.subprocess.run", fake_run)
    engine = OspSimulationEngine(
        rscript_path=rscript_path, population_worker_path=population_worker_path
    )
    prepared = PreparedRun(
        run_id="OTR-population-003",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    with pytest.raises(OspExecutionVerificationError, match="blocked the solver"):
        engine.run_population(
            prepared,
            population_columns=("IndividualId",),
            population_rows=population_rows(),
            expected_population_count=3,
            expected_pkml_sha256="a" * 64,
        )
