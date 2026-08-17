"""Normalization and immutable storage for selected OSP concentration-time results."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

RESULT_ID_PREFIX = "OTRES-"
RESULT_ARTIFACT_SCHEMA = "opentrials.result-artifact"
CONCENTRATION_TIME_PATH = "concentration_time.parquet"
CONCENTRATION_TIME_COLUMNS = (
    "subject_id",
    "time",
    "time_unit",
    "analyte",
    "matrix",
    "fraction",
    "measurement",
    "value",
    "unit",
    "source_engine",
    "source_path",
    "source_value",
    "source_unit",
    "conversion_policy",
)


class ConversionPolicy(StrEnum):
    """Declared policy used to create canonical concentration-time values."""

    PRESERVE_SOURCE = "PRESERVE_SOURCE"


class ResultSelectionMapping(BaseModel):
    """Explicit metadata and raw-column mapping for one OSP output path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    analyte: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    time_unit: str = Field(min_length=1)
    subject_id_column: str = Field(default="IndividualId", min_length=1)
    time_column: str = Field(default="Time", min_length=1)
    value_column: str = Field(default="simulationValues", min_length=1)
    unit_column: str = Field(default="unit", min_length=1)
    source_path_column: str = Field(default="paths", min_length=1)


class ConcentrationTimeTableArtifact(BaseModel):
    """Integrity details for the normalized concentration-time table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = CONCENTRATION_TIME_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ResultArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one result artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    result_id: str = Field(pattern=r"^OTRES-[A-Za-z0-9_-]+$")
    source_raw_result_sha256: str = Field(pattern=SHA256_PATTERN)
    engine_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    selection: ResultSelectionMapping
    conversion_policy: ConversionPolicy
    concentration_time: ConcentrationTimeTableArtifact


def _semantic_value(value: object) -> object:
    """Normalize equivalent numeric scalar types before canonical hashing."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_concentration_time_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash a logical concentration-time table independently of Parquet encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


def _required_value(row: Mapping[str, object], column: str, row_index: int) -> object:
    try:
        value = row[column]
    except KeyError as error:
        raise ValueError(
            f"Raw result row {row_index} is missing required field {column!r}."
        ) from error
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Raw result row {row_index} has an empty required field {column!r}.")
    return value


def _finite_number(value: object, field: str, row_index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Raw result row {row_index} field {field!r} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Raw result row {row_index} field {field!r} must be finite.")
    return number


def normalize_osp_concentration_time_rows(
    raw_rows: Sequence[Mapping[str, object]],
    selection: ResultSelectionMapping,
    *,
    source_engine: str = "osp",
    conversion_policy: ConversionPolicy = ConversionPolicy.PRESERVE_SOURCE,
) -> tuple[dict[str, object], ...]:
    """Select one OSP path and produce lossless, canonical concentration-time rows.

    ``PRESERVE_SOURCE`` deliberately applies no unit or value conversion: canonical
    ``value``/``unit`` are copied from ``source_value``/``source_unit``.
    """
    if not source_engine.strip():
        raise ValueError("Source engine must be a non-empty string.")
    if conversion_policy is not ConversionPolicy.PRESERVE_SOURCE:
        raise ValueError(f"Unsupported conversion policy: {conversion_policy!r}.")
    if not raw_rows:
        raise ValueError("At least one raw result row is required.")

    normalized: list[dict[str, object]] = []
    for row_index, row in enumerate(raw_rows):
        raw_path = _required_value(row, selection.source_path_column, row_index)
        if raw_path != selection.source_path:
            raise ValueError(
                f"Raw result row {row_index} source path {raw_path!r} does not match "
                f"the selected source path {selection.source_path!r}."
            )
        subject_id = _required_value(row, selection.subject_id_column, row_index)
        raw_time = _required_value(row, selection.time_column, row_index)
        raw_value = _required_value(row, selection.value_column, row_index)
        raw_unit = _required_value(row, selection.unit_column, row_index)
        time = _finite_number(raw_time, selection.time_column, row_index)
        source_value = _finite_number(raw_value, selection.value_column, row_index)
        if not isinstance(raw_unit, str):
            raise ValueError(
                f"Raw result row {row_index} field {selection.unit_column!r} must be text."
            )

        normalized.append(
            {
                "subject_id": str(subject_id),
                "time": time,
                "time_unit": selection.time_unit,
                "analyte": selection.analyte,
                "matrix": selection.matrix,
                "fraction": selection.fraction,
                "measurement": selection.measurement,
                "value": source_value,
                "unit": raw_unit,
                "source_engine": source_engine,
                "source_path": raw_path,
                "source_value": source_value,
                "source_unit": raw_unit,
                "conversion_policy": conversion_policy.value,
            }
        )
    return tuple(normalized)


class ResultArtifactStore:
    """Persist immutable normalized concentration-time artifacts by result ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_result(self, result_id: str) -> Path:
        """Create the unique directory that will contain one result artifact."""
        if not result_id.startswith(RESULT_ID_PREFIX):
            raise ValueError(f"Result IDs must begin with {RESULT_ID_PREFIX!r}.")
        directory = self.root / result_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_concentration_time(
        self,
        result_id: str,
        *,
        source_raw_result: object,
        raw_rows: Sequence[Mapping[str, object]],
        engine_id: str,
        model_id: str,
        run_id: str,
        selection: ResultSelectionMapping,
        conversion_policy: ConversionPolicy = ConversionPolicy.PRESERVE_SOURCE,
    ) -> ResultArtifactManifest:
        """Normalize and write a selected OSP concentration-time result exactly once."""
        directory = self.root / result_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Result directory does not exist: {result_id!r}.")
        parquet_path = directory / CONCENTRATION_TIME_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Result artifacts already exist for result: {result_id!r}.")
        rows = normalize_osp_concentration_time_rows(
            raw_rows,
            selection,
            source_engine=engine_id,
            conversion_policy=conversion_policy,
        )
        table = pa.table(
            {column: [row[column] for row in rows] for column in CONCENTRATION_TIME_COLUMNS}
        )
        pq.write_table(table, parquet_path, compression="zstd")
        manifest = ResultArtifactManifest(
            result_id=result_id,
            source_raw_result_sha256=sha256(source_raw_result),
            engine_id=engine_id,
            model_id=model_id,
            run_id=run_id,
            selection=selection,
            conversion_policy=conversion_policy,
            concentration_time=ConcentrationTimeTableArtifact(
                rows=len(rows),
                columns=len(CONCENTRATION_TIME_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_concentration_time_hash(
                    CONCENTRATION_TIME_COLUMNS, rows
                ),
            ),
        )
        manifest_document = document(RESULT_ARTIFACT_SCHEMA, manifest)
        manifest_path.write_text(manifest_document.canonical_json() + "\n", encoding="utf-8")
        return manifest

    def read_manifest(self, result_id: str) -> ResultArtifactManifest:
        """Load and validate a result artifact manifest envelope."""
        path = self.root / result_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid result manifest: {path}") from error
        if manifest_document.schema_id != RESULT_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected result manifest schema: {manifest_document.schema_id!r}.")
        return ResultArtifactManifest.model_validate(manifest_document.payload)

    def verify_result(self, result_id: str) -> ResultArtifactManifest:
        """Verify persisted Parquet bytes and its logical concentration-time table."""
        manifest = self.read_manifest(result_id)
        parquet_path = self.root / result_id / manifest.concentration_time.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.concentration_time.file_sha256:
            raise ValueError("Result Parquet file hash does not match its manifest.")
        table = pq.read_table(parquet_path)
        columns = tuple(table.column_names)
        rows = tuple(dict(row) for row in table.to_pylist())
        actual_semantic_sha256 = semantic_concentration_time_hash(columns, rows)
        if actual_semantic_sha256 != manifest.concentration_time.semantic_content_sha256:
            raise ValueError("Result Parquet semantic content hash does not match its manifest.")
        return manifest
