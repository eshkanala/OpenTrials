"""Contract tests for Project.run()'s routing between population and trial execution.

Uses ``population_generation_id``/``population_root`` reuse mode throughout
so these tests never need real OSP population generation -- only the final
execution step, which is monkeypatched exactly like every other orchestration
contract test in this project. The "generate a fresh population" path is
proven separately, live, in
``tests/integration/test_sdk_project_live.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.config.project import ProjectConfig
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import (
    TOTAL_PLASMA_PATH,
)
from opentrials.patient import PopulationSpec
from opentrials.sdk.project import Project
from opentrials.sdk.run import PopulationRun, TrialRun
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
GENERATION_ID = "OTPGEN-sdk-project-test"
POPULATION_SIZE = 4


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="sdk-project-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "sdk-project-demo"}
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


def trial_with(*arms: TrialArm, randomization: RandomizationType) -> Trial:
    return Trial(
        trial_id="SDK-PROJECT-TRIAL",
        title="SDK project trial",
        question_of_interest="Does routing work?",
        population=PopulationSpec(
            id="sdk-project-demo", size=POPULATION_SIZE, seed=1, generator_version="0.1.0"
        ),
        arms=arms,
        randomization=randomization,
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
        seed=3,
    )


def fake_population_execution(*, prepared_run: object, **_: object) -> RawSimulationResult:
    rows = [
        {
            "IndividualId": i,
            "Time": t,
            "simulationValues": v,
            "unit": "umol/L",
            "paths": TOTAL_PLASMA_PATH,
        }
        for i in range(POPULATION_SIZE)
        for t, v in ((0, 5.0), (10, 10.0))
    ]
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


def fake_trial_execution(
    *, prepared_run: object, population_rows: object, **_: object
) -> RawSimulationResult:
    individual_ids = sorted(
        int(row["IndividualId"]) for row in population_rows  # type: ignore[union-attr,index]
    )
    rows = [
        {
            "IndividualId": i,
            "Time": t,
            "simulationValues": v,
            "unit": "umol/L",
            "paths": TOTAL_PLASMA_PATH,
        }
        for i in individual_ids
        for t, v in ((0, 5.0), (10, 10.0))
    ]
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


def test_project_run_routes_a_single_arm_trial_to_population_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.population_execution._execute_osp_population",
        fake_population_execution,
    )
    project = Project(
        ProjectConfig(
            trial=trial_with(arm("only", 250.0, 1.0), randomization=RandomizationType.NONE),
            model_id="osp.aciclovir.vergin-1995-iv",
            population_generation_id=GENERATION_ID,
            population_root=population_root,
        )
    )

    run = project.run(output_root=tmp_path / "runs", r_libs_user="/fake/r/libs")

    assert isinstance(run, PopulationRun)
    assert run.population.participant_count == POPULATION_SIZE


def test_project_run_accepts_a_plain_string_output_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.population_execution._execute_osp_population",
        fake_population_execution,
    )
    project = Project(
        ProjectConfig(
            trial=trial_with(arm("only", 250.0, 1.0), randomization=RandomizationType.NONE),
            model_id="osp.aciclovir.vergin-1995-iv",
            population_generation_id=GENERATION_ID,
            population_root=population_root,
        )
    )

    run = project.run(output_root=str(tmp_path / "runs"), r_libs_user="/fake/r/libs")

    assert isinstance(run, PopulationRun)


def test_project_run_routes_a_multi_arm_trial_to_trial_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.trial_execution._execute_osp_population", fake_trial_execution
    )
    project = Project(
        ProjectConfig(
            trial=trial_with(
                arm("low", 125.0, 0.5),
                arm("high", 250.0, 0.5),
                randomization=RandomizationType.PARALLEL,
            ),
            model_id="osp.aciclovir.vergin-1995-iv",
            population_generation_id=GENERATION_ID,
            population_root=population_root,
        )
    )

    run = project.run(output_root=tmp_path / "runs", r_libs_user="/fake/r/libs")

    assert isinstance(run, TrialRun)
    assert {arm.arm_id for arm in run.arms} == {"low", "high"}


def test_project_run_requires_population_root_alongside_generation_id(tmp_path: Path) -> None:
    project = Project(
        ProjectConfig(
            trial=trial_with(arm("only", 250.0, 1.0), randomization=RandomizationType.NONE),
            model_id="osp.aciclovir.vergin-1995-iv",
            population_generation_id=GENERATION_ID,
        )
    )

    with pytest.raises(ValueError, match="population_root is required"):
        project.run(output_root=tmp_path / "runs", r_libs_user="/fake/r/libs")
