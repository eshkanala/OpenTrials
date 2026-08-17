import pytest

from opentrials.analysis.pk import PkEndpointType
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.validation.compatibility import (
    CompatibilityItem,
    CompatibilityStatus,
    PredictedPkSeriesDescriptor,
    ValidationCompatibilityReport,
    ValidationEligibility,
)
from opentrials.validation.engine import evaluate_pk_validation
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole

PREDICTED_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OBSERVED_HASH = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def value(amount: float, unit: str, value_type: ValueType = ValueType.OBSERVED) -> ScientificValue:
    return ScientificValue(value=amount, unit=unit, value_type=value_type)


def intervention() -> Intervention:
    return Intervention(
        intervention_id="intervention-1",
        compound=Compound(identity=CompoundIdentity(compound_id="compound-a", preferred_name="A")),
        regimen=Regimen(
            regimen_id="regimen-1",
            doses=(
                Dose(
                    amount=value(1, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=value(0, "h"),
                ),
            ),
        ),
    )


def observed_dataset(samples: tuple[tuple[str, float, float], ...]) -> ObservedDataset:
    return ObservedDataset(
        dataset_id="observed-1",
        role=DatasetRole.EXTERNAL_VALIDATION,
        study=ObservedStudy(
            study_id="study-1",
            title="Observed PK",
            evidence_ids=("evidence-study",),
            population_description="Adults",
            intervention=intervention(),
        ),
        observations=tuple(
            ObservedPkObservation(
                observation_id=f"observation-{index}",
                subject_or_population_id=subject_id,
                time=value(time, "min"),
                value=value(concentration, "ug/mL"),
                analyte="compound-a",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
                evidence_ids=(f"evidence-{index}",),
            )
            for index, (subject_id, time, concentration) in enumerate(samples)
        ),
        license="CC-BY-4.0",
        source_identifier="doi:example",
        provenance_ids=("provenance-1",),
    )


def descriptor() -> PredictedPkSeriesDescriptor:
    return PredictedPkSeriesDescriptor(
        trial_arm_id="arm-1",
        analyte="compound-a",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
        unit="mg/L",
        time_unit="h",
        sample_times=(
            value(0, "h", ValueType.PREDICTED),
            value(1, "h", ValueType.PREDICTED),
            value(2, "h", ValueType.PREDICTED),
        ),
    )


def report(
    eligibility: ValidationEligibility = ValidationEligibility.ELIGIBLE,
) -> ValidationCompatibilityReport:
    return ValidationCompatibilityReport(
        trial_id="trial-1",
        dataset_id="observed-1",
        eligibility=eligibility,
        items=(
            CompatibilityItem(field="all", status=CompatibilityStatus.MATCH, detail="Matches."),
        ),
    )


def row(subject_id: str, time: float, concentration: float) -> dict[str, object]:
    return {
        "subject_id": subject_id,
        "time": time,
        "time_unit": "h",
        "analyte": "compound-a",
        "matrix": "plasma",
        "fraction": "total",
        "measurement": "concentration",
        "value": concentration,
        "unit": "mg/L",
    }


def test_evaluates_known_residuals_endpoints_and_metrics() -> None:
    result = evaluate_pk_validation(
        report(),
        observed_dataset((("subject-1", 0, 1), ("subject-1", 60, 2), ("subject-1", 120, 1))),
        descriptor(),
        (row("subject-1", 0, 1.1), row("subject-1", 1, 2.2), row("subject-1", 2, 0.9)),
        PREDICTED_HASH,
        OBSERVED_HASH,
    )

    assert [point.residual.value for point in result.aligned_points] == pytest.approx(
        (0.1, 0.2, -0.1)
    )
    assert [point.relative_error for point in result.aligned_points] == pytest.approx(
        (0.1, 0.1, -0.1)
    )
    endpoints = {comparison.endpoint_type: comparison for comparison in result.endpoint_comparisons}
    assert endpoints[PkEndpointType.CMAX].residual.value == pytest.approx(0.2)
    assert endpoints[PkEndpointType.TMAX].residual.value == 0.0
    assert endpoints[PkEndpointType.AUC_0_LAST].residual.value == pytest.approx(0.2)
    metrics = {metric.metric_id: metric for metric in result.metrics}
    assert metrics["mean_signed_error"].value == pytest.approx(0.2 / 3)
    assert metrics["mean_signed_error"].unit == "mg/L"
    assert metrics["mean_absolute_percentage_error"].value == pytest.approx(0.1)
    assert metrics["mean_absolute_percentage_error"].unit == "1"


def test_refuses_ineligible_compatibility() -> None:
    with pytest.raises(ValueError, match="INELIGIBLE"):
        evaluate_pk_validation(
            report(ValidationEligibility.INELIGIBLE),
            observed_dataset((("subject-1", 0, 1),)),
            descriptor(),
            (row("subject-1", 0, 1),),
            PREDICTED_HASH,
            OBSERVED_HASH,
        )


@pytest.mark.parametrize(
    ("samples", "rows", "message"),
    [
        (
            (("subject-1", 30, 1),),
            (row("subject-1", 0, 1),),
            "sample times",
        ),
        (
            (("subject-2", 0, 1),),
            (row("subject-1", 0, 1),),
            "subject identities",
        ),
    ],
)
def test_rejects_nonexact_time_alignment_or_subject_identity(
    samples: tuple[tuple[str, float, float], ...], rows: tuple[dict[str, object], ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate_pk_validation(
            report(), observed_dataset(samples), descriptor(), rows, PREDICTED_HASH, OBSERVED_HASH
        )
