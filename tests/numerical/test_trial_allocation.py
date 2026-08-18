import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.patient import PopulationSpec
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    RandomizationType,
    TimeWindow,
    Trial,
    TrialArm,
    allocate_population_to_arms,
)


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def arm(arm_id: str, dose_mg: float, allocation: float) -> TrialArm:
    intervention = Intervention(
        intervention_id=f"aciclovir-{arm_id}",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id=f"{arm_id}-regimen",
            doses=(
                Dose(
                    amount=assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                    infusion_duration=assumed(10, "min"),
                ),
            ),
        ),
    )
    return TrialArm(arm_id=arm_id, name=arm_id, intervention=intervention, allocation=allocation)


def trial(*, arms: tuple[TrialArm, ...], seed: int = 42, population_size: int = 10) -> Trial:
    return Trial(
        trial_id="ALLOC-TEST",
        title="Allocation test",
        question_of_interest="Does allocation partition deterministically?",
        population=PopulationSpec(
            id="alloc-test", size=population_size, seed=1, generator_version="0.1.0"
        ),
        arms=arms,
        randomization=RandomizationType.PARALLEL,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=seed,
    )


def population_rows(n: int) -> tuple[dict[str, object], ...]:
    return tuple(
        {"IndividualId": i, "Gender": "FEMALE", "Organism|Age": 20.0 + i} for i in range(n)
    )


COLUMNS = ("IndividualId", "Gender", "Organism|Age")


def test_allocation_partitions_every_subject_exactly_once() -> None:
    arms = (arm("low", 125.0, 0.5), arm("high", 250.0, 0.5))
    result = allocate_population_to_arms(
        trial(arms=arms, population_size=10), COLUMNS, population_rows(10), "IndividualId"
    )

    assigned_indexes = sorted(entry.source_row_index for entry in result.entries)
    assert assigned_indexes == list(range(10))
    assert len(result.entries) == 10
    assert result.arm_counts == {"low": 5, "high": 5}


def test_largest_remainder_apportionment_sums_to_total_with_uneven_fractions() -> None:
    # 1/3 + 1/3 + 1/3 of 10 -> quotas 3.33 each; two arms round up by remainder.
    arms = (arm("a", 100.0, 1 / 3), arm("b", 200.0, 1 / 3), arm("c", 300.0, 1 / 3))
    result = allocate_population_to_arms(
        trial(arms=arms, population_size=10), COLUMNS, population_rows(10), "IndividualId"
    )

    assert sum(result.arm_counts.values()) == 10
    assert set(result.arm_counts.values()) == {3, 3, 4} or sorted(result.arm_counts.values()) == [
        3,
        3,
        4,
    ]


def test_allocation_is_deterministic_given_the_same_seed() -> None:
    arms = (arm("low", 125.0, 0.5), arm("high", 250.0, 0.5))
    first = allocate_population_to_arms(
        trial(arms=arms, seed=7, population_size=20), COLUMNS, population_rows(20), "IndividualId"
    )
    second = allocate_population_to_arms(
        trial(arms=arms, seed=7, population_size=20), COLUMNS, population_rows(20), "IndividualId"
    )

    assert first.entries == second.entries
    assert first.arm_counts == second.arm_counts


def test_allocation_differs_for_different_seeds() -> None:
    arms = (arm("low", 125.0, 0.5), arm("high", 250.0, 0.5))
    first = allocate_population_to_arms(
        trial(arms=arms, seed=1, population_size=20), COLUMNS, population_rows(20), "IndividualId"
    )
    second = allocate_population_to_arms(
        trial(arms=arms, seed=2, population_size=20), COLUMNS, population_rows(20), "IndividualId"
    )

    assignment_by_index_first = {e.source_row_index: e.arm_id for e in first.entries}
    assignment_by_index_second = {e.source_row_index: e.arm_id for e in second.entries}
    assert assignment_by_index_first != assignment_by_index_second


def test_allocation_rejects_non_randomized_trial() -> None:
    single_arm = (arm("only", 250.0, 1.0),)
    non_randomized = Trial(
        trial_id="NON-RANDOMIZED",
        title="Single arm",
        question_of_interest="One arm only.",
        population=PopulationSpec(id="single", size=5, seed=1, generator_version="0.1.0"),
        arms=single_arm,
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=1,
    )

    with pytest.raises(ValueError, match="PARALLEL-randomized"):
        allocate_population_to_arms(non_randomized, COLUMNS, population_rows(5), "IndividualId")


def test_row_hashes_are_recomputed_from_the_real_population_rows() -> None:
    arms = (arm("low", 125.0, 0.5), arm("high", 250.0, 0.5))
    result = allocate_population_to_arms(
        trial(arms=arms, population_size=4), COLUMNS, population_rows(4), "IndividualId"
    )

    hashes = {entry.source_row_index: entry.source_row_sha256 for entry in result.entries}
    assert len(set(hashes.values())) == 4  # every row's content differs -> every hash differs
