"""Contract tests for the thin `opentrials report` CLI command.

Builds a real, persisted (monkeypatched-execution) run exactly like
``test_reporting_build.py``, then drives the CLI's ``report`` subcommand
against it -- proving the command dispatches, detects trial vs. population
run shape, and writes the requested format to the requested path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.cli.main import main
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import (
    ACICLOVIR_IV_CAPABILITY_PROFILE,
    TOTAL_PLASMA_PATH,
)
from opentrials.sdk.population import run_population
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-cli-report-test"
POPULATION_SIZE = 3


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="cli-report-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "cli-report-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=POPULATION_SIZE,
        column_names=COLUMNS,
        rows=tuple(
            {"IndividualId": i, "Gender": "FEMALE", "Organism|Age": 20.0 + i}
            for i in range(POPULATION_SIZE)
        ),
    )
    return root


def fake_population_execution(*, prepared_run: object, **_: object) -> RawSimulationResult:
    rows = []
    for individual_id, cmax in ((0, 10.0), (1, 20.0), (2, 30.0)):
        for time, value in ((0, cmax / 2), (10, cmax)):
            rows.append(
                {
                    "IndividualId": individual_id,
                    "Time": time,
                    "simulationValues": value,
                    "unit": "umol/L",
                    "paths": TOTAL_PLASMA_PATH,
                }
            )
    return RawSimulationResult(
        run_id=prepared_run.run_id,  # type: ignore[attr-defined]
        engine_id="osp",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={
            "population_count": POPULATION_SIZE,
            "result_individual_ids": [0, 1, 2],
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True}] * 3,
            },
            "raw_result_rows": rows,
        },
    )


def _population_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.population_execution._execute_osp_population",
        fake_population_execution,
    )
    run = run_population(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
    )
    return run.run_directory, population_root


def test_cli_report_writes_markdown_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_directory, population_root = _population_run(tmp_path, monkeypatch)
    output_path = tmp_path / "report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "opentrials", "report", str(run_directory),
            "--population-root", str(population_root),
            "--output", str(output_path),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert "Report written" in capsys.readouterr().out
    content = output_path.read_text(encoding="utf-8")
    assert "## PK Endpoints" in content


def test_cli_report_writes_html_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_directory, population_root = _population_run(tmp_path, monkeypatch)
    output_path = tmp_path / "report.html"
    monkeypatch.setattr(
        "sys.argv",
        [
            "opentrials", "report", str(run_directory),
            "--population-root", str(population_root),
            "--format", "html",
            "--output", str(output_path),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")


def test_cli_report_fails_cleanly_on_a_bad_population_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_directory, _population_root = _population_run(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv",
        [
            "opentrials", "report", str(run_directory),
            "--population-root", str(tmp_path / "does-not-exist"),
        ],
    )

    exit_code = main()

    assert exit_code == 1
    assert "Report failed" in capsys.readouterr().out
