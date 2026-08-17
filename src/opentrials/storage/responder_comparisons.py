"""Immutable Parquet artifacts for extreme-responder baseline comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.baseline_comparison import BaselineComparisonResult
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

RESPONDER_COMPARISON_ID_PREFIX = "OTXCMP-"
RESPONDER_COMPARISON_ARTIFACT_SCHEMA = "opentrials.extreme-responder-baseline-comparison-artifact"
NUMERIC_SUMMARIES_PATH = "numeric_summaries.parquet"
NUMERIC_COMPARISONS_PATH = "numeric_comparisons.parquet"
CATEGORICAL_SUMMARIES_PATH = "categorical_summaries.parquet"

NUMERIC_SUMMARY_COLUMNS = (
    "group_label",
    "membership_id",
    "field_id",
    "unit",
    "n_members",
    "mean",
    "sample_standard_deviation",
    "coefficient_of_variation",
    "minimum",
    "maximum",
    "p25",
    "p50",
    "p75",
)
NUMERIC_COMPARISON_COLUMNS = (
    "field_id",
    "unit",
    "extreme_mean",
    "reference_mean",
    "absolute_difference",
    "relative_difference",
)
CATEGORICAL_SUMMARY_COLUMNS = (
    "group_label",
    "membership_id",
    "field_id",
    "n_members",
    "category",
    "count",
)


def _semantic_value(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _semantic_table_hash(column_names: Sequence[str], rows: Sequence[Mapping[str, object]]) -> str:
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


def semantic_numeric_summary_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


def semantic_numeric_comparison_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


def semantic_categorical_summary_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


class ResponderComparisonTableArtifact(BaseModel):
    """Integrity details for one persisted OTXCMP table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rows: int = Field(ge=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ResponderComparisonArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one OTXCMP artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    comparison_id: str = Field(pattern=r"^OTXCMP-[A-Za-z0-9_-]+$")
    extreme_membership_id: str = Field(min_length=1)
    reference_membership_id: str = Field(min_length=1)
    extreme_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    reference_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    field_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    interpretation_note: str = Field(min_length=1)
    numeric_summaries: ResponderComparisonTableArtifact
    numeric_comparisons: ResponderComparisonTableArtifact
    categorical_summaries: ResponderComparisonTableArtifact


class ResponderComparisonArtifactStore:
    """Persist and reload immutable OTXCMP baseline-comparison artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_comparison(self, comparison_id: str) -> Path:
        if not comparison_id.startswith(RESPONDER_COMPARISON_ID_PREFIX):
            raise ValueError(
                f"Comparison IDs must begin with {RESPONDER_COMPARISON_ID_PREFIX!r}."
            )
        directory = self.root / comparison_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_comparison(
        self, comparison_id: str, result: BaselineComparisonResult
    ) -> ResponderComparisonArtifactManifest:
        """Persist an already-computed, already-verified comparison exactly once."""
        directory = self.root / comparison_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Comparison directory does not exist: {comparison_id!r}.")
        numeric_summaries_path = directory / NUMERIC_SUMMARIES_PATH
        numeric_comparisons_path = directory / NUMERIC_COMPARISONS_PATH
        categorical_summaries_path = directory / CATEGORICAL_SUMMARIES_PATH
        manifest_path = directory / "manifest.json"
        if any(
            path.exists()
            for path in (
                numeric_summaries_path,
                numeric_comparisons_path,
                categorical_summaries_path,
                manifest_path,
            )
        ):
            raise FileExistsError(f"Comparison artifacts already exist for: {comparison_id!r}.")

        numeric_summary_rows = tuple(
            {
                "group_label": summary.group_label,
                "membership_id": summary.membership_id,
                "field_id": summary.field_id,
                "unit": summary.unit,
                "n_members": summary.n_members,
                "mean": summary.summary.mean if summary.summary is not None else None,
                "sample_standard_deviation": (
                    summary.summary.sample_standard_deviation
                    if summary.summary is not None
                    else None
                ),
                "coefficient_of_variation": (
                    summary.summary.coefficient_of_variation
                    if summary.summary is not None
                    else None
                ),
                "minimum": summary.summary.minimum if summary.summary is not None else None,
                "maximum": summary.summary.maximum if summary.summary is not None else None,
                "p25": summary.summary.p25 if summary.summary is not None else None,
                "p50": summary.summary.p50 if summary.summary is not None else None,
                "p75": summary.summary.p75 if summary.summary is not None else None,
            }
            for summary in result.numeric_summaries
        )
        numeric_comparison_rows = tuple(
            {
                "field_id": comparison.field_id,
                "unit": comparison.unit,
                "extreme_mean": comparison.extreme_mean,
                "reference_mean": comparison.reference_mean,
                "absolute_difference": comparison.absolute_difference,
                "relative_difference": comparison.relative_difference,
            }
            for comparison in result.numeric_comparisons
        )
        categorical_summary_rows = tuple(
            {
                "group_label": summary.group_label,
                "membership_id": summary.membership_id,
                "field_id": summary.field_id,
                "n_members": summary.n_members,
                "category": category,
                "count": count,
            }
            for summary in result.categorical_summaries
            for category, count in summary.category_counts.items()
        )
        if not numeric_summary_rows and not categorical_summary_rows:
            raise ValueError("A baseline comparison requires at least one field summary.")

        _write_numeric_summary_table(numeric_summaries_path, numeric_summary_rows)
        _write_numeric_comparison_table(numeric_comparisons_path, numeric_comparison_rows)
        _write_categorical_summary_table(categorical_summaries_path, categorical_summary_rows)

        manifest = ResponderComparisonArtifactManifest(
            comparison_id=comparison_id,
            extreme_membership_id=result.extreme_membership_id,
            reference_membership_id=result.reference_membership_id,
            extreme_membership_semantic_sha256=result.extreme_membership_semantic_sha256,
            reference_membership_semantic_sha256=result.reference_membership_semantic_sha256,
            source_generation_id=result.source_generation_id,
            source_population_semantic_sha256=result.source_population_semantic_sha256,
            field_catalog_sha256=result.field_catalog_sha256,
            interpretation_note=result.interpretation_note,
            numeric_summaries=_table_artifact(
                NUMERIC_SUMMARIES_PATH,
                numeric_summaries_path,
                len(numeric_summary_rows),
                len(NUMERIC_SUMMARY_COLUMNS),
                semantic_numeric_summary_hash(NUMERIC_SUMMARY_COLUMNS, numeric_summary_rows),
            ),
            numeric_comparisons=_table_artifact(
                NUMERIC_COMPARISONS_PATH,
                numeric_comparisons_path,
                len(numeric_comparison_rows),
                len(NUMERIC_COMPARISON_COLUMNS),
                semantic_numeric_comparison_hash(
                    NUMERIC_COMPARISON_COLUMNS, numeric_comparison_rows
                ),
            ),
            categorical_summaries=_table_artifact(
                CATEGORICAL_SUMMARIES_PATH,
                categorical_summaries_path,
                len(categorical_summary_rows),
                len(CATEGORICAL_SUMMARY_COLUMNS),
                semantic_categorical_summary_hash(
                    CATEGORICAL_SUMMARY_COLUMNS, categorical_summary_rows
                ),
            ),
        )
        manifest_path.write_text(
            document(RESPONDER_COMPARISON_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, comparison_id: str) -> ResponderComparisonArtifactManifest:
        path = self.root / comparison_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid responder comparison manifest: {path}") from error
        if envelope.schema_id != RESPONDER_COMPARISON_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected responder comparison schema: {envelope.schema_id!r}.")
        return ResponderComparisonArtifactManifest.model_validate(envelope.payload)

    def verify_comparison(self, comparison_id: str) -> ResponderComparisonArtifactManifest:
        manifest = self.read_manifest(comparison_id)
        directory = self.root / comparison_id
        self._verify_table(
            directory / manifest.numeric_summaries.path,
            manifest.numeric_summaries,
            NUMERIC_SUMMARY_COLUMNS,
            semantic_numeric_summary_hash,
        )
        self._verify_table(
            directory / manifest.numeric_comparisons.path,
            manifest.numeric_comparisons,
            NUMERIC_COMPARISON_COLUMNS,
            semantic_numeric_comparison_hash,
        )
        self._verify_table(
            directory / manifest.categorical_summaries.path,
            manifest.categorical_summaries,
            CATEGORICAL_SUMMARY_COLUMNS,
            semantic_categorical_summary_hash,
        )
        return manifest

    @staticmethod
    def _verify_table(
        path: Path,
        artifact: ResponderComparisonTableArtifact,
        expected_columns: Sequence[str],
        hasher: Any,
    ) -> None:
        actual_file_sha256 = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_file_sha256 != artifact.file_sha256:
            raise ValueError(f"OTXCMP table Parquet file hash does not match its manifest: {path}.")
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != tuple(expected_columns)
            or table.num_rows != artifact.rows
            or table.num_columns != artifact.columns
        ):
            raise ValueError(f"OTXCMP table Parquet shape does not match its manifest: {path}.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if hasher(expected_columns, rows) != artifact.semantic_content_sha256:
            raise ValueError(
                f"OTXCMP table Parquet semantic hash does not match its manifest: {path}."
            )


def _table_artifact(
    path_name: str, path: Path, row_count: int, column_count: int, semantic_hash: str
) -> ResponderComparisonTableArtifact:
    return ResponderComparisonTableArtifact(
        path=path_name,
        rows=row_count,
        columns=column_count,
        file_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        semantic_content_sha256=semantic_hash,
    )


def _write_numeric_summary_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    text_columns = {"group_label", "membership_id", "field_id", "unit"}
    _write_typed_table(path, NUMERIC_SUMMARY_COLUMNS, rows, text_columns, int_columns={"n_members"})


def _write_numeric_comparison_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    _write_typed_table(
        path, NUMERIC_COMPARISON_COLUMNS, rows, text_columns={"field_id", "unit"}, int_columns=set()
    )


def _write_categorical_summary_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    _write_typed_table(
        path,
        CATEGORICAL_SUMMARY_COLUMNS,
        rows,
        text_columns={"group_label", "membership_id", "field_id", "category"},
        int_columns={"n_members", "count"},
    )


def _write_typed_table(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
    text_columns: set[str],
    int_columns: set[str],
) -> None:
    """Write a Parquet table with explicit column types, including when empty.

    Implicit type inference on an all-``None``/empty column can produce an
    ambiguous Arrow null-typed array; explicit typing keeps zero-row and
    zero-member cases (empty extreme tail, no categorical fields requested)
    well-defined artifacts rather than a silent edge case.
    """
    arrays = {}
    for column in columns:
        values = [row[column] for row in rows]
        if column in text_columns:
            arrays[column] = pa.array(values, type=pa.string())
        elif column in int_columns:
            arrays[column] = pa.array(values, type=pa.int64())
        else:
            arrays[column] = pa.array(values, type=pa.float64())
    pq.write_table(pa.table(arrays), path, compression="zstd")
