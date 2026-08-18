"""Opt-in live proof: OTPGEN -> OTPHYS (renal GFR override) -> PBPK -> OTPK v2.

The v0.6-A capability probe (see HANDOFF.md) established that `ospsuite-R`
exposes no disease/impairment population API, but the pinned Aciclovir model
carries a real, physiologically meaningful per-individual GFR parameter
(``Organism|Kidney|GFRmat``) that is already a standard population-table
column, safely scalable, and round-trip-safe. This test is the permanent
live proof of that capability: the same source individuals executed at
three declared GFR states, with identical lineage preserved across all
three, and the observed AUC trend reported -- not asserted as a hard
software invariant, per explicit project direction (dose/state-response
direction is a scientific observation, not a thing a software test should
require).
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
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.orchestration.physiology_population_execution import (
    build_physiology_population,
    run_physiology_population_execution,
)
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.storage import (
    PhysiologyPopulationArtifactStore,
    PkEndpointArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

pytestmark = pytest.mark.osp_integration

POPULATION_SIZE = 6
GENERATION_ID = "OTPGEN-physiology-live-proof"
TARGET = "renal.glomerular_filtration_rate"
GFR_COLUMN = "Organism|Kidney|GFRmat"
STATES = (("OTPHYS-healthy", 1.0), ("OTPHYS-moderate", 0.6), ("OTPHYS-severe", 0.3))


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def generate_and_persist_population(
    store: PopulationArtifactStore, r_libs_user: str
) -> PopulationArtifactManifest:
    specification = PopulationSpec(
        id="physiology-live-proof",
        size=POPULATION_SIZE,
        seed=17,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(35, "year"), maximum=assumed(55, "year")),
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


def test_renal_gfr_override_executes_at_three_states_with_identical_lineage(
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
    physiology_store = PhysiologyPopulationArtifactStore(physiology_root)

    population_manifest = generate_and_persist_population(population_store, r_libs_user)
    source_table = pq.read_table(
        population_root / GENERATION_ID / population_manifest.individuals.path
    )
    source_gfr_by_id = {
        int(row["IndividualId"]): float(row[GFR_COLUMN]) for row in source_table.to_pylist()
    }

    endpoint_stores: dict[str, PkEndpointArtifactStore] = {}
    endpoint_ids: dict[str, str] = {}
    lineage_identity: dict[str, tuple[str, str]] = {}
    mean_auc_by_state: dict[str, float] = {}

    for physiology_population_id, scale_factor in STATES:
        physiology_manifest = build_physiology_population(
            model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_generation_id=GENERATION_ID,
            population_root=population_root,
            override=PhysiologicalStateOverride(
                target=TARGET,
                scale_factor=scale_factor,
                unit="L/min",
                purpose="v0.6-A live proof: renal glomerular-filtration-rate perturbation",
            ),
        )
        # GFR values read back correctly: every row in the persisted OTPHYS
        # table matches scale_factor times its exact source OTPGEN value.
        physiology_table = pq.read_table(
            physiology_root / physiology_population_id / physiology_manifest.individuals.path
        )
        for row in physiology_table.to_pylist():
            individual_id = int(row["IndividualId"])
            expected = source_gfr_by_id[individual_id] * scale_factor
            assert row[GFR_COLUMN] == pytest.approx(expected, rel=1e-9)

        # All three verify.
        assert physiology_store.verify_physiology_population(
            physiology_population_id
        ) == physiology_manifest

        run = run_physiology_population_execution(
            model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
            physiology_population_id=physiology_population_id,
            physiology_root=physiology_root,
            population_root=population_root,
            dose_mg=250.0,
            output_root=tmp_path / "runs" / physiology_population_id,
            r_libs_user=r_libs_user,
        )
        assert run.source_generation_id == GENERATION_ID
        assert run.population_count == POPULATION_SIZE
        assert len({endpoint.subject_id for endpoint in run.endpoints}) == POPULATION_SIZE

        endpoint_store = PkEndpointArtifactStore(run.run_directory / "endpoints")
        endpoint_id = run.endpoint_directory.name
        endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
        endpoint_stores[physiology_population_id] = endpoint_store
        endpoint_ids[physiology_population_id] = endpoint_id

        # Same source subjects retain identical lineage across every state.
        lineage_identity[physiology_population_id] = (
            endpoint_manifest.source_generation_id or "",
            endpoint_manifest.source_population_semantic_sha256 or "",
        )

        auc_values = [
            endpoint.value
            for endpoint in run.endpoints
            if endpoint.endpoint_type.value == "AUC_0_LAST"
        ]
        mean_auc_by_state[physiology_population_id] = sum(auc_values) / len(auc_values)

    # All three produce distinct endpoint artifacts.
    assert len(set(endpoint_ids.values())) == 3

    # Same source subjects retain identical lineage -- not merely "some
    # OTPGEN", but literally the same generation id and population hash.
    distinct_lineage_identities = set(lineage_identity.values())
    assert len(distinct_lineage_identities) == 1

    # Per-subject row identity is also identical across states: verify by
    # reading each endpoint artifact's raw lineage columns directly.
    per_state_row_identity: dict[str, dict[str, tuple[int, str]]] = {}
    for physiology_population_id in endpoint_ids:
        rows = endpoint_stores[physiology_population_id].read_rows(
            endpoint_ids[physiology_population_id]
        )
        per_state_row_identity[physiology_population_id] = {
            str(row["subject_id"]): (
                int(row["source_population_row_index"]),
                str(row["source_population_row_sha256"]),
            )
            for row in rows
        }
    reference_identity = per_state_row_identity[STATES[0][0]]
    for physiology_population_id, _ in STATES[1:]:
        assert per_state_row_identity[physiology_population_id] == reference_identity

    print(
        "\nLive v0.6-A proof -- mean AUC_inf by declared GFR scale factor "
        "(reported, not asserted):",
        {label: f"{scale}x -> {mean_auc_by_state[label]:.2f}" for label, scale in STATES},
    )
