"""Immutable Parquet artifacts for prospective multi-arm trial PK comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.arm_comparison import TrialArmComparisonResult
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

ARM_COMPARISON_ID_PREFIX = "OTACMP-"
ARM_COMPARISON_ARTIFACT_SCHEMA = "opentrials.trial-arm-comparison-artifact"
ARM_SUMMARIES_PATH = "arm_summaries.parquet"
PAIRWISE_COMPARISONS_PATH = "pairwise_comparisons.parquet"

ARM_SUMMARY_COLUMNS = (
    "arm_id",
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
PAIRWISE_COMPARISON_COLUMNS = (
    "arm_a_id",
    "arm_b_id",
    "endpoint_type",
    "unit",
    "arm_a_mean",
    "arm_b_mean",
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


def semantic_arm_summary_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


def semantic_pairwise_comparison_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    return _semantic_table_hash(column_names, rows)


class ArmComparisonTableArtifact(BaseModel):
    """Integrity details for one persisted OTACMP table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rows: int = Field(ge=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ArmComparisonArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one OTACMP artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    comparison_id: str = Field(pattern=r"^OTACMP-[A-Za-z0-9_-]+$")
    allocation_id: str = Field(pattern=r"^OTALLOC-[A-Za-z0-9_-]+$")
    allocation_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    arm_endpoint_ids: dict[str, str]
    arm_endpoint_semantic_sha256: dict[str, str]
    interpretation_note: str = Field(min_length=1)
    arm_summaries: ArmComparisonTableArtifact
    pairwise_comparisons: ArmComparisonTableArtifact


class ArmComparisonArtifactStore:
    """Persist and reload immutable OTACMP multi-arm PK comparison artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_comparison(self, comparison_id: str) -> Path:
        if not comparison_id.startswith(ARM_COMPARISON_ID_PREFIX):
            raise ValueError(f"Comparison IDs must begin with {ARM_COMPARISON_ID_PREFIX!r}.")
        directory = self.root / comparison_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_comparison(
        self, comparison_id: str, result: TrialArmComparisonResult
    ) -> ArmComparisonArtifactManifest:
        """Persist an already-computed, already-verified comparison exactly once."""
        directory = self.root / comparison_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Comparison directory does not exist: {comparison_id!r}.")
        arm_summaries_path = directory / ARM_SUMMARIES_PATH
        pairwise_path = directory / PAIRWISE_COMPARISONS_PATH
        manifest_path = directory / "manifest.json"
        if arm_summaries_path.exists() or pairwise_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Comparison artifacts already exist for: {comparison_id!r}.")
        if not result.arm_summaries:
            raise ValueError("A trial-arm comparison requires at least one arm summary.")

        arm_summary_rows = tuple(
            {
                "arm_id": summary.arm_id,
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
            for summary in result.arm_summaries
        )
        pairwise_rows = tuple(
            {
                "arm_a_id": comparison.arm_a_id,
                "arm_b_id": comparison.arm_b_id,
                "endpoint_type": comparison.endpoint_type.value,
                "unit": comparison.unit,
                "arm_a_mean": comparison.arm_a_mean,
                "arm_b_mean": comparison.arm_b_mean,
                "absolute_difference": comparison.absolute_difference,
                "relative_difference": comparison.relative_difference,
            }
            for comparison in result.pairwise_comparisons
        )

        _write_table(arm_summaries_path, ARM_SUMMARY_COLUMNS, arm_summary_rows)
        _write_table(pairwise_path, PAIRWISE_COMPARISON_COLUMNS, pairwise_rows)

        manifest = ArmComparisonArtifactManifest(
            comparison_id=comparison_id,
            allocation_id=result.allocation_id,
            allocation_semantic_sha256=result.allocation_semantic_sha256,
            source_generation_id=result.source_generation_id,
            source_population_semantic_sha256=result.source_population_semantic_sha256,
            arm_endpoint_ids=result.arm_endpoint_ids,
            arm_endpoint_semantic_sha256=result.arm_endpoint_semantic_sha256,
            interpretation_note=result.interpretation_note,
            arm_summaries=ArmComparisonTableArtifact(
                path=ARM_SUMMARIES_PATH,
                rows=len(arm_summary_rows),
                columns=len(ARM_SUMMARY_COLUMNS),
                file_sha256=_file_sha256(arm_summaries_path),
                semantic_content_sha256=semantic_arm_summary_hash(
                    ARM_SUMMARY_COLUMNS, arm_summary_rows
                ),
            ),
            pairwise_comparisons=ArmComparisonTableArtifact(
                path=PAIRWISE_COMPARISONS_PATH,
                rows=len(pairwise_rows) if pairwise_rows else 0,
                columns=len(PAIRWISE_COMPARISON_COLUMNS),
                file_sha256=_file_sha256(pairwise_path),
                semantic_content_sha256=semantic_pairwise_comparison_hash(
                    PAIRWISE_COMPARISON_COLUMNS, pairwise_rows
                ),
            )
            if pairwise_rows
            else _empty_table_artifact(pairwise_path, PAIRWISE_COMPARISON_COLUMNS),
        )
        manifest_path.write_text(
            document(ARM_COMPARISON_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, comparison_id: str) -> ArmComparisonArtifactManifest:
        path = self.root / comparison_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid arm comparison manifest: {path}") from error
        if envelope.schema_id != ARM_COMPARISON_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected arm comparison schema: {envelope.schema_id!r}.")
        return ArmComparisonArtifactManifest.model_validate(envelope.payload)

    def verify_comparison(self, comparison_id: str) -> ArmComparisonArtifactManifest:
        manifest = self.read_manifest(comparison_id)
        directory = self.root / comparison_id
        self._verify_table(
            directory / manifest.arm_summaries.path,
            manifest.arm_summaries,
            ARM_SUMMARY_COLUMNS,
            semantic_arm_summary_hash,
        )
        self._verify_table(
            directory / manifest.pairwise_comparisons.path,
            manifest.pairwise_comparisons,
            PAIRWISE_COMPARISON_COLUMNS,
            semantic_pairwise_comparison_hash,
        )
        return manifest

    @staticmethod
    def _verify_table(
        path: Path,
        artifact: ArmComparisonTableArtifact,
        expected_columns: Sequence[str],
        hasher: Any,
    ) -> None:
        actual_file_sha256 = _file_sha256(path)
        if actual_file_sha256 != artifact.file_sha256:
            raise ValueError(f"OTACMP table Parquet file hash does not match its manifest: {path}.")
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != tuple(expected_columns)
            or table.num_rows != artifact.rows
            or table.num_columns != artifact.columns
        ):
            raise ValueError(f"OTACMP table Parquet shape does not match its manifest: {path}.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if hasher(expected_columns, rows) != artifact.semantic_content_sha256:
            raise ValueError(
                f"OTACMP table Parquet semantic hash does not match its manifest: {path}."
            )


def _write_table(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    text_columns = {"arm_id", "arm_a_id", "arm_b_id", "endpoint_type", "unit"}
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


def _empty_table_artifact(path: Path, columns: Sequence[str]) -> ArmComparisonTableArtifact:
    _write_table(path, columns, ())
    return ArmComparisonTableArtifact(
        path=path.name,
        rows=0,
        columns=len(columns),
        file_sha256=_file_sha256(path),
        semantic_content_sha256=_semantic_table_hash(columns, ()),
    )


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
