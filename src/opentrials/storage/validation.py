"""Immutable, table-backed storage for PK validation artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.pk import PkEndpointType
from opentrials.core.scientific_value import ScientificValue
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.validation.compatibility import ValidationCompatibilityReport, ValidationEligibility
from opentrials.validation.engine import (
    AlignedPkPoint,
    EndpointComparison,
    ValidationEngineResult,
    ValidationMetric,
)
from opentrials.validation.study import DatasetRole

VALIDATION_ID_PREFIX = "OTVAL-"
VALIDATION_ARTIFACT_SCHEMA = "opentrials.validation-artifact"
ALIGNMENT_PATH = "alignment.parquet"
ENDPOINT_COMPARISONS_PATH = "endpoint_comparisons.parquet"
METRICS_PATH = "metrics.parquet"
ALIGNMENT_COLUMNS = (
    "subject_id",
    "time_value",
    "time_unit",
    "time_scientific_value_json",
    "predicted_value",
    "predicted_unit",
    "predicted_scientific_value_json",
    "observed_value",
    "observed_unit",
    "observed_scientific_value_json",
    "residual_value",
    "residual_unit",
    "residual_scientific_value_json",
    "relative_error",
)
ENDPOINT_COMPARISON_COLUMNS = (
    "subject_id",
    "endpoint_type",
    "predicted_value",
    "predicted_unit",
    "predicted_scientific_value_json",
    "observed_value",
    "observed_unit",
    "observed_scientific_value_json",
    "residual_value",
    "residual_unit",
    "residual_scientific_value_json",
    "relative_error",
)
METRICS_COLUMNS = ("metric_id", "value", "unit", "description")


def _semantic_value(value: object) -> object:
    """Normalize equivalent Arrow numeric scalar representations before hashing."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_validation_table_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash a logical validation table independently of Parquet byte encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


def semantic_alignment_hash(rows: Sequence[Mapping[str, object]]) -> str:
    """Return the semantic identity of an alignment table."""
    return semantic_validation_table_hash(ALIGNMENT_COLUMNS, rows)


def semantic_endpoint_comparisons_hash(rows: Sequence[Mapping[str, object]]) -> str:
    """Return the semantic identity of an endpoint-comparison table."""
    return semantic_validation_table_hash(ENDPOINT_COMPARISON_COLUMNS, rows)


def semantic_metrics_hash(rows: Sequence[Mapping[str, object]]) -> str:
    """Return the semantic identity of a validation-metrics table."""
    return semantic_validation_table_hash(METRICS_COLUMNS, rows)


class ValidationTableArtifact(BaseModel):
    """Integrity details for one persisted validation table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ValidationArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for a validation comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    validation_id: str = Field(pattern=r"^OTVAL-[A-Za-z0-9_-]+$")
    source_predicted_result_sha256: str = Field(pattern=SHA256_PATTERN)
    source_observed_dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    trial_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_role: DatasetRole
    compatibility_report: ValidationCompatibilityReport
    compatibility_report_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    validation_engine_result_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    alignment: ValidationTableArtifact
    endpoint_comparisons: ValidationTableArtifact
    metrics: ValidationTableArtifact


def _alignment_rows(result: ValidationEngineResult) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "subject_id": point.subject_id,
            "time_value": point.time.value,
            "time_unit": point.time.unit,
            "time_scientific_value_json": point.time.canonical_json(),
            "predicted_value": point.predicted.value,
            "predicted_unit": point.predicted.unit,
            "predicted_scientific_value_json": point.predicted.canonical_json(),
            "observed_value": point.observed.value,
            "observed_unit": point.observed.unit,
            "observed_scientific_value_json": point.observed.canonical_json(),
            "residual_value": point.residual.value,
            "residual_unit": point.residual.unit,
            "residual_scientific_value_json": point.residual.canonical_json(),
            "relative_error": point.relative_error,
        }
        for point in result.aligned_points
    )


def _endpoint_comparison_rows(result: ValidationEngineResult) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "subject_id": comparison.subject_id,
            "endpoint_type": comparison.endpoint_type.value,
            "predicted_value": comparison.predicted.value,
            "predicted_unit": comparison.predicted.unit,
            "predicted_scientific_value_json": comparison.predicted.canonical_json(),
            "observed_value": comparison.observed.value,
            "observed_unit": comparison.observed.unit,
            "observed_scientific_value_json": comparison.observed.canonical_json(),
            "residual_value": comparison.residual.value,
            "residual_unit": comparison.residual.unit,
            "residual_scientific_value_json": comparison.residual.canonical_json(),
            "relative_error": comparison.relative_error,
        }
        for comparison in result.endpoint_comparisons
    )


def _metric_rows(result: ValidationEngineResult) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "metric_id": metric.metric_id,
            "value": metric.value,
            "unit": metric.unit,
            "description": metric.description,
        }
        for metric in result.metrics
    )


class ValidationArtifactStore:
    """Persist immutable validation-engine outputs by validation artifact ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_validation(self, validation_id: str) -> Path:
        """Create the unique directory for one validation artifact."""
        if not validation_id.startswith(VALIDATION_ID_PREFIX):
            raise ValueError(f"Validation artifact IDs must begin with {VALIDATION_ID_PREFIX!r}.")
        directory = self.root / validation_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_validation(
        self,
        validation_id: str,
        *,
        result: ValidationEngineResult,
        source_predicted_result_sha256: str,
        source_observed_dataset_sha256: str,
        dataset_role: DatasetRole,
    ) -> ValidationArtifactManifest:
        """Write an eligible validation result exactly once with complete integrity metadata."""
        directory = self.root / validation_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Validation artifact directory does not exist: {validation_id!r}."
            )
        paths = tuple(
            directory / path
            for path in (ALIGNMENT_PATH, ENDPOINT_COMPARISONS_PATH, METRICS_PATH, "manifest.json")
        )
        if any(path.exists() for path in paths):
            raise FileExistsError(
                f"Validation artifacts already exist for validation ID: {validation_id!r}."
            )
        if result.compatibility_report.eligibility is ValidationEligibility.INELIGIBLE:
            raise ValueError("Cannot persist an INELIGIBLE validation result.")
        if re.fullmatch(SHA256_PATTERN, source_predicted_result_sha256) is None:
            raise ValueError("Source predicted result hash must use the sha256:<hex> format.")
        if re.fullmatch(SHA256_PATTERN, source_observed_dataset_sha256) is None:
            raise ValueError("Source observed dataset hash must use the sha256:<hex> format.")

        tables = (
            (ALIGNMENT_PATH, ALIGNMENT_COLUMNS, _alignment_rows(result)),
            (
                ENDPOINT_COMPARISONS_PATH,
                ENDPOINT_COMPARISON_COLUMNS,
                _endpoint_comparison_rows(result),
            ),
            (METRICS_PATH, METRICS_COLUMNS, _metric_rows(result)),
        )
        artifacts: dict[str, ValidationTableArtifact] = {}
        for path, columns, rows in tables:
            parquet_path = directory / path
            table = pa.table({column: [row[column] for row in rows] for column in columns})
            pq.write_table(table, parquet_path, compression="zstd")
            artifacts[path] = ValidationTableArtifact(
                path=path,
                rows=len(rows),
                columns=len(columns),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_validation_table_hash(columns, rows),
            )

        report = result.compatibility_report
        manifest = ValidationArtifactManifest(
            validation_id=validation_id,
            source_predicted_result_sha256=source_predicted_result_sha256,
            source_observed_dataset_sha256=source_observed_dataset_sha256,
            trial_id=report.trial_id,
            dataset_id=report.dataset_id,
            dataset_role=dataset_role,
            compatibility_report=report,
            compatibility_report_canonical_sha256=sha256(report),
            validation_engine_result_semantic_sha256=sha256(result),
            alignment=artifacts[ALIGNMENT_PATH],
            endpoint_comparisons=artifacts[ENDPOINT_COMPARISONS_PATH],
            metrics=artifacts[METRICS_PATH],
        )
        (directory / "manifest.json").write_text(
            document(VALIDATION_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def read_manifest(self, validation_id: str) -> ValidationArtifactManifest:
        """Load and validate a schema-enveloped validation artifact manifest."""
        path = self.root / validation_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid validation manifest: {path}") from error
        if manifest_document.schema_id != VALIDATION_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected validation manifest schema: {manifest_document.schema_id!r}."
            )
        return ValidationArtifactManifest.model_validate(manifest_document.payload)

    def verify_validation(self, validation_id: str) -> ValidationArtifactManifest:
        """Verify validation provenance plus the byte and semantic hashes of every table."""
        manifest = self.read_manifest(validation_id)
        if manifest.validation_id != validation_id:
            raise ValueError("Validation manifest ID does not match its directory ID.")
        if manifest.compatibility_report.eligibility is ValidationEligibility.INELIGIBLE:
            raise ValueError("Validation artifact contains an INELIGIBLE compatibility report.")
        if sha256(manifest.compatibility_report) != manifest.compatibility_report_canonical_sha256:
            raise ValueError("Validation compatibility report hash does not match its manifest.")

        verified_rows: dict[str, tuple[dict[str, object], ...]] = {}
        for artifact, columns in (
            (manifest.alignment, ALIGNMENT_COLUMNS),
            (manifest.endpoint_comparisons, ENDPOINT_COMPARISON_COLUMNS),
            (manifest.metrics, METRICS_COLUMNS),
        ):
            parquet_path = self.root / validation_id / artifact.path
            actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
            if actual_file_sha256 != artifact.file_sha256:
                raise ValueError(
                    f"Validation table file hash does not match its manifest: {artifact.path}"
                )
            table = pq.read_table(parquet_path)
            actual_columns = tuple(table.column_names)
            rows = tuple(dict(row) for row in table.to_pylist())
            if len(rows) != artifact.rows or len(actual_columns) != artifact.columns:
                raise ValueError(
                    f"Validation table dimensions do not match its manifest: {artifact.path}"
                )
            if actual_columns != columns:
                raise ValueError(
                    f"Validation table columns do not match its manifest: {artifact.path}"
                )
            if (
                semantic_validation_table_hash(actual_columns, rows)
                != artifact.semantic_content_sha256
            ):
                raise ValueError(
                    "Validation table semantic content hash does not match its manifest: "
                    f"{artifact.path}"
                )
            verified_rows[artifact.path] = rows

        try:
            reconstructed = ValidationEngineResult(
                compatibility_report=manifest.compatibility_report,
                aligned_points=tuple(
                    AlignedPkPoint(
                        subject_id=str(row["subject_id"]),
                        time=ScientificValue.model_validate_json(
                            str(row["time_scientific_value_json"])
                        ),
                        predicted=ScientificValue.model_validate_json(
                            str(row["predicted_scientific_value_json"])
                        ),
                        observed=ScientificValue.model_validate_json(
                            str(row["observed_scientific_value_json"])
                        ),
                        residual=ScientificValue.model_validate_json(
                            str(row["residual_scientific_value_json"])
                        ),
                        relative_error=float(cast(float | int | str, row["relative_error"])),
                    )
                    for row in verified_rows[ALIGNMENT_PATH]
                ),
                endpoint_comparisons=tuple(
                    EndpointComparison(
                        subject_id=str(row["subject_id"]),
                        endpoint_type=PkEndpointType(str(row["endpoint_type"])),
                        predicted=ScientificValue.model_validate_json(
                            str(row["predicted_scientific_value_json"])
                        ),
                        observed=ScientificValue.model_validate_json(
                            str(row["observed_scientific_value_json"])
                        ),
                        residual=ScientificValue.model_validate_json(
                            str(row["residual_scientific_value_json"])
                        ),
                        relative_error=float(cast(float | int | str, row["relative_error"])),
                    )
                    for row in verified_rows[ENDPOINT_COMPARISONS_PATH]
                ),
                metrics=tuple(
                    ValidationMetric(
                        metric_id=str(row["metric_id"]),
                        value=float(cast(float | int | str, row["value"])),
                        unit=str(row["unit"]),
                        description=str(row["description"]),
                    )
                    for row in verified_rows[METRICS_PATH]
                ),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Persisted validation tables cannot reconstruct the engine result."
            ) from error
        if sha256(reconstructed) != manifest.validation_engine_result_semantic_sha256:
            raise ValueError("Validation engine result semantic hash does not match its manifest.")
        return manifest
