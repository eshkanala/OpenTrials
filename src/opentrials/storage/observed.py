"""Immutable, solver-independent storage for observed clinical evidence artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, canonical_json, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole

OBSERVED_DATASET_ID_PREFIX = "OTOBS-"
OBSERVED_ARTIFACT_SCHEMA = "opentrials.observed-evidence-artifact"
OBSERVATIONS_PATH = "observations.parquet"
OBSERVATION_COLUMNS = (
    "observation_id",
    "subject_or_population_id",
    "time_value",
    "time_unit",
    "time_scientific_value_json",
    "value",
    "value_unit",
    "value_type",
    "value_scientific_value_json",
    "analyte",
    "matrix",
    "fraction",
    "measurement",
    "assay",
    "condition",
    "evidence_ids_json",
    "observation_semantic_sha256",
)


def _semantic_value(value: object) -> object:
    """Normalize Arrow's equivalent numeric scalar representations for hashing."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_observations_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash a logical observed-measurement table independent of Parquet encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


def _observation_semantic_hash(observation: ObservedPkObservation) -> str:
    """Return the canonical identity of one complete source observation."""
    return sha256(observation)


def _full_observations_semantic_hash(observations: Sequence[ObservedPkObservation]) -> str:
    """Return the lossless semantic identity of the source observation collection."""
    return sha256(tuple(observations))


def _observation_row(observation: ObservedPkObservation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "subject_or_population_id": observation.subject_or_population_id,
        "time_value": observation.time.value,
        "time_unit": observation.time.unit,
        "time_scientific_value_json": observation.time.canonical_json(),
        "value": observation.value.value,
        "value_unit": observation.value.unit,
        "value_type": observation.value.value_type.value,
        "value_scientific_value_json": observation.value.canonical_json(),
        "analyte": observation.analyte,
        "matrix": observation.matrix,
        "fraction": observation.fraction,
        "measurement": observation.measurement,
        "assay": observation.assay,
        "condition": observation.condition,
        "evidence_ids_json": canonical_json(observation.evidence_ids),
        "observation_semantic_sha256": _observation_semantic_hash(observation),
    }


class ObservationsTableArtifact(BaseModel):
    """Integrity details for a lossless observed-measurement table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = OBSERVATIONS_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ObservedStudyArtifact(BaseModel):
    """Study identity retained alongside the flattened observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    population_description: str = Field(min_length=1)
    intervention_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    study_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    study_limitations: str | None = None
    assay_context: str | None = None


def _study_artifact(study: ObservedStudy) -> ObservedStudyArtifact:
    return ObservedStudyArtifact(
        study_id=study.study_id,
        title=study.title,
        evidence_ids=study.evidence_ids,
        population_description=study.population_description,
        intervention_canonical_sha256=sha256(study.intervention),
        study_canonical_sha256=sha256(study),
        study_limitations=study.study_limitations,
        assay_context=study.assay_context,
    )


class ObservedDatasetArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for observed clinical evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    dataset_id: str = Field(pattern=r"^OTOBS-[A-Za-z0-9_-]+$")
    role: DatasetRole
    dataset: ObservedDataset
    dataset_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    study: ObservedStudyArtifact
    license: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)
    full_observations_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    observations: ObservationsTableArtifact


class ObservedArtifactStore:
    """Persist immutable observed clinical-evidence artifacts by dataset ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_observed_dataset(self, dataset_id: str) -> Path:
        """Create the unique directory for an observed dataset artifact."""
        if not dataset_id.startswith(OBSERVED_DATASET_ID_PREFIX):
            raise ValueError(
                f"Observed dataset IDs must begin with {OBSERVED_DATASET_ID_PREFIX!r}."
            )
        directory = self.root / dataset_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_observed_dataset(
        self, dataset: ObservedDataset, *, dataset_id: str | None = None
    ) -> ObservedDatasetArtifactManifest:
        """Write one observed dataset exactly once, without solver-specific metadata."""
        artifact_id = dataset.dataset_id if dataset_id is None else dataset_id
        if artifact_id != dataset.dataset_id:
            raise ValueError("Artifact dataset ID must match ObservedDataset.dataset_id.")
        if not artifact_id.startswith(OBSERVED_DATASET_ID_PREFIX):
            raise ValueError(
                f"Observed dataset IDs must begin with {OBSERVED_DATASET_ID_PREFIX!r}."
            )
        directory = self.root / artifact_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Observed dataset directory does not exist: {artifact_id!r}.")
        parquet_path = directory / OBSERVATIONS_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Observed dataset artifacts already exist for: {artifact_id!r}.")

        rows = tuple(_observation_row(observation) for observation in dataset.observations)
        table = pa.table({column: [row[column] for row in rows] for column in OBSERVATION_COLUMNS})
        pq.write_table(table, parquet_path, compression="zstd")
        manifest = ObservedDatasetArtifactManifest(
            dataset_id=artifact_id,
            role=dataset.role,
            dataset=dataset,
            dataset_canonical_sha256=sha256(dataset),
            study=_study_artifact(dataset.study),
            license=dataset.license,
            source_identifier=dataset.source_identifier,
            provenance_ids=dataset.provenance_ids,
            full_observations_semantic_sha256=_full_observations_semantic_hash(
                dataset.observations
            ),
            observations=ObservationsTableArtifact(
                rows=len(rows),
                columns=len(OBSERVATION_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_observations_hash(OBSERVATION_COLUMNS, rows),
            ),
        )
        manifest_path.write_text(
            document(OBSERVED_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def read_manifest(self, dataset_id: str) -> ObservedDatasetArtifactManifest:
        """Load and validate a schema-enveloped observed-evidence manifest."""
        path = self.root / dataset_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid observed evidence manifest: {path}") from error
        if manifest_document.schema_id != OBSERVED_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected observed evidence manifest schema: {manifest_document.schema_id!r}."
            )
        return ObservedDatasetArtifactManifest.model_validate(manifest_document.payload)

    def verify_observed_dataset(self, dataset_id: str) -> ObservedDatasetArtifactManifest:
        """Verify manifest identity and persisted Parquet byte and semantic hashes."""
        manifest = self.read_manifest(dataset_id)
        if manifest.dataset_id != dataset_id:
            raise ValueError(
                "Observed evidence manifest dataset ID does not match its directory ID."
            )
        if sha256(manifest.dataset) != manifest.dataset_canonical_sha256:
            raise ValueError("Observed dataset canonical hash does not match its manifest.")
        if _study_artifact(manifest.dataset.study) != manifest.study:
            raise ValueError("Observed study identity does not match its manifest.")
        if (
            manifest.dataset.role != manifest.role
            or manifest.dataset.license != manifest.license
            or manifest.dataset.source_identifier != manifest.source_identifier
            or manifest.dataset.provenance_ids != manifest.provenance_ids
        ):
            raise ValueError("Observed dataset provenance or role does not match its manifest.")
        if (
            _full_observations_semantic_hash(manifest.dataset.observations)
            != manifest.full_observations_semantic_sha256
        ):
            raise ValueError("Full observed-observation hash does not match its manifest.")

        parquet_path = self.root / dataset_id / manifest.observations.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.observations.file_sha256:
            raise ValueError("Observed observations Parquet file hash does not match its manifest.")
        table = pq.read_table(parquet_path)
        columns = tuple(table.column_names)
        rows = tuple(dict(row) for row in table.to_pylist())
        if len(rows) != manifest.observations.rows or len(columns) != manifest.observations.columns:
            raise ValueError("Observed observations Parquet dimensions do not match its manifest.")
        actual_semantic_sha256 = semantic_observations_hash(columns, rows)
        if actual_semantic_sha256 != manifest.observations.semantic_content_sha256:
            raise ValueError(
                "Observed observations Parquet semantic content hash does not match its manifest."
            )
        return manifest
