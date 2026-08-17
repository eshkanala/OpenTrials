import pytest
from pydantic import ValidationError

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.patient import AgeRange, PopulationSpec
from opentrials.trials import (
    Eligibility,
    EligibilityCriterion,
    EligibilityOperator,
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    RandomizationType,
    TimeWindow,
    Trial,
    TrialArm,
)


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def make_population_spec() -> PopulationSpec:
    return PopulationSpec(
        id="healthy-adults-v1",
        size=100,
        seed=42,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=observed(18, "year"), maximum=observed(65, "year")),
    )


def make_intervention(identifier: str = "aciclovir") -> Intervention:
    return Intervention(
        intervention_id=f"{identifier}-400-mg-oral",
        compound=Compound(
            identity=CompoundIdentity(compound_id=identifier, preferred_name=identifier.title())
        ),
        regimen=Regimen(
            regimen_id=f"{identifier}-single-dose",
            doses=(
                Dose(
                    amount=observed(400, "mg"),
                    route=Route.ORAL,
                    administration_time=observed(0, "hour"),
                ),
            ),
        ),
    )


def make_endpoint() -> Endpoint:
    return Endpoint(
        endpoint_id="auc-0-24",
        endpoint_type=EndpointType.PK,
        measurement="plasma aciclovir concentration",
        time_window=TimeWindow(start=observed(0, "hour"), end=observed(24, "hour")),
        aggregation=EndpointAggregation.AUC,
        missingness_rule=MissingnessRule.REPORT,
        analysis_method="noncompartmental analysis",
        unit="mg/L",
    )


def test_eligibility_keeps_numeric_criteria_unit_aware() -> None:
    eligibility = Eligibility(
        inclusion=(
            EligibilityCriterion(
                criterion_id="adult-age",
                field_path="demographics.age",
                operator=EligibilityOperator.GREATER_THAN_OR_EQUAL,
                value=observed(18, "year"),
            ),
        ),
        exclusion=(
            EligibilityCriterion(
                criterion_id="pregnancy",
                field_path="demographics.pregnancy_state",
                operator=EligibilityOperator.IS_TRUE,
            ),
        ),
    )

    assert eligibility.inclusion[0].value == observed(18, "year")


def test_eligibility_rejects_untyped_numeric_comparison() -> None:
    with pytest.raises(ValidationError, match="require a ScientificValue"):
        EligibilityCriterion(
            criterion_id="adult-age",
            field_path="demographics.age",
            operator=EligibilityOperator.GREATER_THAN_OR_EQUAL,
            value="18",
        )


def test_endpoint_requires_ordered_time_window() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        TimeWindow(start=observed(24, "hour"), end=observed(0, "hour"))


def test_parallel_trial_requires_balanced_allocations() -> None:
    trial = Trial(
        trial_id="aciclovir-dose-comparison",
        title="Aciclovir dose comparison",
        question_of_interest="How does exposure differ by dose?",
        population=make_population_spec(),
        arms=(
            TrialArm(
                arm_id="low-dose",
                name="Low dose",
                intervention=make_intervention("aciclovir-low"),
                allocation=0.5,
            ),
            TrialArm(
                arm_id="high-dose",
                name="High dose",
                intervention=make_intervention("aciclovir-high"),
                allocation=0.5,
            ),
        ),
        randomization=RandomizationType.PARALLEL,
        endpoints=(make_endpoint(),),
        seed=2026,
    )

    assert trial.arms[0].allocation + trial.arms[1].allocation == 1.0
    assert '"trial_id":"aciclovir-dose-comparison"' in trial.canonical_json()


def test_parallel_trial_rejects_unbalanced_allocations() -> None:
    with pytest.raises(ValidationError, match="sum to one"):
        Trial(
            trial_id="unbalanced",
            title="Unbalanced trial",
            question_of_interest="Test allocation validation",
            population=make_population_spec(),
            arms=(
                TrialArm(
                    arm_id="a",
                    name="A",
                    intervention=make_intervention("a"),
                    allocation=0.6,
                ),
                TrialArm(
                    arm_id="b",
                    name="B",
                    intervention=make_intervention("b"),
                    allocation=0.3,
                ),
            ),
            randomization=RandomizationType.PARALLEL,
            endpoints=(make_endpoint(),),
            seed=2026,
        )


def test_non_randomized_trial_requires_one_arm() -> None:
    with pytest.raises(ValidationError, match="exactly one arm"):
        Trial(
            trial_id="invalid-single-arm",
            title="Invalid non-randomized trial",
            question_of_interest="Test arm count validation",
            population=make_population_spec(),
            arms=(
                TrialArm(
                    arm_id="a",
                    name="A",
                    intervention=make_intervention("a"),
                    allocation=0.5,
                ),
                TrialArm(
                    arm_id="b",
                    name="B",
                    intervention=make_intervention("b"),
                    allocation=0.5,
                ),
            ),
            randomization=RandomizationType.NONE,
            endpoints=(make_endpoint(),),
            seed=2026,
        )
