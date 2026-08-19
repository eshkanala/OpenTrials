"""Opt-in live proof: v0.7-C's second registered model runs through the
unmodified generic execution pipeline.

This is the acceptance bar v0.7-B set for itself: registering a second,
sufficiently different model should mean touching only a new
``models/profiles/<model>.py`` and its own live test here -- never
``orchestration.population_execution``, ``adapters.osp.capability``, or
``adapters.osp.physiology_targets``. Nothing in this file imports or
patches any of those; it calls ``run_population_execution`` exactly the
way ``test_osp_population_pbpk_execution.py`` already does for aciclovir,
substituting only the registered profile and its own verified dose.
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
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.midazolam_po import MIDAZOLAM_PO_CAPABILITY_PROFILE
from opentrials.orchestration.population_execution import run_population_execution
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.storage import (
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 5
VERIFIED_DOSE_MG = 10.0


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="midazolam-po-live-proof",
        size=POPULATION_SIZE,
        seed=7,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.MALE,),
    )
    translated = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)
    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    result = generator.generate(translated)
    generation_id = "OTPGEN-midazolam-po-live-proof"
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


def test_midazolam_po_runs_through_the_unmodified_generic_pipeline(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    manifest = generate_and_persist_population(population_store, r_libs_user)
    generation_id = manifest.generation_id

    run = run_population_execution(
        model_capability_profile=MIDAZOLAM_PO_CAPABILITY_PROFILE,
        population_generation_id=generation_id,
        population_root=population_root,
        dose_mg=VERIFIED_DOSE_MG,
        output_root=tmp_path / "runs",
        r_libs_user=r_libs_user,
    )

    assert run.population_count == POPULATION_SIZE
    assert len({endpoint.subject_id for endpoint in run.endpoints}) == POPULATION_SIZE
    assert len(run.endpoints) == POPULATION_SIZE * 3  # Cmax, Tmax, AUC per subject
    assert all(endpoint.value >= 0 for endpoint in run.endpoints)

    endpoint_store = run.endpoint_directory
    assert endpoint_store.is_dir()

    cmax_values = [e.value for e in run.endpoints if e.endpoint_type.value == "CMAX"]
    print(
        "\nLive Midazolam (oral, 10 mg tablet) proof -- Cmax across "
        f"{POPULATION_SIZE} subjects:",
        f"mean={sum(cmax_values) / len(cmax_values):.4f} umol/L",
        f"min={min(cmax_values):.4f}",
        f"max={max(cmax_values):.4f}",
    )
