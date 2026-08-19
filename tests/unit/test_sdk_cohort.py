"""Contract tests for sdk.cohort's thin wrappers around cohort definition/comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.cohort.definitions import CategoricalPredicate, NumericOperator, NumericPredicate
from opentrials.core.serialization import document
from opentrials.sdk import cohort as sdk_cohort
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

ROWS = (
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
        "Organism|Age": 70.0,
        "Organism|Weight": 61.0,
        "Organism|Height": 16.2,
        "Organism|BMI": 0.2324,
    },
)
COLUMNS = (
    "IndividualId",
    "Gender",
    "Organism|Age",
    "Organism|Weight",
    "Organism|Height",
    "Organism|BMI",
)
GENERATION_ID = "OTPGEN-sdk-cohort-test"


def build_population(tmp_path: Path) -> Path:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    store.write_population(
        GENERATION_ID,
        population_id="sdk-cohort-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "sdk-cohort-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=len(ROWS),
        column_names=COLUMNS,
        rows=ROWS,
    )
    return root


def test_define_and_persist_cohort_selects_the_right_members(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    membership_root = tmp_path / "memberships"

    manifest = sdk_cohort.define_and_persist_cohort(
        predicates=(
            NumericPredicate(
                field_id="demographics.age", operator=NumericOperator.GTE, value=65, unit="year"
            ),
        ),
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        membership_root=membership_root,
    )

    assert manifest.members.rows == 1
    assert manifest.source_generation_id == GENERATION_ID


def test_define_and_persist_cohort_supports_categorical_predicates(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    membership_root = tmp_path / "memberships"

    manifest = sdk_cohort.define_and_persist_cohort(
        predicates=(CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",)),),
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        membership_root=membership_root,
    )

    assert manifest.members.rows == 2


def test_compare_cohorts_rejects_comparing_a_membership_with_itself(tmp_path: Path) -> None:
    population_root = build_population(tmp_path)
    membership_root = tmp_path / "memberships"
    manifest = sdk_cohort.define_and_persist_cohort(
        predicates=(CategoricalPredicate(field_id="demographics.sex", values=("FEMALE",)),),
        population_generation_id=GENERATION_ID,
        population_root=population_root,
        membership_root=membership_root,
    )

    with pytest.raises(ValueError, match="two distinct"):
        sdk_cohort.compare_cohorts(
            group_a_membership_id=manifest.membership_id,
            group_b_membership_id=manifest.membership_id,
            group_a_label="females",
            group_b_label="females-again",
            endpoint_id="OTPK-does-not-matter-here",
            membership_root=membership_root,
            population_root=population_root,
            endpoint_root=tmp_path / "endpoints",
        )
