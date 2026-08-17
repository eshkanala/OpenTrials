from pathlib import Path

import pytest

from opentrials.adapters.osp import osp_population_field_catalog
from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.cohort import (
    CategoricalPredicate,
    CohortDefinition,
    CohortMembershipArtifactStore,
    NumericOperator,
    NumericPredicate,
    OverlapPolicy,
    compare_cohort_pk_endpoints,
    source_row_sha256,
)
from opentrials.core.serialization import document
from opentrials.storage import (
    CohortPkComparisonArtifactStore,
    PkEndpointArtifactStore,
    PkEndpointSubjectLineage,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

SOURCE_HASH = "sha256:" + "a" * 64
COLUMNS = (
    "IndividualId",
    "Gender",
    "Organism|Age",
    "Organism|Weight",
    "Organism|Height",
    "Organism|BMI",
)
GENERATION_ID = "OTPGEN-comparison-test"
CMAX_VALUES = {0: 10.0, 1: 20.0, 2: 30.0, 3: 40.0, 4: 50.0}
TMAX_VALUES = {0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0}


def population_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "IndividualId": 10,
            "Gender": "FEMALE",
            "Organism|Age": 25.0,
            "Organism|Weight": 55.0,
            "Organism|Height": 16.3,
            "Organism|BMI": 0.207,
        },
        {
            "IndividualId": 11,
            "Gender": "MALE",
            "Organism|Age": 30.0,
            "Organism|Weight": 82.0,
            "Organism|Height": 17.9,
            "Organism|BMI": 0.256,
        },
        {
            "IndividualId": 12,
            "Gender": "FEMALE",
            "Organism|Age": 45.0,
            "Organism|Weight": 63.0,
            "Organism|Height": 16.5,
            "Organism|BMI": 0.231,
        },
        {
            "IndividualId": 13,
            "Gender": "MALE",
            "Organism|Age": 50.0,
            "Organism|Weight": 88.0,
            "Organism|Height": 17.6,
            "Organism|BMI": 0.284,
        },
        {
            "IndividualId": 14,
            "Gender": "FEMALE",
            "Organism|Age": 60.0,
            "Organism|Weight": 70.0,
            "Organism|Height": 16.0,
            "Organism|BMI": 0.273,
        },
    )


def build_population(
    tmp_path: Path, *, generation_id: str = GENERATION_ID
) -> tuple[PopulationArtifactStore, PopulationArtifactManifest]:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation(generation_id)
    manifest = store.write_population(
        generation_id,
        population_id="comparison-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "comparison-demo"}
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


def build_membership(
    tmp_path: Path,
    populations: PopulationArtifactStore,
    manifest: PopulationArtifactManifest,
    membership_id: str,
    *,
    predicate: NumericPredicate | CategoricalPredicate,
) -> CohortMembershipArtifactStore:
    catalog = osp_population_field_catalog()
    store = CohortMembershipArtifactStore(tmp_path / "memberships", populations)
    store.create_membership(membership_id)
    definition = CohortDefinition(
        cohort_id=f"OTCOH-{membership_id.removeprefix('OTMEM-')}",
        predicates=(predicate,),
        source_generation_id=manifest.generation_id,
        source_population_semantic_sha256=manifest.individuals.semantic_content_sha256,
        field_catalog_sha256=catalog.canonical_sha256(),
    )
    store.write_membership(membership_id, definition=definition, field_catalog=catalog)
    return store


def build_endpoint_artifact(
    tmp_path: Path,
    manifest: PopulationArtifactManifest,
    *,
    endpoint_id: str = "OTPK-comparison",
    exclude_row_indexes: frozenset[int] = frozenset(),
) -> PkEndpointArtifactStore:
    included = [index for index in range(5) if index not in exclude_row_indexes]
    endpoints: list[PkEndpointResult] = []
    lineage: dict[str, PkEndpointSubjectLineage] = {}
    for row_index in included:
        subject_id = f"subject-{row_index}"
        for endpoint_type, values, unit in (
            (PkEndpointType.CMAX, CMAX_VALUES, "umol/L"),
            (PkEndpointType.TMAX, TMAX_VALUES, "min"),
        ):
            endpoints.append(
                PkEndpointResult(
                    subject_id=subject_id,
                    endpoint_type=endpoint_type,
                    value=values[row_index],
                    unit=unit,
                    time_basis="actual_sample_times",
                    integration_method="not_applicable",
                    source_result_hash=SOURCE_HASH,
                    analyte="aciclovir",
                    matrix="plasma",
                    fraction="total",
                    measurement="concentration",
                )
            )
        lineage[subject_id] = PkEndpointSubjectLineage(
            source_generation_id=manifest.generation_id,
            source_population_semantic_sha256=manifest.individuals.semantic_content_sha256,
            source_population_row_index=row_index,
            source_population_row_sha256=source_row_sha256(COLUMNS, population_rows()[row_index]),
        )

    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact(endpoint_id)
    store.write_endpoints(
        endpoint_id,
        endpoints=tuple(endpoints),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-comparison",
        run_id="OTR-comparison",
        subject_lineage=lineage,
    )
    return store


def female_predicate() -> CategoricalPredicate:
    return CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",))


def older_predicate() -> NumericPredicate:
    return NumericPredicate(
        field_id="demographics.age", operator=NumericOperator.GTE, value=40, unit="year"
    )


def setup_two_groups(
    tmp_path: Path, *, exclude_row_indexes: frozenset[int] = frozenset()
) -> tuple[CohortMembershipArtifactStore, PkEndpointArtifactStore]:
    """Females = rows {0, 2, 4}; age >= 40 = rows {2, 3, 4}; overlap = {2, 4}."""
    populations, manifest = build_population(tmp_path)
    membership_store = build_membership(
        tmp_path, populations, manifest, "OTMEM-females", predicate=female_predicate()
    )
    build_membership(tmp_path, populations, manifest, "OTMEM-older", predicate=older_predicate())
    endpoint_store = build_endpoint_artifact(
        tmp_path, manifest, exclude_row_indexes=exclude_row_indexes
    )
    return membership_store, endpoint_store


def test_strict_join_matches_by_lineage_not_subject_id_and_reports_missingness(
    tmp_path: Path,
) -> None:
    membership_store, endpoint_store = setup_two_groups(
        tmp_path, exclude_row_indexes=frozenset({3})
    )

    result = compare_cohort_pk_endpoints(
        group_a_membership_id="OTMEM-females",
        group_b_membership_id="OTMEM-older",
        group_a_label="Females",
        group_b_label="Age >= 40",
        endpoint_id="OTPK-comparison",
        membership_store=membership_store,
        endpoint_store=endpoint_store,
    )

    assert result.overlap.group_a_n == 3
    assert result.overlap.group_b_n == 3
    assert result.overlap.overlap_n == 2
    assert result.overlap.group_a_only_n == 1
    assert result.overlap.group_b_only_n == 1

    cmax_a = next(
        s
        for s in result.group_summaries
        if s.membership_id == "OTMEM-females" and s.endpoint_type == PkEndpointType.CMAX
    )
    cmax_b = next(
        s
        for s in result.group_summaries
        if s.membership_id == "OTMEM-older" and s.endpoint_type == PkEndpointType.CMAX
    )
    assert cmax_a.n_members == 3
    assert cmax_a.n_matched == 3
    assert cmax_a.summary is not None
    assert cmax_a.summary.mean == pytest.approx(30.0)  # rows 0,2,4 -> 10,30,50

    assert cmax_b.n_members == 3
    assert cmax_b.n_matched == 2  # row 3 excluded from the endpoint artifact
    assert cmax_b.n_missing == 1
    assert cmax_b.coverage == pytest.approx(2 / 3)
    assert cmax_b.summary is not None
    assert cmax_b.summary.mean == pytest.approx(40.0)  # rows 2,4 -> 30,50

    comparison = next(c for c in result.comparisons if c.endpoint_type == PkEndpointType.CMAX)
    assert comparison.group_a_mean == pytest.approx(30.0)
    assert comparison.group_b_mean == pytest.approx(40.0)
    assert comparison.absolute_difference == pytest.approx(10.0)
    assert comparison.relative_difference == pytest.approx(10.0 / 30.0)


def test_require_disjoint_policy_rejects_overlapping_groups(tmp_path: Path) -> None:
    membership_store, endpoint_store = setup_two_groups(tmp_path)

    with pytest.raises(ValueError, match="overlap"):
        compare_cohort_pk_endpoints(
            group_a_membership_id="OTMEM-females",
            group_b_membership_id="OTMEM-older",
            group_a_label="Females",
            group_b_label="Age >= 40",
            endpoint_id="OTPK-comparison",
            membership_store=membership_store,
            endpoint_store=endpoint_store,
            overlap_policy=OverlapPolicy.REQUIRE_DISJOINT,
        )


def test_comparison_rejects_endpoint_artifact_without_population_lineage(tmp_path: Path) -> None:
    populations, manifest = build_population(tmp_path)
    membership_store = build_membership(
        tmp_path, populations, manifest, "OTMEM-females", predicate=female_predicate()
    )
    build_membership(tmp_path, populations, manifest, "OTMEM-older", predicate=older_predicate())

    endpoint_store = PkEndpointArtifactStore(tmp_path / "endpoints")
    endpoint_store.create_endpoint_artifact("OTPK-nolineage")
    endpoint_store.write_endpoints(
        "OTPK-nolineage",
        endpoints=(
            PkEndpointResult(
                subject_id="0",
                endpoint_type=PkEndpointType.CMAX,
                value=10.0,
                unit="umol/L",
                time_basis="actual_sample_times",
                integration_method="not_applicable",
                source_result_hash=SOURCE_HASH,
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
            ),
        ),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-nolineage",
        run_id="OTR-nolineage",
    )

    with pytest.raises(ValueError, match=r"Schema v2\+ required"):
        compare_cohort_pk_endpoints(
            group_a_membership_id="OTMEM-females",
            group_b_membership_id="OTMEM-older",
            group_a_label="Females",
            group_b_label="Age >= 40",
            endpoint_id="OTPK-nolineage",
            membership_store=membership_store,
            endpoint_store=endpoint_store,
        )


def test_comparison_rejects_identical_groups(tmp_path: Path) -> None:
    membership_store, endpoint_store = setup_two_groups(tmp_path)

    with pytest.raises(ValueError, match="two distinct"):
        compare_cohort_pk_endpoints(
            group_a_membership_id="OTMEM-females",
            group_b_membership_id="OTMEM-females",
            group_a_label="Females",
            group_b_label="Females again",
            endpoint_id="OTPK-comparison",
            membership_store=membership_store,
            endpoint_store=endpoint_store,
        )


def test_comparison_rejects_groups_from_different_populations(tmp_path: Path) -> None:
    # Both generations and both memberships share one root: `verify_membership` on
    # a single store must be able to resolve either group ID.
    populations, manifest = build_population(tmp_path)
    membership_store = build_membership(
        tmp_path, populations, manifest, "OTMEM-females", predicate=female_predicate()
    )

    _, other_manifest = build_population(tmp_path, generation_id="OTPGEN-other")
    catalog = osp_population_field_catalog()
    membership_store.create_membership("OTMEM-other")
    membership_store.write_membership(
        "OTMEM-other",
        definition=CohortDefinition(
            cohort_id="OTCOH-other",
            predicates=(female_predicate(),),
            source_generation_id="OTPGEN-other",
            source_population_semantic_sha256=other_manifest.individuals.semantic_content_sha256,
            field_catalog_sha256=catalog.canonical_sha256(),
        ),
        field_catalog=catalog,
    )

    endpoint_store = build_endpoint_artifact(tmp_path, manifest)

    with pytest.raises(ValueError, match="different generated populations"):
        compare_cohort_pk_endpoints(
            group_a_membership_id="OTMEM-females",
            group_b_membership_id="OTMEM-other",
            group_a_label="Females",
            group_b_label="Other",
            endpoint_id="OTPK-comparison",
            membership_store=membership_store,
            endpoint_store=endpoint_store,
        )


def test_comparison_artifact_is_immutable_and_verifies(tmp_path: Path) -> None:
    membership_store, endpoint_store = setup_two_groups(
        tmp_path, exclude_row_indexes=frozenset({3})
    )
    result = compare_cohort_pk_endpoints(
        group_a_membership_id="OTMEM-females",
        group_b_membership_id="OTMEM-older",
        group_a_label="Females",
        group_b_label="Age >= 40",
        endpoint_id="OTPK-comparison",
        membership_store=membership_store,
        endpoint_store=endpoint_store,
    )

    store = CohortPkComparisonArtifactStore(tmp_path / "comparisons")
    store.create_comparison("OTCPK-001")
    manifest = store.write_comparison("OTCPK-001", result)
    reloaded = store.verify_comparison("OTCPK-001")

    assert reloaded == manifest
    assert manifest.overlap.overlap_n == 2
    assert manifest.group_summaries.rows == len(result.group_summaries)
    assert manifest.comparisons.rows == len(result.comparisons)
    with pytest.raises(FileExistsError, match="already exist"):
        store.write_comparison("OTCPK-001", result)
