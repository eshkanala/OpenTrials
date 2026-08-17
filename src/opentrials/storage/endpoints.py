"""Immutable, table-backed storage for derived PK endpoint artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.analysis.pk import PkEndpointResult
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

PK_ENDPOINT_ID_PREFIX = "OTPK-"
PK_ENDPOINT_ARTIFACT_SCHEMA = "opentrials.pk-endpoint-artifact"
PK_ENDPOINT_PATH = "endpoints.parquet"
PK_ENDPOINT_COLUMNS = (
    "subject_id",
    "endpoint_type",
    "value",
    "unit",
    "time_basis",
    "integration_method",
    "source_result_hash",
    "analyte",
    "matrix",
    "fraction",
    "measurement",
)


def _semantic_value(value: object) -> object:
    """Normalize equivalent numeric scalar types before canonical hashing."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_pk_endpoint_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash the logical endpoint table independently of Parquet byte encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


class PkEndpointTableArtifact(BaseModel):
    """Integrity details for the persisted PK endpoint table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = PK_ENDPOINT_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class PkEndpointArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for a PK endpoint artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    source_result_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_result_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_engine_id: str | None = Field(default=None, min_length=1)
    source_model_id: str | None = Field(default=None, min_length=1)
    endpoints: PkEndpointTableArtifact

    @model_validator(mode="after")
    def require_complete_optional_source_identity(self) -> PkEndpointArtifactManifest:
        """Avoid recording a partial engine/model identity when either is supplied."""
        if (self.source_engine_id is None) != (self.source_model_id is None):
            raise ValueError("Source engine and model IDs must be provided together.")
        return self


class PkEndpointArtifactStore:
    """Persist immutable PK endpoint artifacts by endpoint artifact ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_endpoint_artifact(self, endpoint_id: str) -> Path:
        """Create the unique directory for a PK endpoint artifact."""
        if not endpoint_id.startswith(PK_ENDPOINT_ID_PREFIX):
            raise ValueError(f"Endpoint artifact IDs must begin with {PK_ENDPOINT_ID_PREFIX!r}.")
        directory = self.root / endpoint_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_endpoints(
        self,
        endpoint_id: str,
        *,
        endpoints: Sequence[PkEndpointResult],
        source_result_semantic_sha256: str,
        source_result_id: str,
        run_id: str,
        source_engine_id: str | None = None,
        source_model_id: str | None = None,
    ) -> PkEndpointArtifactManifest:
        """Write a PK endpoint table and its immutable schema-enveloped manifest."""
        directory = self.root / endpoint_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Endpoint artifact directory does not exist: {endpoint_id!r}.")
        parquet_path = directory / PK_ENDPOINT_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Endpoint artifacts already exist for endpoint ID: {endpoint_id!r}."
            )
        if not endpoints:
            raise ValueError("At least one PK endpoint result is required.")
        if re.fullmatch(SHA256_PATTERN, source_result_semantic_sha256) is None:
            raise ValueError("Source result semantic hash must use the sha256:<hex> format.")
        if any(
            endpoint.source_result_hash != source_result_semantic_sha256 for endpoint in endpoints
        ):
            raise ValueError(
                "Every PK endpoint source result hash must equal the supplied normalized result "
                "semantic hash."
            )

        rows = tuple(
            {
                "subject_id": endpoint.subject_id,
                "endpoint_type": endpoint.endpoint_type.value,
                "value": endpoint.value,
                "unit": endpoint.unit,
                "time_basis": endpoint.time_basis,
                "integration_method": endpoint.integration_method,
                "source_result_hash": endpoint.source_result_hash,
                "analyte": endpoint.analyte,
                "matrix": endpoint.matrix,
                "fraction": endpoint.fraction,
                "measurement": endpoint.measurement,
            }
            for endpoint in endpoints
        )
        semantic_content_sha256 = semantic_pk_endpoint_hash(PK_ENDPOINT_COLUMNS, rows)
        table = pa.table({column: [row[column] for row in rows] for column in PK_ENDPOINT_COLUMNS})
        pq.write_table(table, parquet_path, compression="zstd")
        manifest = PkEndpointArtifactManifest(
            endpoint_id=endpoint_id,
            source_result_semantic_sha256=source_result_semantic_sha256,
            source_result_id=source_result_id,
            run_id=run_id,
            source_engine_id=source_engine_id,
            source_model_id=source_model_id,
            endpoints=PkEndpointTableArtifact(
                rows=len(rows),
                columns=len(PK_ENDPOINT_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_content_sha256,
            ),
        )
        manifest_path.write_text(
            document(PK_ENDPOINT_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, endpoint_id: str) -> PkEndpointArtifactManifest:
        """Load and validate a schema-enveloped endpoint artifact manifest."""
        path = self.root / endpoint_id / "manifest.json"
        try:
            manifest_document = SchemaDocument.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid PK endpoint manifest: {path}") from error
        if manifest_document.schema_id != PK_ENDPOINT_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected PK endpoint manifest schema: {manifest_document.schema_id!r}."
            )
        return PkEndpointArtifactManifest.model_validate(manifest_document.payload)

    def verify_endpoints(self, endpoint_id: str) -> PkEndpointArtifactManifest:
        """Verify persisted endpoint Parquet bytes and its logical table identity."""
        manifest = self.read_manifest(endpoint_id)
        parquet_path = self.root / endpoint_id / manifest.endpoints.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.endpoints.file_sha256:
            raise ValueError("PK endpoint Parquet file hash does not match its manifest.")
        table = pq.read_table(parquet_path)
        columns = tuple(table.column_names)
        rows = tuple(dict(row) for row in table.to_pylist())
        if len(rows) != manifest.endpoints.rows or len(columns) != manifest.endpoints.columns:
            raise ValueError("PK endpoint Parquet dimensions do not match its manifest.")
        actual_semantic_sha256 = semantic_pk_endpoint_hash(columns, rows)
        if actual_semantic_sha256 != manifest.endpoints.semantic_content_sha256:
            raise ValueError(
                "PK endpoint Parquet semantic content hash does not match its manifest."
            )
        return manifest
