"""Immutable Parquet artifacts for sensitivity analyses of verified OTUEX executions."""

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

UNCERTAINTY_SENSITIVITY_ID_PREFIX = "OTSENS-"
UNCERTAINTY_SENSITIVITY_ARTIFACT_SCHEMA = "opentrials.uncertainty-sensitivity-artifact"
UNCERTAINTY_SENSITIVITY_PATH = "sensitivities.parquet"
UNCERTAINTY_SENSITIVITY_COLUMNS = (
    "rank",
    "input_id",
    "input_target",
    "input_unit",
    "output_id",
    "correlation",
    "absolute_correlation",
)
ENGINEERING_DEMONSTRATION_INTERPRETATION = (
    "Engineering demonstration only: intervention dose is a verified perturbation variable, "
    "not genuine biological or parameter uncertainty."
)


def _semantic_value(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_uncertainty_sensitivity_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash logical OTSENS results independently of Parquet encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


class UncertaintySensitivityTableArtifact(BaseModel):
    """Integrity details for the OTSENS result table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = UNCERTAINTY_SENSITIVITY_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class UncertaintySensitivityArtifactManifest(BaseModel):
    """Provenance and integrity record for a sensitivity analysis of one OTUEX."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    sensitivity_id: str = Field(pattern=r"^OTSENS-[A-Za-z0-9_-]+$")
    source_execution_id: str = Field(pattern=r"^OTUEX-[A-Za-z0-9_-]+$")
    source_execution_manifest_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    source_execution_file_sha256: str = Field(pattern=SHA256_PATTERN)
    source_execution_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_draw_artifact_id: str = Field(pattern=r"^OTUDR-[A-Za-z0-9_-]+$")
    source_draws_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    source_draw_table_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    target_model_sha256: str = Field(pattern=SHA256_PATTERN)
    model_id: str = Field(min_length=1)
    interpretation: str = ENGINEERING_DEMONSTRATION_INTERPRETATION
    sensitivities: UncertaintySensitivityTableArtifact


class UncertaintySensitivityArtifactStore:
    """Persist and reload immutable OTSENS artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_sensitivity(self, sensitivity_id: str) -> Path:
        if not sensitivity_id.startswith(UNCERTAINTY_SENSITIVITY_ID_PREFIX):
            raise ValueError(
                f"Sensitivity IDs must begin with {UNCERTAINTY_SENSITIVITY_ID_PREFIX!r}."
            )
        directory = self.root / sensitivity_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_sensitivities(
        self,
        sensitivity_id: str,
        *,
        source_execution_id: str,
        source_execution_manifest_canonical_sha256: str,
        source_execution_file_sha256: str,
        source_execution_semantic_sha256: str,
        source_draw_artifact_id: str,
        source_draws_canonical_sha256: str,
        source_draw_table_semantic_sha256: str,
        target_model_sha256: str,
        model_id: str,
        rows: Sequence[Mapping[str, object]],
    ) -> UncertaintySensitivityArtifactManifest:
        """Write complete, precomputed OTSENS results exactly once.

        Analysis orchestration, not this persistence layer, is responsible for
        deriving rows exclusively from a verified OTUEX artifact.
        """
        directory = self.root / sensitivity_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Sensitivity directory does not exist: {sensitivity_id!r}.")
        path = directory / UNCERTAINTY_SENSITIVITY_PATH
        manifest_path = directory / "manifest.json"
        if path.exists() or manifest_path.exists():
            raise FileExistsError(f"Sensitivity artifacts already exist for: {sensitivity_id!r}.")
        if not rows:
            raise ValueError("At least one sensitivity result row is required.")
        normalized_rows = tuple(
            {column: row[column] for column in UNCERTAINTY_SENSITIVITY_COLUMNS} for row in rows
        )
        pq.write_table(
            pa.table(
                {
                    column: [row[column] for row in normalized_rows]
                    for column in UNCERTAINTY_SENSITIVITY_COLUMNS
                }
            ),
            path,
            compression="zstd",
        )
        manifest = UncertaintySensitivityArtifactManifest(
            sensitivity_id=sensitivity_id,
            source_execution_id=source_execution_id,
            source_execution_manifest_canonical_sha256=source_execution_manifest_canonical_sha256,
            source_execution_file_sha256=source_execution_file_sha256,
            source_execution_semantic_sha256=source_execution_semantic_sha256,
            source_draw_artifact_id=source_draw_artifact_id,
            source_draws_canonical_sha256=source_draws_canonical_sha256,
            source_draw_table_semantic_sha256=source_draw_table_semantic_sha256,
            target_model_sha256=target_model_sha256,
            model_id=model_id,
            sensitivities=UncertaintySensitivityTableArtifact(
                rows=len(normalized_rows),
                columns=len(UNCERTAINTY_SENSITIVITY_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_uncertainty_sensitivity_hash(
                    UNCERTAINTY_SENSITIVITY_COLUMNS, normalized_rows
                ),
            ),
        )
        manifest_path.write_text(
            document(UNCERTAINTY_SENSITIVITY_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, sensitivity_id: str) -> UncertaintySensitivityArtifactManifest:
        path = self.root / sensitivity_id / "manifest.json"
        try:
            envelope: Any = json.loads(path.read_text(encoding="utf-8"))
            value = SchemaDocument.model_validate(envelope)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid uncertainty sensitivity manifest: {path}") from error
        if value.schema_id != UNCERTAINTY_SENSITIVITY_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected uncertainty sensitivity schema: {value.schema_id!r}.")
        return UncertaintySensitivityArtifactManifest.model_validate(value.payload)

    def verify_sensitivity(self, sensitivity_id: str) -> UncertaintySensitivityArtifactManifest:
        """Reload and verify OTSENS byte and semantic identity."""
        manifest = self.read_manifest(sensitivity_id)
        if manifest.sensitivity_id != sensitivity_id:
            raise ValueError("Uncertainty sensitivity manifest ID does not match its directory ID.")
        path = self.root / sensitivity_id / manifest.sensitivities.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.sensitivities.file_sha256:
            raise ValueError(
                "Uncertainty sensitivity Parquet file hash does not match its manifest."
            )
        table = pq.read_table(path)
        if (
            tuple(table.column_names) != UNCERTAINTY_SENSITIVITY_COLUMNS
            or table.num_rows != manifest.sensitivities.rows
            or table.num_columns != manifest.sensitivities.columns
        ):
            raise ValueError("Uncertainty sensitivity Parquet shape does not match its manifest.")
        rows = tuple(dict(row) for row in table.to_pylist())
        if (
            semantic_uncertainty_sensitivity_hash(UNCERTAINTY_SENSITIVITY_COLUMNS, rows)
            != manifest.sensitivities.semantic_content_sha256
        ):
            raise ValueError(
                "Uncertainty sensitivity Parquet semantic hash does not match its manifest."
            )
        return manifest
