"""Contract tests for sdk.population.run_population and its PopulationRun wrapper."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.core.serialization import document
from opentrials.events import Event
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
GENERATION_ID = "OTPGEN-sdk-population-test"


def population_rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 22.0},
        {"IndividualId": 1, "Gender": "MALE", "Organism|Age": 55.0},
        {"IndividualId": 2, "Gender": "FEMALE", "Organism|Age": 63.0},
    )


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="sdk-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "sdk-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=3,
        column_names=COLUMNS,
        rows=population_rows(),
    )
    return root


def fake_execution(*, prepared_run: object, **_: object) -> RawSimulationResult:
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
            "population_count": 3,
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


def test_run_population_returns_a_working_population_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.population_execution._execute_osp_population", fake_execution
    )
    events: list[Event] = []

    run = run_population(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        events=events.append,
    )

    assert run.run_id.startswith("OTR-")
    assert run.population.generation_id == GENERATION_ID
    assert run.population.participant_count == 3
    assert run.model.model_id == "osp.aciclovir.vergin-1995-iv"
    assert len(run.endpoints) == 9  # 3 subjects x 3 endpoint types
    assert all(record.arm_id is None for record in run.endpoints)

    summary = run.summary()
    assert "OpenTrials population run" in summary
    assert "3 participants" in summary

    assert run.verify() is True
    stages = [event.stage for event in events]
    assert stages[:2] == ["verifying_population", "translating_intervention"]


def test_run_population_artifacts_expose_the_underlying_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.population_execution._execute_osp_population", fake_execution
    )

    run = run_population(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
    )

    assert run.artifacts.execution.population_count == 3
    assert run.artifacts.endpoint_id == run.artifacts.execution.endpoint_directory.name
