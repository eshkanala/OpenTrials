"""Immutable, table-backed storage for physiological-state-overridden populations.

An ``OTPHYS`` artifact never overwrites its source ``OTPGEN`` population --
it records a full copy of the source table with exactly one column scaled
by a verified ``PhysiologicalStateOverride``, in the same row order as the
source table. Preserving row order (rather than, say, re-sorting by the
changed value) is what lets a later execution resolve endpoint lineage
against the *original* population's row index/hash, so the same individual
carries identical lineage across every physiology state built from one
OTPGEN generation.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.physiology.overrides import PhysiologicalStateOverride, PhysiologyCoverageReport
from opentrials.storage.populations import (
    PopulationArtifactManifest,
    semantic_population_content_hash,
)

PHYSIOLOGY_POPULATION_ID_PATTERN = r"^OTPHYS-[A-Za-z0-9_-]+$"
PHYSIOLOGY_POPULATION_ARTIFACT_SCHEMA = "opentrials.physiology-population-artifact"


class PhysiologyValueSummary(BaseModel):
    """A compact, auditable summary of one changed column before or after scaling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: float
    maximum: float
    mean: float


class PhysiologyPopulationTableArtifact(BaseModel):
    """Integrity information for a lossless physiology-overridden population table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = "individuals.parquet"
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class PhysiologyPopulationArtifactManifest(BaseModel):
    """Versioned identity and provenance record for one physiology-state population."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    physiology_population_id: str = Field(pattern=PHYSIOLOGY_POPULATION_ID_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    override: PhysiologicalStateOverride
    override_sha256: str = Field(pattern=SHA256_PATTERN)
    osp_parameter_path: str = Field(min_length=1)
    changed_column: str = Field(min_length=1)
    original_value_summary: PhysiologyValueSummary
    executed_value_summary: PhysiologyValueSummary
    coverage: PhysiologyCoverageReport
    individuals: PhysiologyPopulationTableArtifact


class PhysiologyPopulationArtifactStore:
    """Persist immutable physiology-state-overridden population tables."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_physiology_population(self, physiology_population_id: str) -> Path:
        """Create a unique directory for one physiology-state population."""
        if not physiology_population_id.startswith("OTPHYS-"):
            raise ValueError("Physiology population IDs must begin with 'OTPHYS-'.")
        directory = self.root / physiology_population_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_physiology_population(
        self,
        physiology_population_id: str,
        *,
        source_population_manifest: PopulationArtifactManifest,
        source_column_names: Sequence[str],
        source_rows: Sequence[Mapping[str, object]],
        override: PhysiologicalStateOverride,
        osp_parameter_path: str,
        coverage: PhysiologyCoverageReport,
    ) -> PhysiologyPopulationArtifactManifest:
        """Apply one verified override to an exact, already-verified OTPGEN table.

        ``source_column_names``/``source_rows`` must be the exact table
        already verified against ``source_population_manifest`` by the
        caller (for example via ``PopulationArtifactStore.verify_population``
        plus a Parquet read of that same artifact); this store performs no
        population verification of its own, matching the same trust
        boundary every other artifact store in this project uses.
        ``osp_parameter_path``/``coverage`` must already be resolved by the
        caller (see ``adapters.osp.physiology_targets``) -- this storage
        module stays engine-agnostic and never imports an OSP adapter,
        matching the layering used everywhere else in this project (storage
        never depends on adapters).
        """
        directory = self.root / physiology_population_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Physiology population directory does not exist: {physiology_population_id!r}."
            )
        parquet_path = directory / "individuals.parquet"
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Physiology population artifacts already exist for: "
                f"{physiology_population_id!r}."
            )
        if not source_rows:
            raise ValueError("Source population table must have at least one row.")

        column = osp_parameter_path
        normalized_columns = tuple(source_column_names)
        if column not in normalized_columns:
            raise ValueError(
                f"Source population table has no column for physiology target "
                f"{override.target!r} ({column!r})."
            )
        expected_columns = set(normalized_columns)
        if any(set(row) != expected_columns for row in source_rows):
            raise ValueError(
                "Every source population row must contain exactly the declared columns."
            )

        original_values = [_as_float(row[column], column) for row in source_rows]
        executed_rows: list[dict[str, object]] = []
        executed_values: list[float] = []
        for row, original in zip(source_rows, original_values, strict=True):
            executed_value = original * override.scale_factor
            executed_values.append(executed_value)
            executed_row = dict(row)
            executed_row[column] = executed_value
            executed_rows.append(executed_row)

        semantic_content_sha256 = semantic_population_content_hash(
            normalized_columns, executed_rows
        )
        table = pa.table(
            {col: [row[col] for row in executed_rows] for col in normalized_columns}
        )
        pq.write_table(table, parquet_path, compression="zstd")
        file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()

        manifest = PhysiologyPopulationArtifactManifest(
            physiology_population_id=physiology_population_id,
            source_generation_id=source_population_manifest.generation_id,
            source_population_semantic_sha256=(
                source_population_manifest.individuals.semantic_content_sha256
            ),
            override=override,
            override_sha256=sha256(override),
            osp_parameter_path=column,
            changed_column=column,
            original_value_summary=_summary(original_values),
            executed_value_summary=_summary(executed_values),
            coverage=coverage,
            individuals=PhysiologyPopulationTableArtifact(
                rows=len(executed_rows),
                columns=len(normalized_columns),
                file_sha256=file_sha256,
                semantic_content_sha256=semantic_content_sha256,
            ),
        )
        manifest_document = document(PHYSIOLOGY_POPULATION_ARTIFACT_SCHEMA, manifest)
        manifest_path.write_text(manifest_document.canonical_json() + "\n", encoding="utf-8")
        return manifest

    def read_manifest(
        self, physiology_population_id: str
    ) -> PhysiologyPopulationArtifactManifest:
        """Load and validate the versioned manifest for one physiology population."""
        path = self.root / physiology_population_id / "manifest.json"
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid physiology population manifest: {path}") from error
        if manifest_document.schema_id != PHYSIOLOGY_POPULATION_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected physiology population manifest schema: "
                f"{manifest_document.schema_id!r}."
            )
        return PhysiologyPopulationArtifactManifest.model_validate(manifest_document.payload)

    def verify_physiology_population(
        self, physiology_population_id: str
    ) -> PhysiologyPopulationArtifactManifest:
        """Verify file and semantic hashes by reloading the persisted Parquet table."""
        manifest = self.read_manifest(physiology_population_id)
        directory = self.root / physiology_population_id
        parquet_path = directory / manifest.individuals.path
        actual_file_sha256 = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_sha256 != manifest.individuals.file_sha256:
            raise ValueError(
                "Physiology population Parquet file hash does not match its manifest."
            )
        table = pq.read_table(parquet_path)
        columns = tuple(table.column_names)
        rows = tuple(dict(row) for row in table.to_pylist())
        actual_semantic_sha256 = semantic_population_content_hash(columns, rows)
        if actual_semantic_sha256 != manifest.individuals.semantic_content_sha256:
            raise ValueError(
                "Physiology population Parquet semantic content hash does not match its "
                "manifest."
            )
        if sha256(manifest.override) != manifest.override_sha256:
            raise ValueError("Physiology override hash does not match its manifest.")
        return manifest


def _as_float(value: object, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"Column {column!r} must be numeric to apply a physiological state override."
        )
    return float(value)


def _summary(values: Sequence[float]) -> PhysiologyValueSummary:
    return PhysiologyValueSummary(
        minimum=min(values), maximum=max(values), mean=statistics.fmean(values)
    )
