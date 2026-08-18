"""Opt-in live proof: OTPGEN -> population PBPK -> OTPK v2 -> extreme responders.

The v0.4-C live proof: a real N=100 OSP-generated population executed through
PBPK, then the top 10% AUC responders identified and compared against the
reference group's baseline physiology -- purely descriptively.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentrials.adapters.osp import (
    OspHumanPopulation,
    OspPopulationGenerator,
    OspPopulationProfile,
    OspPopulationTranslator,
    osp_population_field_catalog,
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.analysis.pk import PkEndpointType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.orchestration.population_execution import run_population_execution
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.responders import ExtremeResponderDefinition, SelectionMethod, TiePolicy
from opentrials.responders.orchestration import run_extreme_responder_analysis
from opentrials.storage import (
    PkEndpointArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
    ResponderComparisonArtifactStore,
)

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 100
TOP_PERCENTILE = 10.0


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="responder-live-proof",
        size=POPULATION_SIZE,
        seed=7,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    translated = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translated)
    generation_id = "OTPGEN-responder-live-proof"
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


def test_extreme_responders_identified_and_compared_against_real_pbpk_population(
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

    run = run_population_execution(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=generation_id,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
    )
    assert run.population_count == POPULATION_SIZE

    endpoint_store = PkEndpointArtifactStore(run.run_directory / "endpoints")
    endpoint_id = run.endpoint_directory.name
    endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)

    definition = ExtremeResponderDefinition(
        definition_id="OTRESP-live-top-auc",
        source_endpoint_id=endpoint_id,
        source_endpoint_semantic_sha256=endpoint_manifest.endpoints.semantic_content_sha256,
        source_generation_id=generation_id,
        source_population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
        endpoint_type=PkEndpointType.AUC_0_LAST,
        method=SelectionMethod.TOP_PERCENTILE,
        percentile=TOP_PERCENTILE,
        count=None,
        tie_policy=TiePolicy.STRICT_COUNT,
    )

    analysis = run_extreme_responder_analysis(
        definition=definition,
        extreme_label=f"Top {TOP_PERCENTILE:g}% AUC responders",
        reference_label="Reference",
        baseline_field_ids=(
            "demographics.age",
            "physiology.weight",
            "physiology.height",
            "physiology.bmi",
            "demographics.sex",
        ),
        field_catalog=osp_population_field_catalog(),
        endpoint_store=endpoint_store,
        population_store=population_store,
        membership_root=tmp_path / "memberships",
        comparison_root=tmp_path / "comparisons",
    )

    assert analysis.extreme_manifest.members.rows == 10  # ceil(100 * 10%)
    assert analysis.reference_manifest.members.rows == 90
    assert analysis.extreme_manifest.total_population == 100

    comparison_store = ResponderComparisonArtifactStore(tmp_path / "comparisons")
    reloaded = comparison_store.verify_comparison(analysis.comparison_id)
    assert reloaded == analysis.comparison_manifest

    age_comparison = next(
        c
        for c in analysis.comparison_result.numeric_comparisons
        if c.field_id == "demographics.age"
    )
    weight_comparison = next(
        c
        for c in analysis.comparison_result.numeric_comparisons
        if c.field_id == "physiology.weight"
    )
    print(
        "\nLive extreme-responder proof -- top "
        f"{TOP_PERCENTILE:g}% AUC (n=10) vs reference (n=90):",
        f"age {age_comparison.extreme_mean:.2f}y vs {age_comparison.reference_mean:.2f}y",
        f"(diff {age_comparison.absolute_difference:+.2f}y);",
        f"weight {weight_comparison.extreme_mean:.2f}kg vs {weight_comparison.reference_mean:.2f}kg"
        f" (diff {weight_comparison.absolute_difference:+.2f}kg)",
    )
    assert "Does not imply causation" in analysis.comparison_result.interpretation_note
