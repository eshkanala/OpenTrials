"""Opt-in integration proof for the installed local OSP population generator."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentrials.adapters.osp import (
    OspDeterminismLevel,
    OspHumanPopulation,
    OspPopulationGenerationResult,
    OspPopulationGenerator,
    OspPopulationProfile,
    OspPopulationTranslation,
    OspPopulationTranslator,
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.storage import (
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

pytestmark = pytest.mark.osp_integration


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def translation(seed: int):
    specification = PopulationSpec(
        id="osp-reproducibility-proof",
        size=10,
        seed=seed,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    return OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)


def persist_population(
    store: PopulationArtifactStore,
    generation_id: str,
    result: OspPopulationGenerationResult,
    translated: OspPopulationTranslation,
) -> PopulationArtifactManifest:
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


def test_osp_population_seed_is_exactly_reproducible(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    first_translation = translation(42)
    second_translation = translation(42)
    first = generator.generate(first_translation)
    second = generator.generate(second_translation)
    different_seed = generator.generate(translation(43))
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation("OTPGEN-first")
    store.create_generation("OTPGEN-second")
    first_manifest = persist_population(store, "OTPGEN-first", first, first_translation)
    second_manifest = persist_population(store, "OTPGEN-second", second, second_translation)
    first_reloaded = store.verify_population("OTPGEN-first")
    second_reloaded = store.verify_population("OTPGEN-second")

    assert first.engine_seed == second.engine_seed == 42
    assert different_seed.engine_seed == 43
    assert first.determinism_level is OspDeterminismLevel.STRICT
    assert first.raw_rows == second.raw_rows
    assert first.raw_rows != different_seed.raw_rows
    assert first_manifest.generation_id != second_manifest.generation_id
    assert first_reloaded.individuals.semantic_content_sha256 == (
        second_reloaded.individuals.semantic_content_sha256
    )
