"""Contract tests for building ReportData from real, persisted (monkeypatched-execution) runs.

Runs the exact same fake-execution fixtures ``test_sdk_trial.py``/
``test_sdk_population.py`` use, then re-derives a report purely from disk
-- proving ``build_trial_report``/``build_population_report`` genuinely
re-verify the persisted chain rather than trusting the in-memory ``Run``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import (
    ACICLOVIR_IV_CAPABILITY_PROFILE,
    TOTAL_PLASMA_PATH,
)
from opentrials.patient import PopulationSpec
from opentrials.reporting.build import build_population_report, build_trial_report
from opentrials.sdk.population import run_population
from opentrials.sdk.trial import run_trial
from opentrials.simulation.engine import RawSimulationResult
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
)
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-reporting-build-test"
POPULATION_SIZE = 6


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="reporting-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "reporting-demo"}
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


def arm(arm_id: str, dose_mg: float, allocation: float) -> TrialArm:
    intervention = Intervention(
        intervention_id=f"aciclovir-{arm_id}",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id=f"{arm_id}-regimen",
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
    return TrialArm(arm_id=arm_id, name=arm_id, intervention=intervention, allocation=allocation)


def _endpoints() -> tuple[Endpoint, ...]:
    return (
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
    )


def two_arm_trial() -> Trial:
    return Trial(
        trial_id="REPORT-BUILD-TRIAL",
        title="Report build trial",
        question_of_interest="Does the report reflect the real run?",
        population=PopulationSpec(
            id="reporting-demo", size=POPULATION_SIZE, seed=1, generator_version="0.1.0"
        ),
        arms=(arm("low", 125.0, 0.5), arm("high", 250.0, 0.5)),
        randomization=RandomizationType.PARALLEL,
        endpoints=_endpoints(),
        seed=7,
    )


def fake_trial_execution(
    *, prepared_run: object, population_rows: object, **_: object
) -> RawSimulationResult:
    individual_ids = sorted(
        int(row["IndividualId"]) for row in population_rows  # type: ignore[union-attr,index]
    )
    rows = []
    for individual_id in individual_ids:
        cmax = 10.0 * (individual_id + 1)
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
            "population_count": len(individual_ids),
            "result_individual_ids": individual_ids,
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True}] * 3,
            },
            "raw_result_rows": rows,
        },
    )


def fake_population_execution(*, prepared_run: object, **_: object) -> RawSimulationResult:
    rows = []
    for individual_id, cmax in ((0, 10.0), (1, 20.0), (2, 30.0), (3, 40.0), (4, 50.0), (5, 60.0)):
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
            "result_individual_ids": list(range(POPULATION_SIZE)),
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True}] * 3,
            },
            "raw_result_rows": rows,
        },
    )


def test_build_trial_report_reflects_the_real_persisted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.trial_execution._execute_osp_population", fake_trial_execution
    )
    run = run_trial(
        two_arm_trial(),
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
    )

    data = build_trial_report(run.run_directory, population_root)

    assert data.header.report_type == "trial"
    assert data.header.trial_id == "REPORT-BUILD-TRIAL"
    assert data.model.model_id == "osp.aciclovir.vergin-1995-iv"
    assert data.population.participant_count == POPULATION_SIZE
    assert {a.arm_id for a in data.arms} == {"low", "high"}
    assert {row.arm_id for row in data.endpoints} == {"low", "high"}
    assert len(data.comparisons) > 0
    assert len(data.concentration_time_series) == 2
    assert all(row.model_hash_verified for row in data.execution_verification)
    assert all(row.solver_executed for row in data.execution_verification)
    assert data.provenance.comparison_id is not None
    assert data.source_run_directory == run.run_directory
    assert data.source_population_root == population_root


def test_build_trial_report_matches_the_sdk_runs_own_report_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.trial_execution._execute_osp_population", fake_trial_execution
    )
    run = run_trial(
        two_arm_trial(),
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
    )

    from_disk = build_trial_report(run.run_directory, population_root)
    from_method = run.report()

    # Both re-verify from scratch and so may legitimately differ only in
    # header.generated_at (the wall-clock moment each call ran).
    assert from_disk.model_copy(update={"header": None}) == from_method.model_copy(
        update={"header": None}
    )


def test_build_population_report_reflects_the_real_persisted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    data = build_population_report(run.run_directory, population_root)

    assert data.header.report_type == "population"
    assert data.header.trial_id is None
    assert data.population.participant_count == POPULATION_SIZE
    assert data.arms[0].dose_amount == pytest.approx(250.0)
    assert data.comparisons == ()
    assert len(data.concentration_time_series) == 1
    assert all(row.solver_executed for row in data.execution_verification)
