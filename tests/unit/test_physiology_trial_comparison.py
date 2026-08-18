"""Contract tests for the paired cross-physiology-state PK comparison join."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.adapters.osp import physiology_coverage_for, resolve_osp_physiology_column
from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.core.serialization import document, sha256
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.storage import (
    PhysiologyPopulationArtifactStore,
    PkEndpointArtifactStore,
    PkEndpointSubjectLineage,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)
from opentrials.storage.row_identity import source_row_sha256
from opentrials.trials.physiology_comparison import compare_physiology_states

GFR_COLUMN = "Organism|Kidney|GFRmat"
COLUMNS = ("IndividualId", "Organism|Age", GFR_COLUMN)
GENERATION_ID = "OTPGEN-physio-cmp-test"
TARGET = "renal.glomerular_filtration_rate"
RESULT_HASH = sha256({"fixture": "physiology-comparison"})


def source_rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Organism|Age": 40.0, GFR_COLUMN: 0.10},
        {"IndividualId": 1, "Organism|Age": 50.0, GFR_COLUMN: 0.12},
        {"IndividualId": 2, "Organism|Age": 60.0, GFR_COLUMN: 0.09},
    )


def build_population(tmp_path: Path) -> tuple[Path, PopulationArtifactManifest]:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    manifest = store.write_population(
        GENERATION_ID,
        population_id="physio-cmp-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "physio-cmp-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=3,
        column_names=COLUMNS,
        rows=source_rows(),
    )
    return root, manifest


def build_state(
    physiology_root: Path,
    population_manifest: PopulationArtifactManifest,
    state_id: str,
    scale_factor: float,
) -> str:
    physiology_population_id = f"OTPHYS-{state_id}"
    store = PhysiologyPopulationArtifactStore(physiology_root)
    store.create_physiology_population(physiology_population_id)
    store.write_physiology_population(
        physiology_population_id,
        source_population_manifest=population_manifest,
        source_column_names=COLUMNS,
        source_rows=source_rows(),
        override=PhysiologicalStateOverride(
            target=TARGET, scale_factor=scale_factor, unit="L/min", purpose="test"
        ),
        osp_parameter_path=resolve_osp_physiology_column(ACICLOVIR_IV_CAPABILITY_PROFILE, TARGET),
        coverage=physiology_coverage_for(ACICLOVIR_IV_CAPABILITY_PROFILE, TARGET),
    )
    return physiology_population_id


def lineage_for(
    population_manifest: PopulationArtifactManifest, row_index: int
) -> PkEndpointSubjectLineage:
    return PkEndpointSubjectLineage(
        source_generation_id=GENERATION_ID,
        source_population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
        source_population_row_index=row_index,
        source_population_row_sha256=source_row_sha256(COLUMNS, source_rows()[row_index]),
    )


def write_state_endpoints(
    endpoint_root: Path,
    state_id: str,
    population_manifest: PopulationArtifactManifest,
    values: dict[str, dict[PkEndpointType, float]],
    lineage_overrides: dict[str, PkEndpointSubjectLineage] | None = None,
) -> tuple[PkEndpointArtifactStore, str]:
    store = PkEndpointArtifactStore(endpoint_root / state_id)
    endpoint_id = f"OTPK-{state_id}"
    store.create_endpoint_artifact(endpoint_id)
    endpoints = []
    lineage: dict[str, PkEndpointSubjectLineage] = {}
    for subject_id, by_type in values.items():
        row_index = int(subject_id)
        for endpoint_type, value in by_type.items():
            endpoints.append(
                PkEndpointResult(
                    subject_id=subject_id,
                    endpoint_type=endpoint_type,
                    value=value,
                    unit="umol/L" if endpoint_type != PkEndpointType.TMAX else "min",
                    time_basis="post-dose",
                    integration_method="linear-log-trapezoidal",
                    source_result_hash=RESULT_HASH,
                    analyte="aciclovir",
                    matrix="plasma",
                    fraction="total",
                    measurement="concentration",
                )
            )
        lineage[subject_id] = (
            lineage_overrides.get(subject_id)
            if lineage_overrides and subject_id in lineage_overrides
            else lineage_for(population_manifest, row_index)
        )
    store.write_endpoints(
        endpoint_id,
        endpoints=endpoints,
        source_result_semantic_sha256=RESULT_HASH,
        source_result_id=f"OTRES-{state_id}",
        run_id=f"OTR-{state_id}",
        source_engine_id="osp",
        source_model_id="osp.aciclovir.vergin-1995-iv",
        subject_lineage=lineage,
    )
    return store, endpoint_id


def full_values(cmax_by_subject: dict[str, float]) -> dict[str, dict[PkEndpointType, float]]:
    return {
        subject: {PkEndpointType.CMAX: cmax, PkEndpointType.AUC_0_LAST: cmax * 100}
        for subject, cmax in cmax_by_subject.items()
    }


def test_paired_deltas_computed_correctly_for_matching_lineage(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    physio_ids = {
        "baseline": build_state(physiology_root, population_manifest, "baseline", 1.0),
        "reduced": build_state(physiology_root, population_manifest, "reduced", 0.6),
    }
    endpoint_root = tmp_path / "endpoints"
    baseline_store, baseline_endpoint_id = write_state_endpoints(
        endpoint_root,
        "baseline",
        population_manifest,
        full_values({"0": 10.0, "1": 20.0, "2": 30.0}),
    )
    reduced_store, reduced_endpoint_id = write_state_endpoints(
        endpoint_root,
        "reduced",
        population_manifest,
        full_values({"0": 11.0, "1": 22.0, "2": 33.0}),
    )

    result = compare_physiology_states(
        baseline_state_id="baseline",
        state_physiology_population_ids=physio_ids,
        state_endpoint_ids={"baseline": baseline_endpoint_id, "reduced": reduced_endpoint_id},
        physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
        endpoint_stores={"baseline": baseline_store, "reduced": reduced_store},
    )

    assert result.missingness.expected_subject_count == 3
    assert result.missingness.complete_subject_count == 3
    assert result.missingness.excluded_subject_ids == ()

    cmax_delta = next(
        delta
        for delta in result.subject_deltas
        if delta.subject_id == "0" and delta.endpoint_type == PkEndpointType.CMAX
    )
    assert cmax_delta.baseline_value == pytest.approx(10.0)
    assert cmax_delta.comparison_value == pytest.approx(11.0)
    assert cmax_delta.absolute_difference == pytest.approx(1.0)
    assert cmax_delta.relative_difference == pytest.approx(0.1)
    # 3 subjects x 2 endpoint types x 1 comparison state
    assert len(result.subject_deltas) == 6


def test_missing_subject_in_one_state_is_excluded_not_silently_dropped(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    physio_ids = {
        "baseline": build_state(physiology_root, population_manifest, "baseline", 1.0),
        "reduced": build_state(physiology_root, population_manifest, "reduced", 0.6),
    }
    endpoint_root = tmp_path / "endpoints"
    baseline_store, baseline_endpoint_id = write_state_endpoints(
        endpoint_root,
        "baseline",
        population_manifest,
        full_values({"0": 10.0, "1": 20.0, "2": 30.0}),
    )
    # Subject "2" is missing from the reduced state -- e.g. a partial run.
    reduced_store, reduced_endpoint_id = write_state_endpoints(
        endpoint_root, "reduced", population_manifest, full_values({"0": 11.0, "1": 22.0})
    )

    result = compare_physiology_states(
        baseline_state_id="baseline",
        state_physiology_population_ids=physio_ids,
        state_endpoint_ids={"baseline": baseline_endpoint_id, "reduced": reduced_endpoint_id},
        physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
        endpoint_stores={"baseline": baseline_store, "reduced": reduced_store},
    )

    assert result.missingness.complete_subject_count == 2
    assert result.missingness.excluded_subject_ids == ("2",)
    assert all(delta.subject_id != "2" for delta in result.subject_deltas)
    # State-level summaries still include the excluded subject for its own state.
    baseline_cmax_summary = next(
        summary
        for summary in result.state_summaries
        if summary.state_id == "baseline" and summary.endpoint_type == PkEndpointType.CMAX
    )
    assert baseline_cmax_summary.n == 3


def test_mismatched_lineage_across_states_is_rejected(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    physio_ids = {
        "baseline": build_state(physiology_root, population_manifest, "baseline", 1.0),
        "reduced": build_state(physiology_root, population_manifest, "reduced", 0.6),
    }
    endpoint_root = tmp_path / "endpoints"
    baseline_store, baseline_endpoint_id = write_state_endpoints(
        endpoint_root,
        "baseline",
        population_manifest,
        full_values({"0": 10.0, "1": 20.0, "2": 30.0}),
    )
    # Corrupt subject "0"'s lineage in the reduced state: wrong row index.
    corrupted_lineage = {
        "0": PkEndpointSubjectLineage(
            source_generation_id=GENERATION_ID,
            source_population_semantic_sha256=(
                population_manifest.individuals.semantic_content_sha256
            ),
            source_population_row_index=1,
            source_population_row_sha256=source_row_sha256(COLUMNS, source_rows()[1]),
        )
    }
    reduced_store, reduced_endpoint_id = write_state_endpoints(
        endpoint_root,
        "reduced",
        population_manifest,
        full_values({"0": 11.0, "1": 22.0, "2": 33.0}),
        lineage_overrides=corrupted_lineage,
    )

    with pytest.raises(ValueError, match="identical population-row lineage"):
        compare_physiology_states(
            baseline_state_id="baseline",
            state_physiology_population_ids=physio_ids,
            state_endpoint_ids={"baseline": baseline_endpoint_id, "reduced": reduced_endpoint_id},
            physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
            endpoint_stores={"baseline": baseline_store, "reduced": reduced_store},
        )


def test_requires_at_least_two_states(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    physio_ids = {"baseline": build_state(physiology_root, population_manifest, "baseline", 1.0)}
    endpoint_root = tmp_path / "endpoints"
    baseline_store, baseline_endpoint_id = write_state_endpoints(
        endpoint_root, "baseline", population_manifest, full_values({"0": 10.0})
    )

    with pytest.raises(ValueError, match="at least two"):
        compare_physiology_states(
            baseline_state_id="baseline",
            state_physiology_population_ids=physio_ids,
            state_endpoint_ids={"baseline": baseline_endpoint_id},
            physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
            endpoint_stores={"baseline": baseline_store},
        )


def test_baseline_state_must_be_among_declared_states(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_root = tmp_path / "physiology"
    physio_ids = {
        "baseline": build_state(physiology_root, population_manifest, "baseline", 1.0),
        "reduced": build_state(physiology_root, population_manifest, "reduced", 0.6),
    }
    endpoint_root = tmp_path / "endpoints"
    baseline_store, baseline_endpoint_id = write_state_endpoints(
        endpoint_root, "baseline", population_manifest, full_values({"0": 10.0})
    )
    reduced_store, reduced_endpoint_id = write_state_endpoints(
        endpoint_root, "reduced", population_manifest, full_values({"0": 11.0})
    )

    with pytest.raises(ValueError, match="baseline_state_id"):
        compare_physiology_states(
            baseline_state_id="not-a-declared-state",
            state_physiology_population_ids=physio_ids,
            state_endpoint_ids={"baseline": baseline_endpoint_id, "reduced": reduced_endpoint_id},
            physiology_store=PhysiologyPopulationArtifactStore(physiology_root),
            endpoint_stores={"baseline": baseline_store, "reduced": reduced_store},
        )
