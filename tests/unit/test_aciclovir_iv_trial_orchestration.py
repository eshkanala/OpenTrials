"""Contract tests for the prospective multi-arm Aciclovir IV trial workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_trial import TOTAL_PLASMA_PATH, run_aciclovir_iv_trial
from opentrials.patient import PopulationSpec
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
    ObservationSchedule,
    RandomizationType,
    SamplingWindow,
    TimeWindow,
    Trial,
    TrialArm,
)

COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-trial-orchestration-test"
POPULATION_SIZE = 10


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def population_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {"IndividualId": i, "Gender": "FEMALE", "Organism|Age": 20.0 + i}
        for i in range(POPULATION_SIZE)
    )


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="trial-orchestration-demo",
        source_request=document(
            "opentrials.osp.population-worker-request",
            {"population_id": "trial-orchestration-demo"},
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=POPULATION_SIZE,
        column_names=COLUMNS,
        rows=population_rows(),
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


def three_arm_trial() -> Trial:
    return Trial(
        trial_id="ACICLOVIR-DOSE-COMPARISON",
        title="Aciclovir dose-ranging trial",
        question_of_interest="How do outcomes differ across prospectively assigned arms?",
        population=PopulationSpec(
            id="trial-orchestration-demo", size=POPULATION_SIZE, seed=1, generator_version="0.1.0"
        ),
        arms=(
            arm("low", 125.0, 1 / 3),
            arm("standard", 250.0, 1 / 3),
            arm("high", 375.0, 1 / 3),
        ),
        randomization=RandomizationType.PARALLEL,
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
        seed=99,
    )


def fake_execution(
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


def fake_execution_with_schedule(
    *,
    prepared_run: object,
    population_rows: object,
    output_intervals: tuple[object, ...] = (),
    **_: object,
) -> RawSimulationResult:
    individual_ids = sorted(
        int(row["IndividualId"]) for row in population_rows  # type: ignore[union-attr,index]
    )
    declared_times: list[float] = []
    for interval in output_intervals:
        start = interval.start_time  # type: ignore[attr-defined]
        end = interval.end_time  # type: ignore[attr-defined]
        step = 1.0 / interval.resolution  # type: ignore[attr-defined]
        count = round((end - start) / step)
        declared_times.extend(start + index * step for index in range(count + 1))
    declared_times = sorted(set(declared_times))

    rows = []
    for individual_id in individual_ids:
        cmax = 10.0 * (individual_id + 1)
        for time in declared_times:
            rows.append(
                {
                    "IndividualId": individual_id,
                    "Time": time,
                    "simulationValues": cmax * (1 - time / (2 * max(declared_times))),
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
            "output_schedule_applied": bool(output_intervals),
            "observed_output_times": declared_times if output_intervals else None,
            "execution_verification": {
                "model_hash_verification": {"verified": True},
                "route_container_verification": {"verified": True},
                "solver_executed": True,
                "parameter_assignments": [{"verified": True}] * 3,
            },
            "raw_result_rows": rows,
        },
    )


def test_multi_arm_trial_with_observation_schedule_computes_endpoints_from_declared_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_trial._execute_osp_population",
        fake_execution_with_schedule,
    )
    schedule = ObservationSchedule(
        schedule_id="sparse-proof",
        time_unit="min",
        windows=(
            SamplingWindow(
                start=ScientificValue(value=0, unit="min", value_type=ValueType.ASSUMED),
                end=ScientificValue(value=60, unit="min", value_type=ValueType.ASSUMED),
                interval=ScientificValue(value=15, unit="min", value_type=ValueType.ASSUMED),
            ),
        ),
    )

    result = run_aciclovir_iv_trial(
        three_arm_trial(),
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        observation_schedule=schedule,
    )

    for arm_result in result.arms:
        sample_times = {
            round(endpoint.value, 6)
            for endpoint in arm_result.endpoints
            if endpoint.endpoint_type == "TMAX"
        }
        assert sample_times <= {0.0, 15.0, 30.0, 45.0, 60.0}

    top_manifest = json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))
    assert top_manifest["payload"]["observation_schedule"]["schedule_id"] == "sparse-proof"
    assert top_manifest["payload"]["observation_schedule"]["declared_times_min"] == [
        0.0,
        15.0,
        30.0,
        45.0,
        60.0,
    ]


def test_multi_arm_trial_rejects_mismatched_observed_output_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)

    def wrong_schedule_execution(
        *, prepared_run: object, population_rows: object, **_: object
    ) -> RawSimulationResult:
        individual_ids = sorted(
            int(row["IndividualId"]) for row in population_rows  # type: ignore[union-attr,index]
        )
        return RawSimulationResult(
            run_id=prepared_run.run_id,  # type: ignore[attr-defined]
            engine_id="osp",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            payload={
                "population_count": len(individual_ids),
                "result_individual_ids": individual_ids,
                "output_schedule_applied": True,
                "observed_output_times": [0.0, 5.0],  # does not match declared [0, 15, 30, 45, 60]
                "execution_verification": {
                    "model_hash_verification": {"verified": True},
                    "route_container_verification": {"verified": True},
                    "solver_executed": True,
                    "parameter_assignments": [{"verified": True}] * 3,
                },
                "raw_result_rows": [
                    {
                        "IndividualId": individual_ids[0],
                        "Time": 0,
                        "simulationValues": 1.0,
                        "unit": "umol/L",
                        "paths": TOTAL_PLASMA_PATH,
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_trial._execute_osp_population",
        wrong_schedule_execution,
    )
    schedule = ObservationSchedule(
        schedule_id="mismatch-proof",
        time_unit="min",
        windows=(
            SamplingWindow(
                start=ScientificValue(value=0, unit="min", value_type=ValueType.ASSUMED),
                end=ScientificValue(value=60, unit="min", value_type=ValueType.ASSUMED),
                interval=ScientificValue(value=15, unit="min", value_type=ValueType.ASSUMED),
            ),
        ),
    )

    with pytest.raises(ValueError, match="do not match the declared observation schedule"):
        run_aciclovir_iv_trial(
            three_arm_trial(),
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            output_root=tmp_path / "runs",
            r_libs_user="/fake/r/libs",
            observation_schedule=schedule,
        )


def test_multi_arm_trial_persists_lineage_aware_artifacts_per_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    population_root = build_population(tmp_path)
    monkeypatch.setattr(
        "opentrials.orchestration.aciclovir_iv_trial._execute_osp_population", fake_execution
    )
    stages: list[str] = []

    result = run_aciclovir_iv_trial(
        three_arm_trial(),
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        progress=stages.append,
    )

    assert stages[0] == "validating_trial"
    assert stages[1] == "verifying_population"
    assert "allocating_arms" in stages
    assert {"executing_arm:low", "executing_arm:standard", "executing_arm:high"} <= set(stages)
    assert stages[-2:] == ["writing_manifest", "completed"]

    assert result.population_count == POPULATION_SIZE
    assert len(result.arms) == 3
    assert sum(arm_result.participant_count for arm_result in result.arms) == POPULATION_SIZE
    assert {arm_result.dose_mg for arm_result in result.arms} == {125.0, 250.0, 375.0}

    # Every arm produced lineage-aware endpoints for exactly its allocated subjects.
    all_subject_ids: set[str] = set()
    for arm_result in result.arms:
        subject_ids = {endpoint.subject_id for endpoint in arm_result.endpoints}
        assert len(subject_ids) == arm_result.participant_count
        assert not (subject_ids & all_subject_ids)  # arms are disjoint
        all_subject_ids |= subject_ids

        endpoint_manifest_path = arm_result.endpoint_directory / "manifest.json"
        endpoint_manifest = json.loads(
            endpoint_manifest_path.read_text(encoding="utf-8")
        )["payload"]
        assert endpoint_manifest["population_lineage_present"] is True
        assert endpoint_manifest["source_generation_id"] == GENERATION_ID

    top_manifest = json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))
    assert top_manifest["schema"] == "opentrials.aciclovir-iv-trial-run"
    assert set(top_manifest["payload"]["arms"]) == {"low", "standard", "high"}
    assert (result.run_directory / "allocation" / result.allocation_id / "manifest.json").is_file()


def test_multi_arm_trial_rejects_non_randomized_trial(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    single_arm_trial = three_arm_trial().model_copy(
        update={
            "arms": (arm("only", 250.0, 1.0),),
            "randomization": RandomizationType.NONE,
        }
    )

    with pytest.raises(ValueError, match="PARALLEL-randomized"):
        run_aciclovir_iv_trial(
            single_arm_trial,
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            output_root=tmp_path / "runs",
            r_libs_user="/fake/r/libs",
        )


def test_multi_arm_trial_rejects_non_aciclovir_arm(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    bad_arm = arm("low", 125.0, 0.5).model_copy(
        update={
            "intervention": arm("low", 125.0, 0.5).intervention.model_copy(
                update={
                    "compound": Compound(
                        identity=CompoundIdentity(compound_id="other", preferred_name="Other")
                    )
                }
            )
        }
    )
    trial = three_arm_trial().model_copy(
        update={"arms": (bad_arm, arm("standard", 250.0, 0.5))}
    )

    with pytest.raises(ValueError, match="only aciclovir"):
        run_aciclovir_iv_trial(
            trial,
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            output_root=tmp_path / "runs",
            r_libs_user="/fake/r/libs",
        )
