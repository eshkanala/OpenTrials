"""Contract tests for the CSV-transport population execution engine method."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pyarrow.csv as pa_csv
import pytest

from opentrials.adapters.osp import OspSimulationEngine, OspWorkerError
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
        trial_id="aciclovir-population-csv-demo",
        title="CSV-transport population execution",
        question_of_interest="Does CSV transport preserve the existing engine contract?",
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


def make_fake_run(result_csv_content: str, response_overrides: dict[str, object] | None = None):
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        input_path = Path(command[command.index("--input") + 1])
        request = json.loads(input_path.read_text(encoding="utf-8"))
        request_payload = request["payload"]

        population_csv_path = Path(request_payload["population_csv_path"])
        assert population_csv_path.is_file()
        table = pa_csv.read_csv(population_csv_path)
        assert table.column_names == ["IndividualId", "Gender"]
        assert table.to_pylist() == list(population_rows())

        result_csv_path = Path(request_payload["result_csv_path"])
        result_csv_path.write_text(result_csv_content, encoding="utf-8")
        result_csv_sha256 = hashlib.sha256(result_csv_path.read_bytes()).hexdigest()

        payload: dict[str, object] = {
            "status": "SUCCEEDED",
            "run_id": "OTR-population-csv-001",
            "engine_id": "osp",
            "generated_at": "2026-08-18T12:00:00Z",
            "r_version": "R version 4.6.1",
            "ospsuite_version": "12.4.4",
            "simulation_name": "Vergin 1995 IV",
            "population_count": 3,
            "result_individual_ids": [0, 1, 2],
            "output_schedule_applied": False,
            "observed_output_times": None,
            "population_readback": None,
            "result_csv_sha256": result_csv_sha256,
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [],
            },
        }
        if response_overrides:
            payload.update(response_overrides)
        response = {
            "schema": "opentrials.osp.population-execution-csv-worker-response",
            "schema_version": "1.0.0",
            "payload": payload,
        }
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(json.dumps(response), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    return fake_run


RESULT_CSV = (
    '"IndividualId","Time [min]","Organism|Plasma [umol/l]"\n'
    "0,0,0.0\n0,10,5.0\n1,0,0.0\n1,10,6.0\n2,0,0.0\n2,10,7.0\n"
)


def test_run_population_csv_writes_population_and_reads_result_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    population_csv_worker_path = tmp_path / "run_population_simulation_csv.R"
    population_csv_worker_path.touch()

    monkeypatch.setattr(
        "opentrials.adapters.osp.engine.subprocess.run", make_fake_run(RESULT_CSV)
    )
    engine = OspSimulationEngine(
        rscript_path=rscript_path, population_csv_worker_path=population_csv_worker_path
    )
    prepared = PreparedRun(
        run_id="OTR-population-csv-001",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    raw_result = engine.run_population_csv(
        prepared,
        population_columns=("IndividualId", "Gender"),
        population_rows=population_rows(),
        expected_population_count=3,
        expected_pkml_sha256="a" * 64,
    )

    assert raw_result.payload["population_count"] == 3
    assert raw_result.payload["result_individual_ids"] == [0, 1, 2]
    raw_rows = raw_result.payload["raw_result_rows"]
    assert len(raw_rows) == 6
    assert raw_rows[0] == {
        "IndividualId": 0,
        "Time": 0,
        "simulationValues": 0.0,
        "unit": "umol/l",
        "paths": "Organism|Plasma",
    }
    # result_csv_sha256 is an internal transport-verification detail, not a
    # scientific field -- it must not leak into the returned payload.
    assert "result_csv_sha256" not in raw_result.payload


def test_run_population_csv_rejects_a_tampered_result_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    population_csv_worker_path = tmp_path / "run_population_simulation_csv.R"
    population_csv_worker_path.touch()

    monkeypatch.setattr(
        "opentrials.adapters.osp.engine.subprocess.run",
        make_fake_run(RESULT_CSV, response_overrides={"result_csv_sha256": "0" * 64}),
    )
    engine = OspSimulationEngine(
        rscript_path=rscript_path, population_csv_worker_path=population_csv_worker_path
    )
    prepared = PreparedRun(
        run_id="OTR-population-csv-001",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    with pytest.raises(OspWorkerError) as excinfo:
        engine.run_population_csv(
            prepared,
            population_columns=("IndividualId", "Gender"),
            population_rows=population_rows(),
            expected_population_count=3,
            expected_pkml_sha256="a" * 64,
        )
    assert "does not match" in str(excinfo.value)


def test_run_population_csv_rejects_mismatched_row_count(tmp_path: Path) -> None:
    pkml_path = tmp_path / "aciclovir.pkml"
    pkml_path.touch()
    engine = OspSimulationEngine(r_libs_user="/fake/r/libs")
    prepared = PreparedRun(
        run_id="OTR-population-csv-002",
        trial=minimal_trial(),
        model_packages=(osp_package(pkml_path),),
        seed=42,
    )

    with pytest.raises(ValueError, match="expected_population_count"):
        engine.run_population_csv(
            prepared,
            population_columns=("IndividualId", "Gender"),
            population_rows=population_rows(),
            expected_population_count=5,
            expected_pkml_sha256="a" * 64,
        )
