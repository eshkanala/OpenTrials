from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from opentrials.adapters.osp import osp_population_field_catalog
from opentrials.cohort import (
    CategoricalPredicate,
    CohortDefinition,
    CohortKind,
    CohortMembershipArtifactStore,
    NumericOperator,
    NumericPredicate,
    PresencePredicate,
)
from opentrials.core.serialization import document
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)


def rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "IndividualId": 10,
            "Gender": "FEMALE",
            "Organism|Age": 31.2,
            "Organism|Weight": 58.4,
            "Organism|Height": 16.5,
            "Organism|BMI": 0.2145,
        },
        {
            "IndividualId": 11,
            "Gender": "MALE",
            "Organism|Age": 42.7,
            "Organism|Weight": 79.1,
            "Organism|Height": 17.8,
            "Organism|BMI": 0.2497,
        },
        {
            "IndividualId": 12,
            "Gender": "FEMALE",
            "Organism|Age": None,
            "Organism|Weight": 61.0,
            "Organism|Height": 16.2,
            "Organism|BMI": 0.2324,
        },
    )


def population_store(tmp_path: Path) -> tuple[PopulationArtifactStore, object]:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation("OTPGEN-test")
    manifest = store.write_population(
        "OTPGEN-test",
        population_id="demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=3,
        column_names=(
            "IndividualId",
            "Gender",
            "Organism|Age",
            "Organism|Weight",
            "Organism|Height",
            "Organism|BMI",
        ),
        rows=rows(),
    )
    return store, manifest


def definition(manifest: object, **changes: object) -> CohortDefinition:
    catalog = osp_population_field_catalog()
    values: dict[str, object] = {
        "cohort_id": "OTCOH-adult-female",
        "predicates": (
            NumericPredicate(
                field_id="demographics.age",
                operator=NumericOperator.GTE,
                value=0.03,
                unit="kiloyear",
            ),
            CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",)),
            PresencePredicate(field_id="demographics.age", present=True),
        ),
        "source_generation_id": "OTPGEN-test",
        "source_population_semantic_sha256": manifest.individuals.semantic_content_sha256,  # type: ignore[attr-defined]
        "field_catalog_sha256": catalog.canonical_sha256(),
    }
    values.update(changes)
    return CohortDefinition(**values)


def test_predicate_contracts_are_narrow_and_definitions_are_immutable(tmp_path: Path) -> None:
    _, manifest = population_store(tmp_path)
    cohort = definition(manifest)
    assert cohort.predicates[0].unit == "kiloyear"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        NumericPredicate(  # type: ignore[call-arg]
            field_id="demographics.age", operator="GTE", value=18, unit="year", expression="age + 1"
        )
    with pytest.raises(ValidationError, match="parent"):
        CohortDefinition(**{**cohort.model_dump(), "kind": "SUBGROUP"})
    with pytest.raises(ValidationError, match="frozen"):
        cohort.cohort_id = "OTCOH-changed"  # type: ignore[misc]


def test_membership_is_immutable_verifiable_and_preserves_complete_row_hash(tmp_path: Path) -> None:
    populations, manifest = population_store(tmp_path)
    store = CohortMembershipArtifactStore(tmp_path / "memberships", populations)
    directory = store.create_membership("OTMEM-adult-female")
    written = store.write_membership(
        "OTMEM-adult-female",
        definition=definition(manifest),
        field_catalog=osp_population_field_catalog(),
    )
    verified = store.verify_membership("OTMEM-adult-female")
    table = pq.read_table(directory / "members.parquet")
    assert written.members.rows == verified.members.rows == 1
    assert table.column_names == ["source_subject_id", "source_row_index", "source_row_sha256"]
    assert table.to_pylist()[0]["source_subject_id"] == "10"
    assert table.to_pylist()[0]["source_row_sha256"].startswith("sha256:")
    with pytest.raises(FileExistsError):
        store.write_membership(
            "OTMEM-adult-female",
            definition=definition(manifest),
            field_catalog=osp_population_field_catalog(),
        )


def test_source_and_catalog_mismatches_are_rejected(tmp_path: Path) -> None:
    populations, manifest = population_store(tmp_path)
    store = CohortMembershipArtifactStore(tmp_path / "memberships", populations)
    store.create_membership("OTMEM-mismatch")
    mismatch = definition(manifest, source_population_semantic_sha256="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="population semantic hash"):
        store.write_membership(
            "OTMEM-mismatch", definition=mismatch, field_catalog=osp_population_field_catalog()
        )


def test_subgroup_uses_parent_and_must_be_strict_subset(tmp_path: Path) -> None:
    populations, manifest = population_store(tmp_path)
    store = CohortMembershipArtifactStore(tmp_path / "memberships", populations)
    store.create_membership("OTMEM-females")
    parent = definition(
        manifest,
        cohort_id="OTCOH-females",
        predicates=(CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",)),),
    )
    store.write_membership(
        "OTMEM-females", definition=parent, field_catalog=osp_population_field_catalog()
    )
    store.create_membership("OTMEM-young-females")
    subgroup = definition(
        manifest,
        cohort_id="OTCOH-young-females",
        kind=CohortKind.SUBGROUP,
        parent_membership_id="OTMEM-females",
        predicates=(
            NumericPredicate(field_id="demographics.age", operator="LT", value=40, unit="year"),
        ),
    )
    child = store.write_membership(
        "OTMEM-young-females", definition=subgroup, field_catalog=osp_population_field_catalog()
    )
    assert child.members.rows == 1
    assert child.parent_membership is not None
    store.create_membership("OTMEM-not-strict")
    not_strict = definition(
        manifest,
        cohort_id="OTCOH-not-strict",
        kind=CohortKind.SUBGROUP,
        parent_membership_id="OTMEM-females",
        predicates=(CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",)),),
    )
    with pytest.raises(ValueError, match="strict subset"):
        store.write_membership(
            "OTMEM-not-strict", definition=not_strict, field_catalog=osp_population_field_catalog()
        )


def test_zero_member_cohort_is_a_valid_artifact(tmp_path: Path) -> None:
    populations, manifest = population_store(tmp_path)
    store = CohortMembershipArtifactStore(tmp_path / "memberships", populations)
    store.create_membership("OTMEM-empty")
    empty = definition(
        manifest,
        cohort_id="OTCOH-empty",
        predicates=(
            NumericPredicate(field_id="demographics.age", operator="GT", value=200, unit="year"),
        ),
    )
    persisted = store.write_membership(
        "OTMEM-empty", definition=empty, field_catalog=osp_population_field_catalog()
    )
    assert persisted.members.rows == 0
    assert store.verify_membership("OTMEM-empty").members.rows == 0
