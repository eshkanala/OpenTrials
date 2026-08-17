from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.validation import (
    DatasetRole,
    MetricComparator,
    MetricDefinition,
    MetricResult,
    ValidationDataset,
    ValidationResult,
    ValidationStatus,
    ValidationStudy,
)

HASH = "sha256:" + "c" * 64


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def external_dataset() -> ValidationDataset:
    return ValidationDataset(
        dataset_id="external-pk-001",
        role=DatasetRole.EXTERNAL_VALIDATION,
        content_hash=HASH,
        license="CC-BY-4.0",
        source_identifier="doi:10.0000/example",
    )


def test_validation_study_requires_independent_evaluation_data() -> None:
    with pytest.raises(ValidationError, match="external-validation or held-out-test"):
        ValidationStudy(
            study_id="calibration-only",
            question="Does the model reproduce exposure?",
            context_of_use="research",
            datasets=(external_dataset().model_copy(update={"role": DatasetRole.CALIBRATION}),),
            metrics=(
                MetricDefinition(
                    metric_id="auc-error",
                    description="AUC relative error",
                    comparator=MetricComparator.LESS_THAN_OR_EQUAL,
                    threshold=observed(0.25, "dimensionless"),
                ),
            ),
        )


def test_metric_results_require_compatible_prediction_and_observation() -> None:
    with pytest.raises(ValidationError, match="compatible units"):
        MetricResult(metric_id="auc", predicted=observed(10, "mg*h/L"), observed=observed(4, "kg"))


def test_failed_validation_requires_recorded_failure() -> None:
    with pytest.raises(ValidationError, match="record at least one failure"):
        ValidationResult(
            validation_result_id="validation-001",
            study_id="study-001",
            run_id="OTR-001",
            status=ValidationStatus.FAILED,
            conclusion="Model did not meet acceptance criteria.",
            created_at=datetime(2026, 8, 16, tzinfo=UTC),
        )


def test_validation_result_serializes_deterministically() -> None:
    result = ValidationResult(
        validation_result_id="validation-001",
        study_id="study-001",
        run_id="OTR-001",
        status=ValidationStatus.PASSED,
        metric_results=(
            MetricResult(
                metric_id="auc", predicted=observed(10, "mg/L"), observed=observed(9, "mg/L")
            ),
        ),
        conclusion="Acceptance criteria met.",
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert '"status":"PASSED"' in result.canonical_json()
