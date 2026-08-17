"""Opt-in live proof: OTPGEN -> population-linked PBPK -> OTPK v2 -> OTCPK.

This is the "live v0.4-B" proof: a real OSP-generated population, executed as
one batched runSimulations() call with preserved row lineage, compared across
two real OTMEM cohorts derived from the actual generated ages.
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
    osp_population_field_catalog,
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.cohort import (
    CohortDefinition,
    CohortMembershipArtifactStore,
    NumericOperator,
    NumericPredicate,
    compare_cohort_pk_endpoints,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.orchestration.aciclovir_iv_population import run_aciclovir_iv_population
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.storage import (
    CohortPkComparisonArtifactStore,
    PkEndpointArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 5


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="otcpk-live-proof",
        size=POPULATION_SIZE,
        seed=99,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(70, "year")),
        sexes=(Sex.FEMALE,),
    )
    translated = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translated)
    generation_id = "OTPGEN-otcpk-live-proof"
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


def age_split_cohorts(
    membership_store: CohortMembershipArtifactStore,
    *,
    generation_id: str,
    population_semantic_sha256: str,
    median_age: float,
) -> None:
    catalog = osp_population_field_catalog()
    for membership_id, cohort_id, operator in (
        ("OTMEM-younger", "OTCOH-younger", NumericOperator.LT),
        ("OTMEM-older", "OTCOH-older", NumericOperator.GTE),
    ):
        membership_store.create_membership(membership_id)
        membership_store.write_membership(
            membership_id,
            definition=CohortDefinition(
                cohort_id=cohort_id,
                predicates=(
                    NumericPredicate(
                        field_id="demographics.age",
                        operator=operator,
                        value=median_age,
                        unit="year",
                    ),
                ),
                source_generation_id=generation_id,
                source_population_semantic_sha256=population_semantic_sha256,
                field_catalog_sha256=catalog.canonical_sha256(),
            ),
            field_catalog=catalog,
        )


def test_population_linked_pbpk_execution_and_live_cohort_comparison(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    manifest = generate_and_persist_population(population_store, r_libs_user)
    generation_id = manifest.generation_id

    run = run_aciclovir_iv_population(
        population_generation_id=generation_id,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
    )

    assert run.population_count == POPULATION_SIZE
    assert len({endpoint.subject_id for endpoint in run.endpoints}) == POPULATION_SIZE
    assert len(run.endpoints) == POPULATION_SIZE * 3  # Cmax, Tmax, AUC per subject

    population_table = pq.read_table(population_root / generation_id / "individuals.parquet")
    ages = sorted(float(row["Organism|Age"]) for row in population_table.to_pylist())
    median_age = ages[len(ages) // 2]

    membership_store = CohortMembershipArtifactStore(tmp_path / "memberships", population_store)
    age_split_cohorts(
        membership_store,
        generation_id=generation_id,
        population_semantic_sha256=manifest.individuals.semantic_content_sha256,
        median_age=median_age,
    )

    endpoint_store = PkEndpointArtifactStore(run.run_directory / "endpoints")
    endpoint_id = run.endpoint_directory.name

    result = compare_cohort_pk_endpoints(
        group_a_membership_id="OTMEM-younger",
        group_b_membership_id="OTMEM-older",
        group_a_label="Younger",
        group_b_label="Older",
        endpoint_id=endpoint_id,
        membership_store=membership_store,
        endpoint_store=endpoint_store,
    )

    assert result.overlap.overlap_n == 0
    assert result.overlap.group_a_n + result.overlap.group_b_n == POPULATION_SIZE
    assert result.overlap.group_a_n > 0
    assert result.overlap.group_b_n > 0
    assert result.group_summaries
    assert result.comparisons
    assert all(summary.n_matched == summary.n_members for summary in result.group_summaries)

    comparison_store = CohortPkComparisonArtifactStore(tmp_path / "comparisons")
    comparison_store.create_comparison("OTCPK-live-proof")
    comparison_manifest = comparison_store.write_comparison("OTCPK-live-proof", result)
    assert comparison_store.verify_comparison("OTCPK-live-proof") == comparison_manifest

    cmax_comparison = next(
        c for c in result.comparisons if c.endpoint_type.value == "CMAX"
    )
    print(
        "\nLive OTCPK proof -- Cmax younger vs older:",
        f"A(n={result.overlap.group_a_n})={cmax_comparison.group_a_mean:.4f}",
        f"B(n={result.overlap.group_b_n})={cmax_comparison.group_b_mean:.4f}",
        f"abs_diff={cmax_comparison.absolute_difference:.4f}",
    )
