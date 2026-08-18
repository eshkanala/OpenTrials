"""Contract tests for the prospective physiology-state trial workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_physiology_population import TOTAL_PLASMA_PATH
from opentrials.orchestration.aciclovir_iv_physiology_trial import (
    PhysiologyStateDeclaration,
    run_aciclovir_iv_physiology_trial,
)
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PhysiologyComparisonArtifactStore,
    PhysiologyPopulationArtifactStore,
    PhysiologyTrialArtifactStore,
    PkEndpointArtifactStore,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

GFR_COLUMN = "Organism|Kidney|GFRmat"
COLUMNS = ("IndividualId", "Gender", "Organism|Age", GFR_COLUMN)
GENERATION_ID = "OTPGEN-physiology-trial-test"
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
        population_id="physiology-trial-demo",
        source_request=document(
            "opentrials.osp.population-worker-request",
            {"population_id": "physiology-trial-demo"},
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


def fake_execution(
    *, prepared_run: object, population_rows: tuple[dict[str, object], ...], **_: object
) -> RawSimulationResult:
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
    population_readback = [
        {"IndividualId": row["IndividualId"], GFR_COLUMN: row[GFR_COLUMN]}
        for row in population_rows
    ]
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
            "population_readback": population_readback,
            "raw_result_rows": rows,
        },
    )


def declared_states() -> tuple[PhysiologyStateDeclaration, ...]:
    return (
        PhysiologyStateDeclaration(
            state_id="baseline",
            override=PhysiologicalStateOverride(
                target=TARGET, scale_factor=1.0, unit="L/min", purpose="baseline"
            ),
        ),
        PhysiologyStateDeclaration(
            state_id="moderate",
            override=PhysiologicalStateOverride(
                target=TARGET, scale_factor=0.6, unit="L/min", purpose="moderate reduction"
            ),
        ),
        PhysiologyStateDeclaration(
            state_id="severe",
            override=PhysiologicalStateOverride(
                target=TARGET, scale_factor=0.3, unit="L/min", purpose="severe reduction"
            ),
        ),
    )


def test_trial_produces_verifiable_comparison_and_top_level_otphytrial_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_physiology_population._execute_osp_population",
        fake_execution,
    )
    stages: list[str] = []

    result = run_aciclovir_iv_physiology_trial(
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        physiology_root=tmp_path / "physiology",
        states=declared_states(),
        baseline_state_id="baseline",
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        progress=stages.append,
    )

    assert stages[0] == "verifying_source_population"
    assert stages[-1] == "completed"
    assert "comparing_states" in stages
    assert "writing_trial_record" in stages
    assert result.baseline_state_id == "baseline"
    assert set(result.state_ids) == {"baseline", "moderate", "severe"}

    # OTPHYCMP re-verifies independently.
    comparison_store = PhysiologyComparisonArtifactStore(result.run_directory / "comparison")
    comparison_manifest = comparison_store.verify_comparison(result.comparison_id)
    # 3 states x 2 endpoint types (CMAX, AUC_0_LAST; TMAX has n=... check below)
    assert comparison_manifest.state_summaries.rows > 0
    assert comparison_manifest.subject_deltas.rows > 0
    assert comparison_manifest.missingness.complete_subject_count == 3
    assert comparison_manifest.missingness.excluded_subject_ids == ()

    # OTPHYTRIAL re-verifies the whole chain from each sub-artifact's own store.
    population_store = PopulationArtifactStore(population_root)
    physiology_store = PhysiologyPopulationArtifactStore(tmp_path / "physiology")
    trial_run_store = PhysiologyTrialArtifactStore(result.run_directory / "trial_run")
    # Endpoint stores are rooted per executed run directory; rebuild from the
    # trial manifest itself rather than guessing run IDs.
    trial_manifest = trial_run_store.read_manifest(result.trial_run_id)
    endpoint_stores = {}
    for state in trial_manifest.states:
        run_directory = result.run_directory / "states" / state.executed_run_id
        endpoint_stores[state.state_id] = PkEndpointArtifactStore(run_directory / "endpoints")

    verified = trial_run_store.verify_physiology_trial(
        result.trial_run_id,
        population_store=population_store,
        physiology_store=physiology_store,
        endpoint_stores=endpoint_stores,
        comparison_store=comparison_store,
    )
    assert verified.baseline_state_id == "baseline"
    assert len(verified.states) == 3
    assert all(state.physiology_state_verified for state in verified.states)
    assert all(state.observation_schedule_verified is None for state in verified.states)
    assert {state.override_scale_factor for state in verified.states} == {1.0, 0.6, 0.3}


def test_requires_at_least_two_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_physiology_population._execute_osp_population",
        fake_execution,
    )
    with pytest.raises(ValueError, match="at least two"):
        run_aciclovir_iv_physiology_trial(
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            physiology_root=tmp_path / "physiology",
            states=declared_states()[:1],
            baseline_state_id="baseline",
            dose_mg=250.0,
            output_root=tmp_path / "runs",
            r_libs_user="/fake/r/libs",
        )
