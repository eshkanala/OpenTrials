"""Contract tests for the population-linked Aciclovir IV execution workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_population import (
    TOTAL_PLASMA_PATH,
    run_aciclovir_iv_population,
)
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-population-orchestration-test"


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
        population_id="orchestration-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "orchestration-demo"}
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


def test_population_run_persists_lineage_aware_artifacts_and_reports_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_population._execute_osp_population",
        fake_execution,
    )
    stages: list[str] = []

    result = run_aciclovir_iv_population(
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        progress=stages.append,
    )

    assert stages == [
        "verifying_population",
        "translating_intervention",
        "executing_population",
        "persisting_raw",
        "normalizing_results",
        "resolving_lineage",
        "calculating_endpoints",
        "writing_manifest",
        "completed",
    ]
    assert result.population_generation_id == GENERATION_ID
    assert result.population_count == 3
    assert {endpoint.subject_id for endpoint in result.endpoints} == {"0", "1", "2"}

    # v0.6-C: every run records a per-stage timing breakdown; the JSON
    # transport has no R-side/Python-side transport sub-stage detail.
    expected_stage_names = {
        "verify_otpgen",
        "translate_intervention",
        "execute_population",
        "persist_raw",
        "normalize_results",
        "pk_analysis",
        "resolve_lineage",
        "persist_endpoints",
        "total",
    }
    assert expected_stage_names <= set(result.stage_seconds)
    assert not any(key.startswith(("r_", "python_")) for key in result.stage_seconds)
    assert all(value >= 0 for value in result.stage_seconds.values())

    endpoint_manifest = json.loads(
        (result.endpoint_directory / "manifest.json").read_text(encoding="utf-8")
    )["payload"]
    assert endpoint_manifest["population_lineage_present"] is True
    assert endpoint_manifest["source_generation_id"] == GENERATION_ID

    top_manifest = json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))
    assert top_manifest["schema"] == "opentrials.aciclovir-iv-population-run"
    assert top_manifest["payload"]["population_count"] == 3
    assert top_manifest["payload"]["dose_mg"] == 250.0


def test_population_run_rejects_unsupported_dose(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)

    with pytest.raises(ValueError, match="125 mg or 250 mg"):
        run_aciclovir_iv_population(
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            dose_mg=400.0,
            output_root=tmp_path / "runs",
            r_libs_user="/fake/r/libs",
        )
