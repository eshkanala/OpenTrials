"""Immutable, table-backed virtual-population artifact storage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN

POPULATION_GENERATION_ID_PATTERN = r"^OTPGEN-[A-Za-z0-9_-]+$"
POPULATION_ARTIFACT_SCHEMA = "opentrials.population-artifact"


def _normalize_semantic_value(value: object) -> object:
    """Make logical scalar identity stable across Arrow numeric representations."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_population_content_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash a logical population table independent of Parquet byte encoding."""
    normalized_columns = tuple(column_names)
    return sha256(
        {
            "columns": normalized_columns,
            "rows": [
                {column: _normalize_semantic_value(row[column]) for column in normalized_columns}
                for row in rows
            ],
        }
    )


class PopulationGeneratorProvenance(BaseModel):
    """Engine and software versions that produced a population table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_id: str = Field(min_length=1)
    population_model: str = Field(min_length=1)
    software_versions: dict[str, str] = Field(min_length=1)


class PopulationGenerationProvenance(BaseModel):
    """Requested and executed stochastic-generation controls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_seed: int
    engine_seed: int | None = None
    determinism_level: str = Field(min_length=1)


class PopulationTableArtifact(BaseModel):
    """Integrity information for a lossless generated-population table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = "individuals.parquet"
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)
    source_schema: str = Field(min_length=1)
    normalization: str = "NONE"


class PopulationArtifactManifest(BaseModel):
    """Versioned identity and provenance record for one generated population."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    generation_id: str = Field(pattern=POPULATION_GENERATION_ID_PATTERN)
    population_id: str = Field(min_length=1)
    source_request: SchemaDocument
    source_request_sha256: str = Field(pattern=SHA256_PATTERN)
    generator: PopulationGeneratorProvenance
    generation: PopulationGenerationProvenance
    requested_count: int = Field(gt=0)
    actual_count: int = Field(gt=0)
    individuals: PopulationTableArtifact
    generated_physiology_provenance: tuple[str, ...] = ()


class PopulationArtifactStore:
    """Persist immutable raw population tables with file and logical identities."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_generation(self, generation_id: str) -> Path:
        """Create a unique directory for one generation event."""
        if not generation_id.startswith("OTPGEN-"):
            raise ValueError("Population generation IDs must begin with 'OTPGEN-'.")
        directory = self.root / generation_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_population(
        self,
        generation_id: str,
        *,
        population_id: str,
        source_request: SchemaDocument,
        generator: PopulationGeneratorProvenance,
        generation: PopulationGenerationProvenance,
        requested_count: int,
        column_names: Sequence[str],
        rows: Sequence[Mapping[str, object]],
        generated_physiology_provenance: Sequence[str] = (),
    ) -> PopulationArtifactManifest:
        """Write one raw table and immutable manifest for a population generation event."""
        directory = self.root / generation_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Population generation directory does not exist: {generation_id!r}."
            )
        parquet_path = directory / "individuals.parquet"
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Population artifacts already exist for generation: {generation_id!r}."
            )
        normalized_columns = tuple(column_names)
        if not normalized_columns or any(not column.strip() for column in normalized_columns):
            raise ValueError("Population table columns must be non-empty strings.")
        if len(normalized_columns) != len(set(normalized_columns)):
            raise ValueError("Population table columns must be unique.")
        if len(rows) != requested_count:
            raise ValueError("Population table row count must equal the requested count.")
        expected_columns = set(normalized_columns)
        if any(set(row) != expected_columns for row in rows):
            raise ValueError("Every population row must contain exactly the declared columns.")

        semantic_content_sha256 = semantic_population_content_hash(normalized_columns, rows)
        table = pa.table({column: [row[column] for row in rows] for column in normalized_columns})
        pq.write_table(table, parquet_path, compression="zstd")
        file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        manifest = PopulationArtifactManifest(
            generation_id=generation_id,
            population_id=population_id,
            source_request=source_request,
            source_request_sha256=source_request.sha256(),
            generator=generator,
            generation=generation,
            requested_count=requested_count,
            actual_count=len(rows),
            individuals=PopulationTableArtifact(
                rows=len(rows),
                columns=len(normalized_columns),
                file_sha256=file_sha256,
                semantic_content_sha256=semantic_content_sha256,
                source_schema="osp.populationToDataFrame",
            ),
            generated_physiology_provenance=tuple(generated_physiology_provenance),
        )
        manifest_document = document(POPULATION_ARTIFACT_SCHEMA, manifest)
        manifest_path.write_text(manifest_document.canonical_json() + "\n", encoding="utf-8")
        return manifest

    def read_manifest(self, generation_id: str) -> PopulationArtifactManifest:
        """Load and validate the versioned manifest for one population artifact."""
        path = self.root / generation_id / "manifest.json"
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid population manifest: {path}") from error
        if manifest_document.schema_id != POPULATION_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected population manifest schema: {manifest_document.schema_id!r}."
            )
        return PopulationArtifactManifest.model_validate(manifest_document.payload)

    def verify_population(self, generation_id: str) -> PopulationArtifactManifest:
        """Verify file and semantic hashes by reloading the persisted Parquet table."""
        manifest = self.read_manifest(generation_id)
        directory = self.root / generation_id
        parquet_path = directory / manifest.individuals.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.individuals.file_sha256:
            raise ValueError("Population Parquet file hash does not match its manifest.")
        table = pq.read_table(parquet_path)
        columns = tuple(table.column_names)
        rows = tuple(dict(row) for row in table.to_pylist())
        actual_semantic_sha256 = semantic_population_content_hash(columns, rows)
        if actual_semantic_sha256 != manifest.individuals.semantic_content_sha256:
            raise ValueError(
                "Population Parquet semantic content hash does not match its manifest."
            )
        return manifest
