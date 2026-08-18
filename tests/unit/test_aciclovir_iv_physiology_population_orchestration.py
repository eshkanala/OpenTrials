"""Contract tests for the physiology-state population execution workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.adapters.osp import UnsupportedPhysiologyTargetError
from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_physiology_population import (
    TOTAL_PLASMA_PATH,
    build_physiology_population,
    run_aciclovir_iv_physiology_population,
)
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

GFR_COLUMN = "Organism|Kidney|GFRmat"
COLUMNS = ("IndividualId", "Gender", "Organism|Age", GFR_COLUMN)
GENERATION_ID = "OTPGEN-physiology-orchestration-test"
TARGET = "renal.glomerular_filtration_rate"


def population_rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 22.0, GFR_COLUMN: 0.10},
        {"IndividualId": 1, "Gender": "MALE", "Organism|Age": 55.0, GFR_COLUMN: 0.12},
        {"IndividualId": 2, "Gender": "FEMALE", "Organism|Age": 63.0, GFR_COLUMN: 0.09},
    )


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="physiology-orchestration-demo",
        source_request=document(
            "opentrials.osp.population-worker-request",
            {"population_id": "physiology-orchestration-demo"},
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


def test_build_physiology_population_scales_only_the_verified_column(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    manifest = build_physiology_population(
        physiology_population_id="OTPHYS-severe",
        physiology_root=physiology_root,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        override=PhysiologicalStateOverride(
            target=TARGET, scale_factor=0.3, unit="L/min", purpose="test"
        ),
    )
    assert manifest.source_generation_id == GENERATION_ID
    assert manifest.changed_column == GFR_COLUMN
    assert manifest.individuals.rows == 3


def test_run_over_physiology_population_resolves_lineage_against_original_otpgen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    build_physiology_population(
        physiology_population_id="OTPHYS-moderate",
        physiology_root=physiology_root,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        override=PhysiologicalStateOverride(
            target=TARGET, scale_factor=0.6, unit="L/min", purpose="test"
        ),
    )
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_physiology_population._execute_osp_population",
        fake_execution,
    )
    stages: list[str] = []

    result = run_aciclovir_iv_physiology_population(
        physiology_population_id="OTPHYS-moderate",
        physiology_root=physiology_root,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        progress=stages.append,
    )

    assert stages == [
        "verifying_physiology_population",
        "verifying_source_population",
        "translating_intervention",
        "executing_population",
        "persisting_raw",
        "normalizing_results",
        "resolving_lineage",
        "calculating_endpoints",
        "writing_manifest",
        "completed",
    ]
    assert result.physiology_population_id == "OTPHYS-moderate"
    assert result.source_generation_id == GENERATION_ID
    assert result.population_count == 3
    assert {endpoint.subject_id for endpoint in result.endpoints} == {"0", "1", "2"}

    endpoint_manifest = json.loads(
        (result.endpoint_directory / "manifest.json").read_text(encoding="utf-8")
    )["payload"]
    assert endpoint_manifest["population_lineage_present"] is True
    # Lineage must reference the *original* OTPGEN, never the OTPHYS population.
    assert endpoint_manifest["source_generation_id"] == GENERATION_ID


def test_two_physiology_states_from_the_same_source_yield_identical_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the override design: state changes, lineage does not."""
    population_root = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    for physiology_population_id, scale_factor in (("OTPHYS-a", 1.0), ("OTPHYS-b", 0.3)):
        build_physiology_population(
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            override=PhysiologicalStateOverride(
                target=TARGET, scale_factor=scale_factor, unit="L/min", purpose="test"
            ),
        )
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_physiology_population._execute_osp_population",
        fake_execution,
    )

    lineage_by_state: dict[str, dict[str, tuple[int, str]]] = {}
    for physiology_population_id in ("OTPHYS-a", "OTPHYS-b"):
        result = run_aciclovir_iv_physiology_population(
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_root=population_root,
            dose_mg=250.0,
            output_root=tmp_path / "runs" / physiology_population_id,
            r_libs_user="/fake/r/libs",
        )
        endpoint_rows = json.loads(
            (result.endpoint_directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert endpoint_rows["payload"]["source_generation_id"] == GENERATION_ID
        assert (
            endpoint_rows["payload"]["source_population_semantic_sha256"] is not None
        )
        lineage_by_state[physiology_population_id] = {
            "source_generation_id": endpoint_rows["payload"]["source_generation_id"],
            "source_population_semantic_sha256": endpoint_rows["payload"][
                "source_population_semantic_sha256"
            ],
        }

    assert lineage_by_state["OTPHYS-a"] == lineage_by_state["OTPHYS-b"]


def test_build_physiology_population_rejects_an_unverified_target(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)

    with pytest.raises(UnsupportedPhysiologyTargetError):
        build_physiology_population(
            physiology_population_id="OTPHYS-invalid",
            physiology_root=tmp_path / "physiology",
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            override=PhysiologicalStateOverride(
                target="hepatic.function", scale_factor=0.5, unit="L/min", purpose="test"
            ),
        )
