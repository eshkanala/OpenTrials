"""Immutable Parquet execution indexes for uncertainty-study runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

UNCERTAINTY_EXECUTION_ID_PREFIX = "OTUEX-"
UNCERTAINTY_EXECUTION_ARTIFACT_SCHEMA = "opentrials.uncertainty-execution-artifact"
UNCERTAINTY_EXECUTION_PATH = "executions.parquet"
UNCERTAINTY_EXECUTION_COLUMNS = (
    "draw_id",
    "draw_index",
    "parameter_id",
    "parameter_target",
    "requested_value",
    "requested_unit",
    "executed_value",
    "executed_unit",
    "verification_status",
    "verification_evidence_sha256",
    "child_run_id",
    "child_raw_sha256",
    "result_id",
    "result_semantic_sha256",
    "endpoint_id",
    "endpoint_semantic_sha256",
    "cmax",
    "tmax",
    "auc_0_last",
)


def _semantic_value(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_uncertainty_execution_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash the logical OTUEX execution index independently of Parquet encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


class UncertaintyExecutionTableArtifact(BaseModel):
    """Integrity details for the OTUEX execution-index table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = UNCERTAINTY_EXECUTION_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class UncertaintyExecutionArtifactManifest(BaseModel):
    """Provenance and integrity record for an immutable dose uncertainty execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    execution_id: str = Field(pattern=r"^OTUEX-[A-Za-z0-9_-]+$")
    source_draw_artifact_id: str = Field(pattern=r"^OTUDR-[A-Za-z0-9_-]+$")
    source_draws_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    source_draw_table_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    target_model_sha256: str = Field(pattern=SHA256_PATTERN)
    model_id: str = Field(min_length=1)
    executions: UncertaintyExecutionTableArtifact


class UncertaintyExecutionArtifactStore:
    """Persist and reload immutable OTUEX execution indexes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_execution(self, execution_id: str) -> Path:
        if not execution_id.startswith(UNCERTAINTY_EXECUTION_ID_PREFIX):
            raise ValueError(f"Execution IDs must begin with {UNCERTAINTY_EXECUTION_ID_PREFIX!r}.")
        directory = self.root / execution_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_execution_index(
        self,
        execution_id: str,
        *,
        source_draw_artifact_id: str,
        source_draws_canonical_sha256: str,
        source_draw_table_semantic_sha256: str,
        target_model_sha256: str,
        model_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> UncertaintyExecutionArtifactManifest:
        """Write a complete OTUEX index exactly once after all children succeed."""
        directory = self.root / execution_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Execution directory does not exist: {execution_id!r}.")
        path = directory / UNCERTAINTY_EXECUTION_PATH
        manifest_path = directory / "manifest.json"
        if path.exists() or manifest_path.exists():
            raise FileExistsError(f"Execution artifacts already exist for: {execution_id!r}.")
        if not rows:
            raise ValueError("At least one successful uncertainty execution row is required.")
        normalized_rows = tuple(
            {column: row[column] for column in UNCERTAINTY_EXECUTION_COLUMNS} for row in rows
        )
        table = pa.table(
            {
                column: [row[column] for row in normalized_rows]
                for column in UNCERTAINTY_EXECUTION_COLUMNS
            }
        )
        pq.write_table(table, path, compression="zstd")
        manifest = UncertaintyExecutionArtifactManifest(
            execution_id=execution_id,
            source_draw_artifact_id=source_draw_artifact_id,
            source_draws_canonical_sha256=source_draws_canonical_sha256,
            source_draw_table_semantic_sha256=source_draw_table_semantic_sha256,
            target_model_sha256=target_model_sha256,
            model_id=model_id,
            executions=UncertaintyExecutionTableArtifact(
                rows=len(normalized_rows),
                columns=len(UNCERTAINTY_EXECUTION_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_uncertainty_execution_hash(
                    UNCERTAINTY_EXECUTION_COLUMNS, normalized_rows
                ),
            ),
        )
        manifest_path.write_text(
            document(UNCERTAINTY_EXECUTION_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, execution_id: str) -> UncertaintyExecutionArtifactManifest:
        path = self.root / execution_id / "manifest.json"
        try:
            envelope: Any = json.loads(path.read_text(encoding="utf-8"))
            value = SchemaDocument.model_validate(envelope)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid uncertainty execution manifest: {path}") from error
        if value.schema_id != UNCERTAINTY_EXECUTION_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected uncertainty execution schema: {value.schema_id!r}.")
        return UncertaintyExecutionArtifactManifest.model_validate(value.payload)

    def verify_execution(self, execution_id: str) -> UncertaintyExecutionArtifactManifest:
        """Reload and verify the OTUEX index's byte and semantic identity."""
        manifest = self.read_manifest(execution_id)
        if manifest.execution_id != execution_id:
            raise ValueError("Uncertainty execution manifest ID does not match its directory ID.")
        path = self.root / execution_id / manifest.executions.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.executions.file_sha256:
            raise ValueError("Uncertainty execution Parquet file hash does not match its manifest.")
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != UNCERTAINTY_EXECUTION_COLUMNS
            or table.num_rows != manifest.executions.rows
            or table.num_columns != manifest.executions.columns
        ):
            raise ValueError("Uncertainty execution Parquet shape does not match its manifest.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if (
            semantic_uncertainty_execution_hash(UNCERTAINTY_EXECUTION_COLUMNS, rows)
            != manifest.executions.semantic_content_sha256
        ):
            raise ValueError(
                "Uncertainty execution Parquet semantic hash does not match its manifest."
            )
        return manifest
