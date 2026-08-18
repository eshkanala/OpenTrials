"""Opt-in live proof: CSV transport (v0.6-C) produces scientifically equivalent results to JSON.

The hard invariant for v0.6-C: replacing the Python<->R population/result
transport must not change any scientific conclusion. This test executes the
*same* verified OTPGEN population through the *same* pinned model and dose
twice -- once over each transport -- and compares logical content, not
transport bytes.

One honest, quantified difference was found and is asserted here rather than
hidden: OSP's own ``exportResultsToCSV()`` writes values at a fixed ~7
significant-figure text precision (confirmed not configurable via R's
``options(digits=)``), while the JSON path's ``jsonlite`` serialization
preserves full float64 precision. The observed relative difference is on the
order of 1e-7 -- far below any biologically or clinically meaningful
digit for a descriptive PK simulation, but real, so this test bounds it
explicitly (``rel=1e-6``) instead of asserting byte-for-byte equality. OTRES/
OTPK *semantic* content hashes are therefore expected to differ slightly
between transports and are not asserted equal; endpoint values are compared
directly instead.
"""

from __future__ import annotations

import json
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
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
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
GENERATION_ID = "OTPGEN-csv-transport-equivalence"


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="csv-transport-equivalence",
        size=POPULATION_SIZE,
        seed=11,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(25, "year"), maximum=assumed(60, "year")),
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


def test_csv_and_json_transport_produce_identical_scientific_results(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    population_root = tmp_path / "populations"
    population_store = PopulationArtifactStore(population_root)
    generate_and_persist_population(population_store, r_libs_user)

    json_run = run_population_execution(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs-json",
        r_libs_user=r_libs_user,
        transport="json",
    )
    csv_run = run_population_execution(
        model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        dose_mg=250.0,
        output_root=tmp_path / "runs-csv",
        r_libs_user=r_libs_user,
        transport="csv",
    )

    assert json_run.population_count == csv_run.population_count == POPULATION_SIZE
    assert {e.subject_id for e in json_run.endpoints} == {e.subject_id for e in csv_run.endpoints}
    assert len(json_run.endpoints) == len(csv_run.endpoints)

    # Endpoint values must agree within exportResultsToCSV's known ~7
    # significant-figure text precision (see module docstring) -- a bound,
    # not byte-for-byte equality, since the two transports genuinely write
    # floating-point text at different precision.
    json_by_key = {
        (e.subject_id, e.endpoint_type): e.value for e in json_run.endpoints
    }
    csv_by_key = {(e.subject_id, e.endpoint_type): e.value for e in csv_run.endpoints}
    assert set(json_by_key) == set(csv_by_key)
    max_relative_difference = 0.0
    for key, json_value in json_by_key.items():
        csv_value = csv_by_key[key]
        assert csv_value == pytest.approx(json_value, rel=1e-6), (
            f"{key}: json={json_value} csv={csv_value}"
        )
        if json_value != 0.0:
            max_relative_difference = max(
                max_relative_difference, abs(csv_value - json_value) / abs(json_value)
            )

    # OTRES/OTPK semantic content hashes are expected to differ slightly for
    # the same reason -- they are logged, not asserted equal.
    json_result_manifest = json.loads(
        (json_run.result_directory / "manifest.json").read_text(encoding="utf-8")
    )["payload"]
    csv_result_manifest = json.loads(
        (csv_run.result_directory / "manifest.json").read_text(encoding="utf-8")
    )["payload"]
    json_semantic_hash = json_result_manifest["concentration_time"]["semantic_content_sha256"]
    csv_semantic_hash = csv_result_manifest["concentration_time"]["semantic_content_sha256"]

    print(
        "\nLive v0.6-C equivalence proof: JSON and CSV transport agree within "
        f"rel<=1e-6 on every endpoint value for N={POPULATION_SIZE} "
        f"(observed max relative difference: {max_relative_difference:.2e}). "
        f"OTRES semantic hashes: json={json_semantic_hash[:16]}... "
        f"csv={csv_semantic_hash[:16]}... (expected to differ, per exportResultsToCSV's "
        "text precision)."
    )
