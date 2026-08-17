"""Immutable Parquet artifacts for verified two-group cohort PK comparisons."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.analysis.cohort_comparison import CohortPkComparisonResult, OverlapReport
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

COHORT_PK_COMPARISON_ID_PREFIX = "OTCPK-"
COHORT_PK_COMPARISON_ARTIFACT_SCHEMA = "opentrials.cohort-pk-comparison-artifact"
GROUP_SUMMARIES_PATH = "group_summaries.parquet"
COMPARISONS_PATH = "comparisons.parquet"

GROUP_SUMMARY_COLUMNS = (
    "group_label",
    "membership_id",
    "endpoint_type",
    "unit",
    "n_members",
    "n_matched",
    "n_missing",
    "coverage",
    "mean",
    "sample_standard_deviation",
    "coefficient_of_variation",
    "minimum",
    "maximum",
    "p25",
    "p50",
    "p75",
)
COMPARISON_COLUMNS = (
    "endpoint_type",
    "unit",
    "group_a_mean",
    "group_b_mean",
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


def semantic_group_summary_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash the logical group-summary table independently of Parquet encoding."""
    return _semantic_table_hash(column_names, rows)


def semantic_comparison_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash the logical comparison table independently of Parquet encoding."""
    return _semantic_table_hash(column_names, rows)


class CohortPkTableArtifact(BaseModel):
    """Integrity details for one persisted OTCPK table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class CohortPkComparisonArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one OTCPK comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    comparison_id: str = Field(pattern=r"^OTCPK-[A-Za-z0-9_-]+$")
    group_a_membership_id: str = Field(min_length=1)
    group_b_membership_id: str = Field(min_length=1)
    group_a_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    group_b_membership_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    group_a_label: str = Field(min_length=1)
    group_b_label: str = Field(min_length=1)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    source_endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    overlap: OverlapReport
    group_summaries: CohortPkTableArtifact
    comparisons: CohortPkTableArtifact


class CohortPkComparisonArtifactStore:
    """Persist and reload immutable OTCPK comparison artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_comparison(self, comparison_id: str) -> Path:
        if not comparison_id.startswith(COHORT_PK_COMPARISON_ID_PREFIX):
            raise ValueError(
                f"Comparison IDs must begin with {COHORT_PK_COMPARISON_ID_PREFIX!r}."
            )
        directory = self.root / comparison_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_comparison(
        self, comparison_id: str, result: CohortPkComparisonResult
    ) -> CohortPkComparisonArtifactManifest:
        """Persist a fully computed, already-verified comparison result exactly once.

        This layer performs no join, statistics, or verification of its own; that
        is ``compare_cohort_pk_endpoints``'s responsibility. It only serializes an
        already-strict result immutably.
        """
        directory = self.root / comparison_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Comparison directory does not exist: {comparison_id!r}.")
        summaries_path = directory / GROUP_SUMMARIES_PATH
        comparisons_path = directory / COMPARISONS_PATH
        manifest_path = directory / "manifest.json"
        if summaries_path.exists() or comparisons_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Comparison artifacts already exist for: {comparison_id!r}.")

        summary_rows = tuple(
            {
                "group_label": summary.group_label,
                "membership_id": summary.membership_id,
                "endpoint_type": summary.endpoint_type.value,
                "unit": summary.unit,
                "n_members": summary.n_members,
                "n_matched": summary.n_matched,
                "n_missing": summary.n_missing,
                "coverage": summary.coverage,
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
            for summary in result.group_summaries
        )
        comparison_rows = tuple(
            {
                "endpoint_type": comparison.endpoint_type.value,
                "unit": comparison.unit,
                "group_a_mean": comparison.group_a_mean,
                "group_b_mean": comparison.group_b_mean,
                "absolute_difference": comparison.absolute_difference,
                "relative_difference": comparison.relative_difference,
            }
            for comparison in result.comparisons
        )
        if not summary_rows or not comparison_rows:
            raise ValueError("A comparison requires at least one group summary and comparison row.")

        _write_table(summaries_path, GROUP_SUMMARY_COLUMNS, summary_rows)
        _write_table(comparisons_path, COMPARISON_COLUMNS, comparison_rows)

        manifest = CohortPkComparisonArtifactManifest(
            comparison_id=comparison_id,
            group_a_membership_id=result.group_a_membership_id,
            group_b_membership_id=result.group_b_membership_id,
            group_a_membership_semantic_sha256=result.group_a_membership_semantic_sha256,
            group_b_membership_semantic_sha256=result.group_b_membership_semantic_sha256,
            group_a_label=result.group_a_label,
            group_b_label=result.group_b_label,
            source_generation_id=result.source_generation_id,
            source_population_semantic_sha256=result.source_population_semantic_sha256,
            source_endpoint_id=result.source_endpoint_id,
            source_endpoint_semantic_sha256=result.source_endpoint_semantic_sha256,
            overlap=result.overlap,
            group_summaries=CohortPkTableArtifact(
                path=GROUP_SUMMARIES_PATH,
                rows=len(summary_rows),
                columns=len(GROUP_SUMMARY_COLUMNS),
                file_sha256=_file_sha256(summaries_path),
                semantic_content_sha256=semantic_group_summary_hash(
                    GROUP_SUMMARY_COLUMNS, summary_rows
                ),
            ),
            comparisons=CohortPkTableArtifact(
                path=COMPARISONS_PATH,
                rows=len(comparison_rows),
                columns=len(COMPARISON_COLUMNS),
                file_sha256=_file_sha256(comparisons_path),
                semantic_content_sha256=semantic_comparison_hash(
                    COMPARISON_COLUMNS, comparison_rows
                ),
            ),
        )
        manifest_path.write_text(
            document(COHORT_PK_COMPARISON_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, comparison_id: str) -> CohortPkComparisonArtifactManifest:
        path = self.root / comparison_id / "manifest.json"
        try:
            envelope: Any = json.loads(path.read_text(encoding="utf-8"))
            value = SchemaDocument.model_validate(envelope)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid cohort PK comparison manifest: {path}") from error
        if value.schema_id != COHORT_PK_COMPARISON_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected cohort PK comparison schema: {value.schema_id!r}.")
        return CohortPkComparisonArtifactManifest.model_validate(value.payload)

    def verify_comparison(self, comparison_id: str) -> CohortPkComparisonArtifactManifest:
        """Reload and verify OTCPK byte and semantic identity for both tables."""
        manifest = self.read_manifest(comparison_id)
        if manifest.comparison_id != comparison_id:
            raise ValueError("Comparison manifest ID does not match its directory ID.")
        directory = self.root / comparison_id
        self._verify_table(
            directory / manifest.group_summaries.path,
            manifest.group_summaries,
            GROUP_SUMMARY_COLUMNS,
            semantic_group_summary_hash,
        )
        self._verify_table(
            directory / manifest.comparisons.path,
            manifest.comparisons,
            COMPARISON_COLUMNS,
            semantic_comparison_hash,
        )
        return manifest

    @staticmethod
    def _verify_table(
        path: Path,
        artifact: CohortPkTableArtifact,
        expected_columns: Sequence[str],
        hasher: Any,
    ) -> None:
        actual_file_sha256 = _file_sha256(path)
        if actual_file_sha256 != artifact.file_sha256:
            raise ValueError(f"OTCPK table Parquet file hash does not match its manifest: {path}.")
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != tuple(expected_columns)
            or table.num_rows != artifact.rows
            or table.num_columns != artifact.columns
        ):
            raise ValueError(f"OTCPK table Parquet shape does not match its manifest: {path}.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if hasher(expected_columns, rows) != artifact.semantic_content_sha256:
            raise ValueError(
                f"OTCPK table Parquet semantic hash does not match its manifest: {path}."
            )


def _write_table(
    path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> None:
    table = pa.table({column: [row[column] for row in rows] for column in columns})
    pq.write_table(table, path, compression="zstd")


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
