"""Immutable Parquet artifacts for deterministic trial-arm population allocation."""

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
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.row_identity import source_row_sha256
from opentrials.trials.allocation import ArmAllocationResult, allocate_population_to_arms
from opentrials.trials.trial import Trial

ALLOCATION_ID_PATTERN = r"^OTALLOC-[A-Za-z0-9_-]+$"
ALLOCATION_ARTIFACT_SCHEMA = "opentrials.trial-arm-allocation-artifact"
ALLOCATION_MEMBERS_PATH = "allocation.parquet"
ALLOCATION_COLUMNS = ("source_subject_id", "source_row_index", "source_row_sha256", "arm_id")


def semantic_allocation_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash the logical allocation table independently of Parquet encoding."""
    columns = tuple(column_names)
    return sha256(
        {"columns": columns, "rows": [{column: row[column] for column in columns} for row in rows]}
    )


class AllocationTableArtifact(BaseModel):
    """Integrity details for the persisted allocation table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = ALLOCATION_MEMBERS_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class TrialArmAllocationArtifactManifest(BaseModel):
    """Versioned provenance and integrity record for one trial-arm allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    allocation_id: str = Field(pattern=ALLOCATION_ID_PATTERN)
    trial_id: str = Field(min_length=1)
    trial_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    requested_seed: int
    apportionment_method: str = Field(min_length=1)
    arm_counts: dict[str, int]
    total_population: int = Field(gt=0)
    allocation: AllocationTableArtifact


class TrialArmAllocationArtifactStore:
    """Verify the source OTPGEN population, allocate deterministically, persist once."""

    def __init__(self, root: Path, *, population_store: PopulationArtifactStore) -> None:
        self.root = root
        self.population_store = population_store

    def create_allocation(self, allocation_id: str) -> Path:
        if not allocation_id.startswith("OTALLOC-"):
            raise ValueError("Allocation IDs must begin with 'OTALLOC-'.")
        directory = self.root / allocation_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_allocation(
        self, allocation_id: str, *, trial: Trial, generation_id: str
    ) -> TrialArmAllocationArtifactManifest:
        """Verify the population, allocate deterministically, and persist exactly once."""
        directory = self.root / allocation_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Allocation directory does not exist: {allocation_id!r}.")
        parquet_path = directory / ALLOCATION_MEMBERS_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Allocation artifacts already exist for: {allocation_id!r}."
            )

        population_manifest = self.population_store.verify_population(generation_id)
        population_table = pq.read_table(
            self.population_store.root / generation_id / population_manifest.individuals.path
        )
        population_columns = tuple(population_table.column_names)
        population_rows = tuple(dict(row) for row in population_table.to_pylist())
        if "IndividualId" not in population_columns:
            raise ValueError("Population table has no IndividualId column to allocate by.")

        result = allocate_population_to_arms(
            trial, population_columns, population_rows, "IndividualId"
        )
        _verify_allocation_row_hashes(result, population_columns, population_rows)

        rows = tuple(
            {
                "source_subject_id": entry.subject_id,
                "source_row_index": entry.source_row_index,
                "source_row_sha256": entry.source_row_sha256,
                "arm_id": entry.arm_id,
            }
            for entry in result.entries
        )
        table = pa.table({column: [row[column] for row in rows] for column in ALLOCATION_COLUMNS})
        pq.write_table(table, parquet_path, compression="zstd")
        semantic_content_sha256 = semantic_allocation_hash(ALLOCATION_COLUMNS, rows)

        manifest = TrialArmAllocationArtifactManifest(
            allocation_id=allocation_id,
            trial_id=trial.trial_id,
            trial_sha256=sha256(trial),
            source_generation_id=generation_id,
            source_population_semantic_sha256=population_manifest.individuals.semantic_content_sha256,
            requested_seed=result.requested_seed,
            apportionment_method=result.apportionment_method,
            arm_counts=result.arm_counts,
            total_population=result.total_population,
            allocation=AllocationTableArtifact(
                rows=len(rows),
                columns=len(ALLOCATION_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_content_sha256,
            ),
        )
        manifest_path.write_text(
            document(ALLOCATION_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def read_manifest(self, allocation_id: str) -> TrialArmAllocationArtifactManifest:
        path = self.root / allocation_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid trial-arm allocation manifest: {path}") from error
        if envelope.schema_id != ALLOCATION_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected trial-arm allocation schema: {envelope.schema_id!r}.")
        return TrialArmAllocationArtifactManifest.model_validate(envelope.payload)

    def verify_allocation(self, allocation_id: str) -> TrialArmAllocationArtifactManifest:
        manifest = self.read_manifest(allocation_id)
        parquet_path = self.root / allocation_id / manifest.allocation.path
        actual_file_hash = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_hash != manifest.allocation.file_sha256:
            raise ValueError("Allocation Parquet file hash does not match its manifest.")
        rows = self._read_rows(allocation_id)
        actual_semantic_hash = semantic_allocation_hash(ALLOCATION_COLUMNS, rows)
        if actual_semantic_hash != manifest.allocation.semantic_content_sha256:
            raise ValueError("Allocation Parquet semantic hash does not match its manifest.")
        population_manifest = self.population_store.verify_population(
            manifest.source_generation_id
        )
        if (
            population_manifest.individuals.semantic_content_sha256
            != manifest.source_population_semantic_sha256
        ):
            raise ValueError("Allocation source population hash does not match its manifest.")
        population_table = pq.read_table(
            self.population_store.root
            / manifest.source_generation_id
            / population_manifest.individuals.path
        )
        population_columns = tuple(population_table.column_names)
        population_rows = tuple(dict(row) for row in population_table.to_pylist())
        for row in rows:
            index = row["source_row_index"]
            assert isinstance(index, int)
            if not 0 <= index < len(population_rows):
                raise ValueError("Allocation references a row outside the verified population.")
            actual_row_hash = source_row_sha256(population_columns, population_rows[index])
            if actual_row_hash != row["source_row_sha256"]:
                raise ValueError("Allocation row hash does not match the verified population row.")
        return manifest

    def read_rows_for_arm(self, allocation_id: str, arm_id: str) -> tuple[dict[str, object], ...]:
        """Return the verified rows assigned to exactly one arm."""
        self.verify_allocation(allocation_id)
        return tuple(row for row in self._read_rows(allocation_id) if row["arm_id"] == arm_id)

    def _read_rows(self, allocation_id: str) -> tuple[dict[str, object], ...]:
        table = pq.read_table(self.root / allocation_id / ALLOCATION_MEMBERS_PATH)
        if tuple(table.column_names) != ALLOCATION_COLUMNS:
            raise ValueError("Allocation Parquet columns do not match the contract.")
        return tuple(dict(row) for row in table.to_pylist())


def _verify_allocation_row_hashes(
    result: ArmAllocationResult,
    population_columns: Sequence[str],
    population_rows: Sequence[Mapping[str, object]],
) -> None:
    """Defensive check: the pure allocator must compute genuine row hashes."""
    for entry in result.entries:
        expected = source_row_sha256(population_columns, population_rows[entry.source_row_index])
        if expected != entry.source_row_sha256:
            # Defensive: allocate_population_to_arms already computes this hash itself.
            raise ValueError(
                "Allocation entry row hash does not match its own source population row."
            )
