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
)
from opentrials.validation.compatibility import (
    CompatibilityStatus,
    PredictedPkSeriesDescriptor,
    ValidationEligibility,
    assess_validation_compatibility,
)
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def value(amount: float, unit: str, value_type: ValueType = ValueType.OBSERVED) -> ScientificValue:
    return ScientificValue(value=amount, unit=unit, value_type=value_type)


def intervention(route: Route = Route.INTRAVENOUS, dose_unit: str = "mg") -> Intervention:
    return Intervention(
        intervention_id="aciclovir-single-dose",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="single-dose",
            doses=(
                Dose(
                    amount=value(250 if dose_unit == "mg" else 0.25, dose_unit),
                    route=route,
                    administration_time=value(0, "hour"),
                    infusion_duration=value(30, "minute") if route is Route.INTRAVENOUS else None,
                ),
            ),
        ),
    )


def trial() -> Trial:
    return Trial(
        trial_id="trial-001",
        title="Aciclovir PK",
        question_of_interest="Exposure after a single dose",
        population=PopulationSpec(id="healthy-adults", size=10, seed=1, generator_version="1.0"),
        arms=(
            TrialArm(
                arm_id="treatment", name="Treatment", intervention=intervention(), allocation=1
            ),
        ),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="pk-concentration",
                endpoint_type=EndpointType.PK,
                measurement="free text concentration endpoint",
                time_window=TimeWindow(start=value(0, "hour"), end=value(2, "hour")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="summary",
                unit="mg/L",
            ),
        ),
        seed=1,
    )


def dataset(
    *,
    role: DatasetRole = DatasetRole.EXTERNAL_VALIDATION,
    route: Route = Route.INTRAVENOUS,
    fraction: str = "total",
    unit: str = "ug/mL",
    time: float = 30,
) -> ObservedDataset:
    return ObservedDataset(
        dataset_id="dataset-001",
        role=role,
        study=ObservedStudy(
            study_id="study-001",
            title="Observed aciclovir PK",
            evidence_ids=("evidence-study",),
            population_description="Adults",
            intervention=intervention(route),
        ),
        observations=(
            ObservedPkObservation(
                observation_id="observation-001",
                subject_or_population_id="subject-001",
                time=value(time, "minute"),
                value=value(4.2, unit),
                analyte="aciclovir",
                matrix="plasma",
                fraction=fraction,
                measurement="concentration",
                evidence_ids=("evidence-observation",),
            ),
        ),
        license="CC-BY-4.0",
        source_identifier="doi:example",
        provenance_ids=("provenance-001",),
    )


def descriptor() -> PredictedPkSeriesDescriptor:
    return PredictedPkSeriesDescriptor(
        trial_arm_id="treatment",
        analyte="aciclovir",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
        unit="mg/L",
        time_unit="hour",
        sample_times=(value(0.5, "hour", ValueType.PREDICTED),),
    )


def test_external_matching_data_is_eligible_with_population_limitation() -> None:
    report = assess_validation_compatibility(trial(), dataset(), descriptor())

    assert report.eligibility is ValidationEligibility.ELIGIBLE_WITH_LIMITATIONS
    assert report.is_eligible
    assert report.has_limitations
    assert not report.has_mismatches


def test_held_out_matching_data_is_eligible_with_population_limitation() -> None:
    report = assess_validation_compatibility(
        trial(), dataset(role=DatasetRole.HELD_OUT_TEST), descriptor()
    )

    assert report.eligibility is ValidationEligibility.ELIGIBLE_WITH_LIMITATIONS


def test_mismatched_route_is_ineligible() -> None:
    report = assess_validation_compatibility(trial(), dataset(route=Route.ORAL), descriptor())

    assert report.eligibility is ValidationEligibility.INELIGIBLE
    assert any(
        item.field == "route" and item.status is CompatibilityStatus.MISMATCH
        for item in report.items
    )


def test_calibration_data_is_ineligible() -> None:
    report = assess_validation_compatibility(
        trial(), dataset(role=DatasetRole.CALIBRATION), descriptor()
    )

    assert report.eligibility is ValidationEligibility.INELIGIBLE
    assert any(
        item.field == "dataset_role" and item.status is CompatibilityStatus.MISMATCH
        for item in report.items
    )


def test_fraction_incompatible_unit_and_outside_sampling_window_are_rejected() -> None:
    fraction_report = assess_validation_compatibility(
        trial(), dataset(fraction="unbound"), descriptor()
    )
    unit_report = assess_validation_compatibility(trial(), dataset(unit="milligram"), descriptor())
    time_report = assess_validation_compatibility(trial(), dataset(time=180), descriptor())

    assert fraction_report.eligibility is ValidationEligibility.INELIGIBLE
    assert unit_report.eligibility is ValidationEligibility.INELIGIBLE
    assert time_report.eligibility is ValidationEligibility.INELIGIBLE
    assert any(
        item.field == "sample_times" and item.status is CompatibilityStatus.MISMATCH
        for item in time_report.items
    )


def test_convertible_observed_unit_is_a_match() -> None:
    report = assess_validation_compatibility(trial(), dataset(unit="ug/mL"), descriptor())

    assert (
        next(item for item in report.items if item.field == "observation_units").status
        is CompatibilityStatus.MATCH
    )
