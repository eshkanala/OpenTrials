"""Opt-in live proof: a real prospective 3-arm dose-ranging aciclovir IV trial.

OTPGEN -> OTALLOC (deterministic 3-way split) -> per-arm batched PBPK
execution -> per-arm lineage-aware OTPK v2. The v0.5-A live proof.
"""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.adapters.osp import (
    OspHumanPopulation,
    OspPopulationGenerator,
    OspPopulationProfile,
    OspPopulationTranslator,
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.orchestration.trial_execution import run_trial_execution
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.storage import (
    ArmComparisonArtifactStore,
    PkEndpointArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
    TrialArmAllocationArtifactStore,
    TrialRunArtifactStore,
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

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 30


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


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


def dose_comparison_trial() -> Trial:
    return Trial(
        trial_id="ACICLOVIR-DOSE-COMPARISON-LIVE",
        title="Aciclovir IV dose-ranging trial (live engineering proof)",
        question_of_interest="How does simulated exposure differ across three prospectively "
        "assigned IV dose arms?",
        population=PopulationSpec(
            id="dose-comparison-live", size=POPULATION_SIZE, seed=11, generator_version="0.1.0"
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
        seed=11,
    )


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="dose-comparison-live",
        size=POPULATION_SIZE,
        seed=11,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    translated = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translated)
    generation_id = "OTPGEN-dose-comparison-live"
    store.create_generation(generation_id)
    return store.write_population(
        generation_id,
        population_id=result.population_id,
        source_request=document(
            POPULATION_WORKER_REQUEST_SCHEMA,
            translated.request,
            POPULATION_WORKER_SCHEMA_VERSION,
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp",
            population_model=translated.request.reference_population.value,
            software_versions={"ospsuite": result.ospsuite_version, "r": result.r_version},
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=result.requested_seed,
            engine_seed=result.engine_seed,
            determinism_level=result.determinism_level.value,
        ),
        requested_count=translated.request.number_of_individuals,
        column_names=result.column_names,
        rows=result.raw_rows,
    )


def test_prospective_three_arm_trial_executes_and_yields_distinct_arm_outcomes(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    population_manifest = generate_and_persist_population(population_store, r_libs_user)
    generation_id = population_manifest.generation_id

    run = run_trial_execution(
        dose_comparison_trial(),
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=generation_id,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
    )

    assert run.population_count == POPULATION_SIZE
    assert len(run.arms) == 3
    assert sum(arm_result.participant_count for arm_result in run.arms) == POPULATION_SIZE

    allocation_store = TrialArmAllocationArtifactStore(
        run.run_directory / "allocation", population_store=population_store
    )
    allocation_manifest = allocation_store.verify_allocation(run.allocation_id)
    assert allocation_manifest.total_population == POPULATION_SIZE
    assert sum(allocation_manifest.arm_counts.values()) == POPULATION_SIZE

    cmax_means = {}
    for arm_result in run.arms:
        cmax_values = [
            endpoint.value for endpoint in arm_result.endpoints if endpoint.endpoint_type == "CMAX"
        ]
        cmax_means[arm_result.arm_id] = sum(cmax_values) / len(cmax_values)

    print(
        "\nLive 3-arm trial proof -- mean Cmax by arm "
        f"(n={[a.participant_count for a in run.arms]}):",
        {arm_id: round(mean, 4) for arm_id, mean in cmax_means.items()},
    )
    # Distinct verified doses (125/250/375 mg) through the same PBPK model must
    # produce distinct simulated mean exposures -- not a claim about which
    # direction, just that the arms are genuinely different executions.
    assert len(set(round(value, 6) for value in cmax_means.values())) == 3


def _assumed_min(value: float) -> ScientificValue:
    return assumed(value, "min")


def test_prospective_trial_with_declared_observation_schedule(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    population_manifest = generate_and_persist_population(population_store, r_libs_user)
    generation_id = population_manifest.generation_id

    # A realistic dense-then-sparse IV sampling protocol: q15min through the
    # rising/peak phase (infusion ends at 10 min), then q60min through decline.
    schedule = ObservationSchedule(
        schedule_id="dense-then-sparse",
        time_unit="min",
        windows=(
            SamplingWindow(
                start=_assumed_min(0), end=_assumed_min(60), interval=_assumed_min(15)
            ),
            SamplingWindow(
                start=_assumed_min(60), end=_assumed_min(480), interval=_assumed_min(60)
            ),
        ),
    )
    expected_times = schedule.declared_times()

    run = run_trial_execution(
        dose_comparison_trial(),
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=generation_id,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
        observation_schedule=schedule,
    )

    assert run.population_count == POPULATION_SIZE
    # The declared schedule must be exactly what every arm's persisted
    # normalized concentration-time artifact actually contains -- not merely
    # what the orchestration claimed to request.
    for arm_result in run.arms:
        table = pq.read_table(arm_result.result_directory / "concentration_time.parquet")
        rows = table.to_pylist()
        first_subject = rows[0]["subject_id"]
        actual_times = sorted({row["time"] for row in rows if row["subject_id"] == first_subject})
        assert actual_times == list(expected_times)

    print(
        "\nLive schedule proof -- declared sample times (min):",
        expected_times,
        "-- verified present in every arm's normalized concentration-time artifact.",
    )


def test_complete_prospective_multi_arm_trial_with_schedule_and_provenance_chain(
    tmp_path: Path,
) -> None:
    """The v0.5-C live proof: A (allocation) + B (schedule) + comparison + OTTRIAL, composed."""
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    population_manifest = generate_and_persist_population(population_store, r_libs_user)
    generation_id = population_manifest.generation_id

    schedule = ObservationSchedule(
        schedule_id="dense-then-sparse",
        time_unit="min",
        windows=(
            SamplingWindow(
                start=_assumed_min(0), end=_assumed_min(60), interval=_assumed_min(15)
            ),
            SamplingWindow(
                start=_assumed_min(60), end=_assumed_min(480), interval=_assumed_min(60)
            ),
        ),
    )
    expected_times = schedule.declared_times()
    assert len(expected_times) == 12

    trial = dose_comparison_trial()
    run = run_trial_execution(
        trial,
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=generation_id,
        population_root=population_root,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
        observation_schedule=schedule,
    )

    # N source participants = 30
    assert run.population_count == POPULATION_SIZE
    arm_ids = {arm_result.arm_id for arm_result in run.arms}
    assert arm_ids == {"low", "standard", "high"}

    allocation_store = TrialArmAllocationArtifactStore(
        run.run_directory / "allocation", population_store=population_store
    )
    allocation_manifest = allocation_store.verify_allocation(run.allocation_id)
    assert allocation_manifest.total_population == POPULATION_SIZE

    # union(all arms) = all 30 participants; intersection(any two arms) = empty;
    # each participant occurs exactly once.
    index_sets = {
        arm_id: {
            row["source_row_index"]
            for row in allocation_store.read_rows_for_arm(run.allocation_id, arm_id)
        }
        for arm_id in arm_ids
    }
    assert set().union(*index_sets.values()) == set(range(POPULATION_SIZE))
    assert sum(len(indexes) for indexes in index_sets.values()) == POPULATION_SIZE
    for arm_a, arm_b in itertools.combinations(index_sets, 2):
        assert index_sets[arm_a] & index_sets[arm_b] == set()

    # assigned population for each arm = population actually executed in that arm.
    endpoint_stores: dict[str, PkEndpointArtifactStore] = {}
    for arm_result in run.arms:
        endpoint_store = PkEndpointArtifactStore(
            run.run_directory / "arms" / arm_result.arm_id / "endpoints"
        )
        endpoint_stores[arm_result.arm_id] = endpoint_store
        endpoint_manifest = endpoint_store.verify_endpoints(arm_result.endpoint_id)
        assert endpoint_manifest.population_lineage_present is True
        assert endpoint_manifest.source_generation_id == generation_id
        rows = endpoint_store.read_rows(arm_result.endpoint_id)
        executed_indexes = {row["source_population_row_index"] for row in rows}
        assert executed_indexes == index_sets[arm_result.arm_id]

    # requested dose + administration state read back correctly from OSP, per arm.
    for arm_result in run.arms:
        raw_path = run.run_directory / "arms" / arm_result.arm_id / "raw" / "osp_response.json"
        # SchemaDocument.payload holds the dumped RawSimulationResult, whose own
        # "payload" field is the raw OSP response -- hence payload.payload.
        raw_envelope = json.loads(raw_path.read_text(encoding="utf-8"))
        verification = raw_envelope["payload"]["payload"]["execution_verification"]
        assert verification["model_hash_verification"]["verified"] is True
        assert verification["route_container_verification"]["verified"] is True
        assert verification["solver_executed"] is True
        assert all(item["verified"] is True for item in verification["parameter_assignments"])
        dose_assignment = next(
            item for item in verification["parameter_assignments"] if "Dose" in item["path"]
        )
        assert dose_assignment["executed"]["value"] == pytest.approx(
            arm_result.dose_mg / 1_000_000
        )

    # requested observation schedule verified against solver state/output, per arm.
    for arm_result in run.arms:
        table = pq.read_table(arm_result.result_directory / "concentration_time.parquet")
        rows = table.to_pylist()
        first_subject = rows[0]["subject_id"]
        actual_times = sorted({row["time"] for row in rows if row["subject_id"] == first_subject})
        assert actual_times == list(expected_times)

    # comparisons consume the actual prospectively generated arm outcomes.
    comparison_store = ArmComparisonArtifactStore(run.run_directory / "comparison")
    comparison_manifest = comparison_store.verify_comparison(run.comparison_id)
    assert comparison_manifest.arm_endpoint_ids == {
        arm_result.arm_id: arm_result.endpoint_id for arm_result in run.arms
    }
    assert comparison_manifest.arm_summaries.rows == 9  # 3 arms x 3 endpoint types
    assert comparison_manifest.pairwise_comparisons.rows == 9  # C(3,2) pairs x 3 endpoint types

    # All persisted artifacts verify after reload -- the authoritative OTTRIAL check.
    trial_run_store = TrialRunArtifactStore(run.run_directory / "trial_run")
    verified = trial_run_store.verify_trial_run(
        run.trial_run_id,
        population_store=population_store,
        allocation_store=allocation_store,
        endpoint_stores=endpoint_stores,
        comparison_store=comparison_store,
    )
    assert verified.trial_id == trial.trial_id
    assert verified.source_generation_id == generation_id
    assert verified.allocation_id == run.allocation_id
    assert verified.comparison_id == run.comparison_id
    assert verified.observation_schedule is not None
    assert tuple(verified.observation_schedule.declared_times_min) == expected_times
    assert {arm_record.arm_id for arm_record in verified.arms} == arm_ids
    assert all(arm_record.observation_schedule_verified is True for arm_record in verified.arms)
    assert sum(arm_record.participant_count for arm_record in verified.arms) == POPULATION_SIZE

    cmax_by_arm = {}
    for arm_result in run.arms:
        cmax_values = [
            endpoint.value for endpoint in arm_result.endpoints if endpoint.endpoint_type == "CMAX"
        ]
        cmax_by_arm[arm_result.arm_id] = sum(cmax_values) / len(cmax_values)
    print(
        "\nLive v0.5-C proof -- OTTRIAL",
        run.trial_run_id,
        "mean Cmax by arm:",
        {arm_id: round(mean, 4) for arm_id, mean in cmax_by_arm.items()},
    )
