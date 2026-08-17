from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.analysis.pk import PkEndpointType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.storage.validation import (
    ALIGNMENT_COLUMNS,
    ENDPOINT_COMPARISON_COLUMNS,
    METRICS_COLUMNS,
    ValidationArtifactStore,
    semantic_validation_table_hash,
)
from opentrials.validation.compatibility import (
    CompatibilityItem,
    CompatibilityStatus,
    ValidationCompatibilityReport,
    ValidationEligibility,
)
from opentrials.validation.engine import (
    AlignedPkPoint,
    EndpointComparison,
    ValidationEngineResult,
    ValidationMetric,
)
from opentrials.validation.study import DatasetRole

PREDICTED_HASH = "sha256:" + "a" * 64
OBSERVED_HASH = "sha256:" + "b" * 64


def value(number: float, unit: str, value_type: ValueType) -> ScientificValue:
    return ScientificValue(value=number, unit=unit, value_type=value_type)


def result(
    eligibility: ValidationEligibility = ValidationEligibility.ELIGIBLE,
) -> ValidationEngineResult:
    report = ValidationCompatibilityReport(
        trial_id="OTRIAL-001",
        dataset_id="OTOBS-001",
        eligibility=eligibility,
        items=(
            CompatibilityItem(
                field="all", status=CompatibilityStatus.MATCH, detail="All required criteria match."
            ),
        ),
    )
    return ValidationEngineResult(
        compatibility_report=report,
        aligned_points=(
            AlignedPkPoint(
                subject_id="subject-1",
                time=value(60, "min", ValueType.DERIVED),
                predicted=value(12, "mg/L", ValueType.PREDICTED),
                observed=value(10, "mg/L", ValueType.OBSERVED),
                residual=value(2, "mg/L", ValueType.DERIVED),
                relative_error=0.2,
            ),
        ),
        endpoint_comparisons=(
            EndpointComparison(
                subject_id="subject-1",
                endpoint_type=PkEndpointType.CMAX,
                predicted=value(12, "mg/L", ValueType.PREDICTED),
                observed=value(10, "mg/L", ValueType.OBSERVED),
                residual=value(2, "mg/L", ValueType.DERIVED),
                relative_error=0.2,
            ),
        ),
        metrics=(
            ValidationMetric(
                metric_id="mean_signed_error",
                value=2,
                unit="mg/L",
                description="Mean predicted minus observed concentration.",
            ),
        ),
    )


def test_validation_artifact_writes_reloads_and_verifies_all_tables(tmp_path: Path) -> None:
    store = ValidationArtifactStore(tmp_path / "validations")
    directory = store.create_validation("OTVAL-001")
    written = store.write_validation(
        "OTVAL-001",
        result=result(),
        source_predicted_result_sha256=PREDICTED_HASH,
        source_observed_dataset_sha256=OBSERVED_HASH,
        dataset_role=DatasetRole.EXTERNAL_VALIDATION,
    )

    reloaded = store.verify_validation("OTVAL-001")

    assert reloaded == written
    assert pq.read_table(directory / "alignment.parquet").column_names == list(ALIGNMENT_COLUMNS)
    assert pq.read_table(directory / "endpoint_comparisons.parquet").column_names == list(
        ENDPOINT_COMPARISON_COLUMNS
    )
    assert pq.read_table(directory / "metrics.parquet").column_names == list(METRICS_COLUMNS)
    assert written.dataset_id == "OTOBS-001"
    assert written.dataset_role is DatasetRole.EXTERNAL_VALIDATION
    assert '"schema":"opentrials.validation-artifact"' in (directory / "manifest.json").read_text()


def test_validation_artifact_refuses_ineligible_result(tmp_path: Path) -> None:
    store = ValidationArtifactStore(tmp_path / "validations")
    store.create_validation("OTVAL-001")

    with pytest.raises(ValueError, match="INELIGIBLE"):
        store.write_validation(
            "OTVAL-001",
            result=result(ValidationEligibility.INELIGIBLE),
            source_predicted_result_sha256=PREDICTED_HASH,
            source_observed_dataset_sha256=OBSERVED_HASH,
            dataset_role=DatasetRole.EXTERNAL_VALIDATION,
        )


def test_validation_artifact_is_immutable(tmp_path: Path) -> None:
    store = ValidationArtifactStore(tmp_path / "validations")
    store.create_validation("OTVAL-001")
    engine_result = result()
    store.write_validation(
        "OTVAL-001",
        result=engine_result,
        source_predicted_result_sha256=PREDICTED_HASH,
        source_observed_dataset_sha256=OBSERVED_HASH,
        dataset_role=DatasetRole.EXTERNAL_VALIDATION,
    )

    with pytest.raises(FileExistsError, match="already exist"):
        store.write_validation(
            "OTVAL-001",
            result=engine_result,
            source_predicted_result_sha256=PREDICTED_HASH,
            source_observed_dataset_sha256=OBSERVED_HASH,
            dataset_role=DatasetRole.EXTERNAL_VALIDATION,
        )


def test_validation_semantic_hash_normalizes_equivalent_numeric_cells() -> None:
    integer_rows = ({"subject_id": "subject-1", "value": 1, "relative_error": 0},)
    float_rows = ({"subject_id": "subject-1", "value": 1.0, "relative_error": 0.0},)

    assert semantic_validation_table_hash(
        ("subject_id", "value", "relative_error"), integer_rows
    ) == semantic_validation_table_hash(("subject_id", "value", "relative_error"), float_rows)
