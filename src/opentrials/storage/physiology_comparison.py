"""Immutable Parquet artifacts for paired cross-physiology-state PK comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.physiology_comparison import (
    PhysiologyComparisonMissingness,
    PhysiologyTrialComparisonResult,
)
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.physiology.overrides import PhysiologyCoverageReport

PHYSIOLOGY_COMPARISON_ID_PREFIX = "OTPHYCMP-"
PHYSIOLOGY_COMPARISON_ARTIFACT_SCHEMA = "opentrials.physiology-trial-comparison-artifact"
STATE_SUMMARIES_PATH = "state_summaries.parquet"
SUBJECT_DELTAS_PATH = "subject_deltas.parquet"

STATE_SUMMARY_COLUMNS = (
    "state_id",
    "endpoint_type",
    "unit",
    "n",
    "mean",
    "sample_standard_deviation",
    "coefficient_of_variation",
    "minimum",
    "maximum",
    "p25",
    "p50",
    "p75",
)
SUBJECT_DELTA_COLUMNS = (
    "subject_id",
    "endpoint_type",
    "unit",
    "baseline_state_id",
    "comparison_state_id",
    "baseline_value",
    "comparison_value",
    "absolute_difference",
    "relative_difference",
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


def semantic_state_summary_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


def semantic_subject_delta_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


class PhysiologyComparisonTableArtifact(BaseModel):
    """Integrity details for one persisted OTPHYCMP table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rows: int = Field(ge=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class PhysiologyComparisonArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one OTPHYCMP artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    comparison_id: str = Field(pattern=r"^OTPHYCMP-[A-Za-z0-9_-]+$")
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    baseline_state_id: str = Field(min_length=1)
    state_physiology_population_ids: dict[str, str]
    state_endpoint_ids: dict[str, str]
    state_endpoint_semantic_sha256: dict[str, str]
    missingness: PhysiologyComparisonMissingness
    coverage: PhysiologyCoverageReport
    interpretation_note: str = Field(min_length=1)
    state_summaries: PhysiologyComparisonTableArtifact
    subject_deltas: PhysiologyComparisonTableArtifact


class PhysiologyComparisonArtifactStore:
    """Persist and reload immutable OTPHYCMP cross-physiology-state comparisons."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_comparison(self, comparison_id: str) -> Path:
        if not comparison_id.startswith(PHYSIOLOGY_COMPARISON_ID_PREFIX):
            raise ValueError(
                f"Comparison IDs must begin with {PHYSIOLOGY_COMPARISON_ID_PREFIX!r}."
            )
        directory = self.root / comparison_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_comparison(
        self, comparison_id: str, result: PhysiologyTrialComparisonResult
    ) -> PhysiologyComparisonArtifactManifest:
        """Persist an already-computed, already-verified comparison exactly once."""
        directory = self.root / comparison_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Comparison directory does not exist: {comparison_id!r}.")
        state_summaries_path = directory / STATE_SUMMARIES_PATH
        subject_deltas_path = directory / SUBJECT_DELTAS_PATH
        manifest_path = directory / "manifest.json"
        if state_summaries_path.exists() or subject_deltas_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Comparison artifacts already exist for: {comparison_id!r}.")
        if not result.state_summaries:
            raise ValueError("A physiology-trial comparison requires at least one state summary.")

        state_summary_rows = tuple(
            {
                "state_id": summary.state_id,
                "endpoint_type": summary.endpoint_type.value,
                "unit": summary.unit,
                "n": summary.n,
                "mean": summary.summary.mean,
                "sample_standard_deviation": summary.summary.sample_standard_deviation,
                "coefficient_of_variation": summary.summary.coefficient_of_variation,
                "minimum": summary.summary.minimum,
                "maximum": summary.summary.maximum,
                "p25": summary.summary.p25,
                "p50": summary.summary.p50,
                "p75": summary.summary.p75,
            }
            for summary in result.state_summaries
        )
        subject_delta_rows = tuple(
            {
                "subject_id": delta.subject_id,
                "endpoint_type": delta.endpoint_type.value,
                "unit": delta.unit,
                "baseline_state_id": delta.baseline_state_id,
                "comparison_state_id": delta.comparison_state_id,
                "baseline_value": delta.baseline_value,
                "comparison_value": delta.comparison_value,
                "absolute_difference": delta.absolute_difference,
                "relative_difference": delta.relative_difference,
            }
            for delta in result.subject_deltas
        )

        _write_table(state_summaries_path, STATE_SUMMARY_COLUMNS, state_summary_rows)
        _write_table(subject_deltas_path, SUBJECT_DELTA_COLUMNS, subject_delta_rows)

        manifest = PhysiologyComparisonArtifactManifest(
            comparison_id=comparison_id,
            source_generation_id=result.source_generation_id,
            source_population_semantic_sha256=result.source_population_semantic_sha256,
            baseline_state_id=result.baseline_state_id,
            state_physiology_population_ids=result.state_physiology_population_ids,
            state_endpoint_ids=result.state_endpoint_ids,
            state_endpoint_semantic_sha256=result.state_endpoint_semantic_sha256,
            missingness=result.missingness,
            coverage=result.coverage,
            interpretation_note=result.interpretation_note,
            state_summaries=PhysiologyComparisonTableArtifact(
                path=STATE_SUMMARIES_PATH,
                rows=len(state_summary_rows),
                columns=len(STATE_SUMMARY_COLUMNS),
                file_sha256=_file_sha256(state_summaries_path),
                semantic_content_sha256=semantic_state_summary_hash(
                    STATE_SUMMARY_COLUMNS, state_summary_rows
                ),
            ),
            subject_deltas=(
                PhysiologyComparisonTableArtifact(
                    path=SUBJECT_DELTAS_PATH,
                    rows=len(subject_delta_rows),
                    columns=len(SUBJECT_DELTA_COLUMNS),
                    file_sha256=_file_sha256(subject_deltas_path),
                    semantic_content_sha256=semantic_subject_delta_hash(
                        SUBJECT_DELTA_COLUMNS, subject_delta_rows
                    ),
                )
                if subject_delta_rows
                else _empty_table_artifact(subject_deltas_path, SUBJECT_DELTA_COLUMNS)
            ),
        )
        manifest_path.write_text(
            document(PHYSIOLOGY_COMPARISON_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, comparison_id: str) -> PhysiologyComparisonArtifactManifest:
        path = self.root / comparison_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid physiology comparison manifest: {path}") from error
        if envelope.schema_id != PHYSIOLOGY_COMPARISON_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected physiology comparison schema: {envelope.schema_id!r}.")
        return PhysiologyComparisonArtifactManifest.model_validate(envelope.payload)

    def verify_comparison(self, comparison_id: str) -> PhysiologyComparisonArtifactManifest:
        manifest = self.read_manifest(comparison_id)
        directory = self.root / comparison_id
        self._verify_table(
            directory / manifest.state_summaries.path,
            manifest.state_summaries,
            STATE_SUMMARY_COLUMNS,
            semantic_state_summary_hash,
        )
        self._verify_table(
            directory / manifest.subject_deltas.path,
            manifest.subject_deltas,
            SUBJECT_DELTA_COLUMNS,
            semantic_subject_delta_hash,
        )
        return manifest

    @staticmethod
    def _verify_table(
        path: Path,
        artifact: PhysiologyComparisonTableArtifact,
        expected_columns: Sequence[str],
        hasher: Any,
    ) -> None:
        actual_file_sha256 = _file_sha256(path)
        if actual_file_sha256 != artifact.file_sha256:
            raise ValueError(
                f"OTPHYCMP table Parquet file hash does not match its manifest: {path}."
            )
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != tuple(expected_columns)
            or table.num_rows != artifact.rows
            or table.num_columns != artifact.columns
        ):
            raise ValueError(f"OTPHYCMP table Parquet shape does not match its manifest: {path}.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if hasher(expected_columns, rows) != artifact.semantic_content_sha256:
            raise ValueError(
                f"OTPHYCMP table Parquet semantic hash does not match its manifest: {path}."
            )


def _write_table(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    text_columns = {
        "state_id",
        "subject_id",
        "endpoint_type",
        "unit",
        "baseline_state_id",
        "comparison_state_id",
    }
    int_columns = {"n"}
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


def _empty_table_artifact(path: Path, columns: Sequence[str]) -> PhysiologyComparisonTableArtifact:
    _write_table(path, columns, ())
    return PhysiologyComparisonTableArtifact(
        path=path.name,
        rows=0,
        columns=len(columns),
        file_sha256=_file_sha256(path),
        semantic_content_sha256=_semantic_table_hash(columns, ()),
    )


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
