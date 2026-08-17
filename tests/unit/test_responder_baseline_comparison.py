from pathlib import Path

import pytest

from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.cohort.definitions import FieldCatalog, LogicalField, LogicalFieldKind
from opentrials.core.serialization import document
from opentrials.responders import ExtremeResponderDefinition, SelectionMethod, TiePolicy
from opentrials.responders.baseline_comparison import compare_baseline_characteristics
from opentrials.responders.orchestration import run_extreme_responder_analysis
from opentrials.storage import (
    ExtremeResponderMembershipArtifactStore,
    PkEndpointArtifactStore,
    PkEndpointSubjectLineage,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
    ResponderComparisonArtifactStore,
    ResponderGroupKind,
)
from opentrials.storage.row_identity import source_row_sha256

SOURCE_HASH = "sha256:" + "a" * 64
COLUMNS = ("IndividualId", "Gender", "Organism|Age", "Organism|Weight")
GENERATION_ID = "OTPGEN-baseline-test"
ENDPOINT_ID = "OTPK-baseline-test"
AUC_VALUES = {0: 10.0, 1: 20.0, 2: 30.0, 3: 40.0, 4: 50.0}
AGES = {0: 20.0, 1: 30.0, 2: 40.0, 3: 50.0, 4: 60.0}
WEIGHTS = {0: 50.0, 1: 60.0, 2: 70.0, 3: 80.0, 4: 90.0}
GENDERS = {0: "FEMALE", 1: "MALE", 2: "FEMALE", 3: "MALE", 4: "FEMALE"}


def catalog() -> FieldCatalog:
    return FieldCatalog(
        catalog_id="test.baseline.v1",
        source_schema="osp.populationToDataFrame",
        subject_id_column="IndividualId",
        fields=(
            LogicalField(
                field_id="demographics.age",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|Age",
                unit="year",
            ),
            LogicalField(
                field_id="physiology.weight",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|Weight",
                unit="kg",
            ),
            LogicalField(
                field_id="demographics.sex",
                kind=LogicalFieldKind.CATEGORICAL,
                source_column="Gender",
            ),
        ),
    )


def population_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "IndividualId": index,
            "Gender": GENDERS[index],
            "Organism|Age": AGES[index],
            "Organism|Weight": WEIGHTS[index],
        }
        for index in range(5)
    )


def build_population(tmp_path: Path) -> tuple[PopulationArtifactStore, PopulationArtifactManifest]:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation(GENERATION_ID)
    manifest = store.write_population(
        GENERATION_ID,
        population_id="baseline-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "baseline-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=5,
        column_names=COLUMNS,
        rows=population_rows(),
    )
    return store, manifest


def build_endpoint(
    tmp_path: Path, manifest: PopulationArtifactManifest
) -> PkEndpointArtifactStore:
    endpoints = []
    lineage = {}
    for row_index, auc in AUC_VALUES.items():
        subject_id = f"subject-{row_index}"
        endpoints.append(
            PkEndpointResult(
                subject_id=subject_id,
                endpoint_type=PkEndpointType.AUC_0_LAST,
                value=auc,
                unit="umol/L * min",
                time_basis="actual_sample_times",
                integration_method="linear_trapezoidal",
                source_result_hash=SOURCE_HASH,
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
            )
        )
        lineage[subject_id] = PkEndpointSubjectLineage(
            source_generation_id=GENERATION_ID,
            source_population_semantic_sha256=manifest.individuals.semantic_content_sha256,
            source_population_row_index=row_index,
            source_population_row_sha256=source_row_sha256(COLUMNS, population_rows()[row_index]),
        )
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact(ENDPOINT_ID)
    store.write_endpoints(
        ENDPOINT_ID,
        endpoints=tuple(endpoints),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-baseline-test",
        run_id="OTR-baseline-test",
        subject_lineage=lineage,
    )
    return store


def test_full_orchestration_selects_persists_and_compares_baseline(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoints = build_endpoint(tmp_path, population_manifest)
    endpoint_manifest = endpoints.verify_endpoints(ENDPOINT_ID)

    definition = ExtremeResponderDefinition(
        definition_id="OTRESP-top-auc",
        source_endpoint_id=ENDPOINT_ID,
        source_endpoint_semantic_sha256=endpoint_manifest.endpoints.semantic_content_sha256,
        source_generation_id=GENERATION_ID,
        source_population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
        endpoint_type=PkEndpointType.AUC_0_LAST,
        method=SelectionMethod.TOP_N,
        count=2,
        percentile=None,
        tie_policy=TiePolicy.STRICT_COUNT,
    )

    analysis = run_extreme_responder_analysis(
        definition=definition,
        extreme_label="Top 2 AUC responders",
        reference_label="Reference",
        baseline_field_ids=("demographics.age", "physiology.weight", "demographics.sex"),
        field_catalog=catalog(),
        endpoint_store=endpoints,
        population_store=populations,
        membership_root=tmp_path / "memberships",
        comparison_root=tmp_path / "comparisons",
    )

    assert analysis.extreme_manifest.members.rows == 2
    assert analysis.reference_manifest.members.rows == 3

    age_comparison = next(
        c
        for c in analysis.comparison_result.numeric_comparisons
        if c.field_id == "demographics.age"
    )
    assert age_comparison.extreme_mean == pytest.approx(55.0)  # rows 3,4 -> ages 50,60
    assert age_comparison.reference_mean == pytest.approx(30.0)  # rows 0,1,2 -> ages 20,30,40
    assert age_comparison.absolute_difference == pytest.approx(25.0)
    assert age_comparison.relative_difference == pytest.approx(25.0 / 30.0)

    weight_comparison = next(
        c
        for c in analysis.comparison_result.numeric_comparisons
        if c.field_id == "physiology.weight"
    )
    assert weight_comparison.extreme_mean == pytest.approx(85.0)
    assert weight_comparison.reference_mean == pytest.approx(60.0)

    sex_extreme = next(
        s
        for s in analysis.comparison_result.categorical_summaries
        if s.field_id == "demographics.sex" and s.membership_id == analysis.extreme_membership_id
    )
    sex_reference = next(
        s
        for s in analysis.comparison_result.categorical_summaries
        if s.field_id == "demographics.sex" and s.membership_id == analysis.reference_membership_id
    )
    assert sex_extreme.category_counts == {"MALE": 1, "FEMALE": 1}
    assert sex_reference.category_counts == {"FEMALE": 2, "MALE": 1}

    assert "Does not imply causation" in analysis.comparison_result.interpretation_note

    comparison_store = ResponderComparisonArtifactStore(tmp_path / "comparisons")
    reloaded = comparison_store.verify_comparison(analysis.comparison_id)
    assert reloaded == analysis.comparison_manifest


def test_compare_baseline_characteristics_rejects_identical_memberships(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoints = build_endpoint(tmp_path, population_manifest)
    endpoint_manifest = endpoints.verify_endpoints(ENDPOINT_ID)
    definition = ExtremeResponderDefinition(
        definition_id="OTRESP-top-auc",
        source_endpoint_id=ENDPOINT_ID,
        source_endpoint_semantic_sha256=endpoint_manifest.endpoints.semantic_content_sha256,
        source_generation_id=GENERATION_ID,
        source_population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
        endpoint_type=PkEndpointType.AUC_0_LAST,
        method=SelectionMethod.TOP_N,
        count=2,
        percentile=None,
        tie_policy=TiePolicy.STRICT_COUNT,
    )
    membership_store = ExtremeResponderMembershipArtifactStore(
        tmp_path / "memberships", endpoint_store=endpoints, population_store=populations
    )
    membership_store.create_membership("OTXMEM-extreme")
    membership_store.write_membership(
        "OTXMEM-extreme", definition=definition, group_kind=ResponderGroupKind.EXTREME
    )

    with pytest.raises(ValueError, match="two distinct memberships"):
        compare_baseline_characteristics(
            extreme_membership_id="OTXMEM-extreme",
            reference_membership_id="OTXMEM-extreme",
            extreme_label="Extreme",
            reference_label="Extreme again",
            field_ids=("demographics.age",),
            membership_store=membership_store,
            population_store=populations,
            field_catalog=catalog(),
        )
