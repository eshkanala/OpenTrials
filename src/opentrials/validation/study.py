"""Validation-study and validation-result scientific contracts."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue


class DatasetRole(StrEnum):
    """The permitted role of a dataset in model development and evaluation."""

    TRAINING = "TRAINING"
    CALIBRATION = "CALIBRATION"
    INTERNAL_VALIDATION = "INTERNAL_VALIDATION"
    EXTERNAL_VALIDATION = "EXTERNAL_VALIDATION"
    HELD_OUT_TEST = "HELD_OUT_TEST"


class ValidationStatus(StrEnum):
    """The conclusion of a validation study, distinct from run success."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class MetricComparator(StrEnum):
    """Acceptance directions for predefined validation metrics."""

    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"


class ValidationDataset(BaseModel):
    """An immutable reference to data used in calibration or validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    role: DatasetRole
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    license: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)


class MetricDefinition(BaseModel):
    """A predefined metric and acceptance criterion for a validation study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    comparator: MetricComparator
    threshold: ScientificValue


class ValidationStudy(BaseModel):
    """A predeclared scientific validation protocol for a model/run context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    context_of_use: str = Field(min_length=1)
    datasets: tuple[ValidationDataset, ...] = Field(min_length=1)
    metrics: tuple[MetricDefinition, ...] = Field(min_length=1)
    exclusion_rules: tuple[str, ...] = ()
    acceptance_criteria_description: str | None = None

    @model_validator(mode="after")
    def validate_design(self) -> ValidationStudy:
        dataset_ids = tuple(dataset.dataset_id for dataset in self.datasets)
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("Validation-study dataset IDs must be unique.")
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("Validation-study metric IDs must be unique.")
        evaluation_roles = {DatasetRole.EXTERNAL_VALIDATION, DatasetRole.HELD_OUT_TEST}
        if not any(dataset.role in evaluation_roles for dataset in self.datasets):
            raise ValueError(
                "Validation studies require external-validation or held-out-test data."
            )
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically before a validation is executed."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class MetricResult(BaseModel):
    """Predicted and observed values for one predefined validation metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str = Field(min_length=1)
    predicted: ScientificValue
    observed: ScientificValue
    score: ScientificValue | None = None

    @model_validator(mode="after")
    def validate_dimensions(self) -> MetricResult:
        try:
            self.observed.to(self.predicted.unit)
        except UnitCompatibilityError as error:
            raise ValueError(
                "Predicted and observed metric values must have compatible units."
            ) from error
        return self


class ValidationResult(BaseModel):
    """Immutable recorded outcome of applying a validation study to a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_result_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: ValidationStatus
    metric_results: tuple[MetricResult, ...] = ()
    failures: tuple[str, ...] = ()
    conclusion: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_conclusion(self) -> ValidationResult:
        metric_ids = tuple(result.metric_id for result in self.metric_results)
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("Validation-result metric IDs must be unique.")
        if self.status is ValidationStatus.FAILED and not self.failures:
            raise ValueError("Failed validation results must record at least one failure.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for reports and reproducibility manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
