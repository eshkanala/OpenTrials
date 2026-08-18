"""Opt-in live proof: prospective virtual trial across declared physiological states.

The v0.6-B milestone: the same source OTPGEN population and the same
intervention/dose/route/observation schedule executed at three declared
GFR states (baseline, moderate, severe), producing lineage-matched,
independently re-verifiable cross-state PK comparisons and one immutable
top-level OTPHYTRIAL provenance record. Per explicit project direction, no
assertion is made on the *direction* of the AUC/GFR relationship -- it is
printed, not asserted, and no CKD/disease-stage language is used anywhere.
"""

from __future__ import annotations

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
from opentrials.analysis.descriptive import DescriptiveSummary
from opentrials.analysis.physiology_comparison import PhysiologyStateEndpointSummary
from opentrials.analysis.pk import PkEndpointType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_physiology_trial import (
    PhysiologyStateDeclaration,
    run_aciclovir_iv_physiology_trial,
)
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.storage import (
    PhysiologyComparisonArtifactStore,
    PhysiologyPopulationArtifactStore,
    PhysiologyTrialArtifactStore,
    PkEndpointArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)
from opentrials.trials.schedule import ObservationSchedule, SamplingWindow

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 30
GENERATION_ID = "OTPGEN-physiology-trial-live-proof"
TARGET = "renal.glomerular_filtration_rate"
STATES = (("baseline", 1.0), ("moderate", 0.6), ("severe", 0.3))


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="physiology-trial-live-proof",
        size=POPULATION_SIZE,
        seed=23,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(30, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    translated = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translated)
    store.create_generation(GENERATION_ID)
    return store.write_population(
        GENERATION_ID,
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


def declared_schedule() -> ObservationSchedule:
    return ObservationSchedule(
        schedule_id="physiology-trial-live-proof-schedule",
        time_unit="min",
        windows=(
            SamplingWindow(
                start=assumed(0, "min"), end=assumed(240, "min"), interval=assumed(30, "min")
            ),
        ),
    )


def test_prospective_physiology_state_trial_with_paired_comparison_and_provenance(
    tmp_path: Path,
) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    physiology_root = tmp_path / "physiology"
    population_store = PopulationArtifactStore(population_root)
    generate_and_persist_population(population_store, r_libs_user)

    schedule = declared_schedule()
    declared_times = schedule.declared_times()

    states = tuple(
        PhysiologyStateDeclaration(
            state_id=state_id,
            override=PhysiologicalStateOverride(
                target=TARGET,
                scale_factor=scale_factor,
                unit="L/min",
                purpose=f"v0.6-B live proof declared state: {state_id}",
            ),
        )
        for state_id, scale_factor in STATES
    )

    result = run_aciclovir_iv_physiology_trial(
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        physiology_root=physiology_root,
        states=states,
        baseline_state_id="baseline",
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
        observation_schedule=schedule,
    )

    assert set(result.state_ids) == {state_id for state_id, _ in STATES}

    # Each OTPHYS independently verifies, and every state's declared
    # observation schedule was actually applied and read back correctly.
    physiology_store = PhysiologyPopulationArtifactStore(physiology_root)
    for state_id, _ in STATES:
        physiology_store.verify_physiology_population(f"OTPHYS-{result.run_id.removeprefix('OTR-')}-{state_id}")

    # OTPHYCMP re-verifies and contains the required comparison shape.
    comparison_store = PhysiologyComparisonArtifactStore(result.run_directory / "comparison")
    comparison_manifest = comparison_store.verify_comparison(result.comparison_id)
    assert comparison_manifest.missingness.expected_subject_count == POPULATION_SIZE
    assert comparison_manifest.missingness.complete_subject_count == POPULATION_SIZE
    assert comparison_manifest.missingness.excluded_subject_ids == ()
    assert comparison_manifest.coverage.modeled == ("renal.glomerular_filtration",)
    assert comparison_manifest.state_summaries.rows > 0
    assert comparison_manifest.subject_deltas.rows > 0

    # OTPHYTRIAL: complete reload and re-verification from each sub-artifact's
    # own store -- fresh store objects, not the in-memory results above.
    trial_run_store = PhysiologyTrialArtifactStore(result.run_directory / "trial_run")
    trial_manifest = trial_run_store.read_manifest(result.trial_run_id)
    assert len(trial_manifest.states) == 3
    endpoint_stores: dict[str, PkEndpointArtifactStore] = {}
    for state in trial_manifest.states:
        run_directory = result.run_directory / "states" / state.executed_run_id
        endpoint_stores[state.state_id] = PkEndpointArtifactStore(run_directory / "endpoints")
        # Executed GFR state verified rather than trusted.
        assert state.physiology_state_verified is True
        # Declared observation schedule verified rather than trusted.
        assert state.observation_schedule_verified is True
        endpoint_manifest = endpoint_stores[state.state_id].verify_endpoints(state.endpoint_id)
        assert endpoint_manifest.population_lineage_present is True
        # Solver output grid matches the declared schedule exactly.
        concentration_time_path = (
            run_directory / "normalized" / state.result_id / "concentration_time.parquet"
        )
        observed_times = sorted(
            {float(row["time"]) for row in pq.read_table(concentration_time_path).to_pylist()}
        )
        assert observed_times == sorted(declared_times)

    verified_trial = PhysiologyTrialArtifactStore(
        result.run_directory / "trial_run"
    ).verify_physiology_trial(
        result.trial_run_id,
        population_store=PopulationArtifactStore(population_root),
        physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
        endpoint_stores=endpoint_stores,
        comparison_store=PhysiologyComparisonArtifactStore(result.run_directory / "comparison"),
    )
    assert verified_trial.baseline_state_id == "baseline"

    # Same subject, identical lineage, across every state -- read directly.
    lineage_by_state: dict[str, dict[str, tuple[int, str]]] = {}
    for state in trial_manifest.states:
        rows = endpoint_stores[state.state_id].read_rows(state.endpoint_id)
        lineage_by_state[state.state_id] = {
            str(row["subject_id"]): (
                int(row["source_population_row_index"]),
                str(row["source_population_row_sha256"]),
            )
            for row in rows
        }
    reference = lineage_by_state["baseline"]
    for state_id, _ in STATES[1:]:
        assert lineage_by_state[state_id] == reference

    # Report the observed AUC trend -- not asserted as a software invariant.
    auc_by_state = {
        summary.state_id: summary.summary.mean
        for summary in (
            summary
            for summary in _read_state_summaries(comparison_store, result.comparison_id)
            if summary.endpoint_type == PkEndpointType.AUC_0_LAST
        )
    }
    print(
        "\nLive v0.6-B proof -- mean AUC_0_LAST by declared state (reported, not asserted):",
        auc_by_state,
    )


def _read_state_summaries(
    store: PhysiologyComparisonArtifactStore, comparison_id: str
) -> list[PhysiologyStateEndpointSummary]:
    manifest = store.read_manifest(comparison_id)
    table = pq.read_table(store.root / comparison_id / manifest.state_summaries.path)
    return [
        PhysiologyStateEndpointSummary(
            state_id=str(row["state_id"]),
            endpoint_type=PkEndpointType(row["endpoint_type"]),
            unit=str(row["unit"]),
            n=int(row["n"]),
            summary=DescriptiveSummary(
                n=int(row["n"]),
                mean=float(row["mean"]),
                sample_standard_deviation=row["sample_standard_deviation"],
                coefficient_of_variation=row["coefficient_of_variation"],
                minimum=float(row["minimum"]),
                maximum=float(row["maximum"]),
                p25=float(row["p25"]),
                p50=float(row["p50"]),
                p75=float(row["p75"]),
            ),
        )
        for row in table.to_pylist()
    ]
