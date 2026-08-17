"""Immutable Parquet artifacts for extreme-responder and reference memberships.

Mirrors ``CohortMembershipArtifactStore``'s trust model: this store never
trusts a caller-supplied row list or a lineage claim at face value. It always
independently re-verifies both its OTPK source (schema v2+, lineage-capable,
matching the definition's pinned hash) and its OTPGEN source, and recomputes
every selected subject's row hash directly from the real population table
before persisting -- a tampered or stale OTPK lineage claim is rejected here,
not merely assumed correct because it was already checked once elsewhere.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.responders.definitions import (
    RESPONDER_MEMBERSHIP_ID_PATTERN,
    ExtremeResponderDefinition,
)
from opentrials.responders.selection import (
    RankableSubject,
    RankedSubject,
    select_extreme_responders,
)
from opentrials.storage.endpoints import (
    MIN_LINEAGE_CAPABLE_SCHEMA_MAJOR,
    PkEndpointArtifactStore,
    schema_major_version,
)
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.row_identity import source_row_sha256

RESPONDER_MEMBERSHIP_ARTIFACT_SCHEMA = "opentrials.extreme-responder-membership-artifact"
RESPONDER_MEMBERS_PATH = "members.parquet"
RESPONDER_MEMBER_COLUMNS = (
    "source_subject_id",
    "source_row_index",
    "source_row_sha256",
    "rank",
    "endpoint_value",
)


class ResponderGroupKind(StrEnum):
    """Which side of one selection a membership artifact represents."""

    EXTREME = "EXTREME"
    REFERENCE = "REFERENCE"


def _semantic_value(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def semantic_responder_membership_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash member references independently of Parquet physical encoding."""
    columns = tuple(column_names)
    return sha256(
        {
            "columns": columns,
            "rows": [{column: _semantic_value(row[column]) for column in columns} for row in rows],
        }
    )


class ResponderMembershipTableArtifact(BaseModel):
    """Integrity details for the possibly empty member table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = RESPONDER_MEMBERS_PATH
    rows: int = Field(ge=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class ExtremeResponderMembershipArtifactManifest(BaseModel):
    """Complete immutable selection provenance and member-table integrity record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    membership_id: str = Field(pattern=RESPONDER_MEMBERSHIP_ID_PATTERN)
    group_kind: ResponderGroupKind
    definition: ExtremeResponderDefinition
    definition_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    source_endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_unit: str = Field(min_length=1)
    total_population: int = Field(gt=0)
    threshold_value: float
    members: ResponderMembershipTableArtifact


class ExtremeResponderMembershipArtifactStore:
    """Verify OTPK/OTPGEN sources, select deterministically, and persist once."""

    def __init__(
        self,
        root: Path,
        *,
        endpoint_store: PkEndpointArtifactStore,
        population_store: PopulationArtifactStore,
    ) -> None:
        self.root = root
        self.endpoint_store = endpoint_store
        self.population_store = population_store

    def create_membership(self, membership_id: str) -> Path:
        if not membership_id.startswith("OTXMEM-"):
            raise ValueError("Responder membership IDs must begin with 'OTXMEM-'.")
        directory = self.root / membership_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_membership(
        self,
        membership_id: str,
        *,
        definition: ExtremeResponderDefinition,
        group_kind: ResponderGroupKind,
    ) -> ExtremeResponderMembershipArtifactManifest:
        """Verify sources, evaluate the definition, and persist one group's rows."""
        directory = self.root / membership_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Membership directory does not exist: {membership_id!r}.")
        parquet_path = directory / RESPONDER_MEMBERS_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Responder membership artifacts already exist for: {membership_id!r}."
            )

        endpoint_manifest = self.endpoint_store.verify_endpoints(definition.source_endpoint_id)
        if endpoint_manifest.endpoints.semantic_content_sha256 != (
            definition.source_endpoint_semantic_sha256
        ):
            raise ValueError("Definition endpoint hash does not match the verified OTPK artifact.")
        if (
            not endpoint_manifest.population_lineage_present
            or schema_major_version(endpoint_manifest.schema_version)
            < MIN_LINEAGE_CAPABLE_SCHEMA_MAJOR
        ):
            raise ValueError(
                "Endpoint artifact lacks population lineage. Schema v2+ required for "
                "extreme-responder selection."
            )
        if (
            endpoint_manifest.source_generation_id != definition.source_generation_id
            or endpoint_manifest.source_population_semantic_sha256
            != definition.source_population_semantic_sha256
        ):
            raise ValueError("Endpoint artifact population identity does not match the definition.")

        population_manifest = self.population_store.verify_population(
            definition.source_generation_id
        )
        if (
            population_manifest.individuals.semantic_content_sha256
            != definition.source_population_semantic_sha256
        ):
            raise ValueError("Population hash does not match the definition's pinned identity.")

        endpoint_rows = self.endpoint_store.read_rows(definition.source_endpoint_id)
        subjects, endpoint_unit = _rankable_subjects(endpoint_rows, definition.endpoint_type.value)

        population_table = pq.read_table(
            self.population_store.root
            / definition.source_generation_id
            / population_manifest.individuals.path
        )
        population_columns = tuple(population_table.column_names)
        population_rows = tuple(dict(row) for row in population_table.to_pylist())
        _verify_subject_lineage(subjects, population_columns, population_rows)

        result = select_extreme_responders(subjects, definition)
        selected = result.extreme if group_kind is ResponderGroupKind.EXTREME else result.reference

        rows = tuple(
            {
                "source_subject_id": subject.subject_id,
                "source_row_index": subject.source_row_index,
                "source_row_sha256": subject.source_row_sha256,
                "rank": subject.rank,
                "endpoint_value": subject.value,
            }
            for subject in selected
        )
        _write_members_table(parquet_path, rows)
        semantic_content_sha256 = semantic_responder_membership_hash(RESPONDER_MEMBER_COLUMNS, rows)

        manifest = ExtremeResponderMembershipArtifactManifest(
            membership_id=membership_id,
            group_kind=group_kind,
            definition=definition,
            definition_sha256=definition.canonical_sha256(),
            source_generation_id=definition.source_generation_id,
            source_population_semantic_sha256=definition.source_population_semantic_sha256,
            source_endpoint_id=definition.source_endpoint_id,
            source_endpoint_semantic_sha256=definition.source_endpoint_semantic_sha256,
            endpoint_unit=endpoint_unit,
            total_population=result.total_population,
            threshold_value=result.threshold_value,
            members=ResponderMembershipTableArtifact(
                rows=len(rows),
                columns=len(RESPONDER_MEMBER_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_content_sha256,
            ),
        )
        manifest_path.write_text(
            document(RESPONDER_MEMBERSHIP_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, membership_id: str) -> ExtremeResponderMembershipArtifactManifest:
        path = self.root / membership_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid responder membership manifest: {path}") from error
        if envelope.schema_id != RESPONDER_MEMBERSHIP_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected responder membership schema: {envelope.schema_id!r}.")
        return ExtremeResponderMembershipArtifactManifest.model_validate(envelope.payload)

    def verify_membership(self, membership_id: str) -> ExtremeResponderMembershipArtifactManifest:
        manifest = self.read_manifest(membership_id)
        parquet_path = self.root / membership_id / manifest.members.path
        actual_file_hash = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_hash != manifest.members.file_sha256:
            raise ValueError("Responder membership Parquet file hash does not match its manifest.")
        rows = self._read_member_rows(membership_id)
        actual_semantic_hash = semantic_responder_membership_hash(RESPONDER_MEMBER_COLUMNS, rows)
        if actual_semantic_hash != manifest.members.semantic_content_sha256:
            raise ValueError(
                "Responder membership Parquet semantic hash does not match its manifest."
            )
        if manifest.definition_sha256 != manifest.definition.canonical_sha256():
            raise ValueError("Responder membership definition hash does not match its manifest.")
        population_manifest = self.population_store.verify_population(manifest.source_generation_id)
        if (
            population_manifest.individuals.semantic_content_sha256
            != manifest.source_population_semantic_sha256
        ):
            raise ValueError(
                "Responder membership source population hash does not match its manifest."
            )
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
                raise ValueError("Responder membership references a row outside the population.")
            actual_hash = source_row_sha256(population_columns, population_rows[index])
            if actual_hash != row["source_row_sha256"]:
                raise ValueError(
                    "Responder membership row hash does not match the verified population row."
                )
        return manifest

    def read_member_rows(self, membership_id: str) -> tuple[RankedSubject, ...]:
        self.verify_membership(membership_id)
        return tuple(
            RankedSubject(
                subject_id=str(row["source_subject_id"]),
                source_row_index=_as_int(row["source_row_index"]),
                source_row_sha256=str(row["source_row_sha256"]),
                value=float(row["endpoint_value"]),  # type: ignore[arg-type]
                rank=_as_int(row["rank"]),
            )
            for row in self._read_member_rows(membership_id)
        )

    def _read_member_rows(self, membership_id: str) -> tuple[dict[str, object], ...]:
        table = pq.read_table(self.root / membership_id / RESPONDER_MEMBERS_PATH)
        if tuple(table.column_names) != RESPONDER_MEMBER_COLUMNS:
            raise ValueError("Responder membership Parquet columns do not match the contract.")
        return tuple(dict(row) for row in table.to_pylist())


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer value in a responder membership row.")
    return value


def _rankable_subjects(
    endpoint_rows: Sequence[Mapping[str, object]], endpoint_type: str
) -> tuple[tuple[RankableSubject, ...], str]:
    """Extract lineage-verified per-subject values for one endpoint type."""
    unit: str | None = None
    subjects: list[RankableSubject] = []
    for row in endpoint_rows:
        if row.get("endpoint_type") != endpoint_type:
            continue
        row_unit = row.get("unit")
        assert isinstance(row_unit, str)
        if unit is None:
            unit = row_unit
        elif unit != row_unit:
            raise ValueError(
                f"Endpoint artifact has inconsistent units for {endpoint_type}: "
                f"{unit!r} vs {row_unit!r}."
            )
        row_index = row.get("source_population_row_index")
        row_hash = row.get("source_population_row_sha256")
        subject_id = row.get("subject_id")
        value = row.get("value")
        if row_index is None or row_hash is None:
            raise ValueError(
                f"Endpoint row for subject {subject_id!r} has no population lineage."
            )
        assert isinstance(row_index, int)
        assert isinstance(row_hash, str)
        assert isinstance(subject_id, str)
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        subjects.append(
            RankableSubject(
                subject_id=subject_id,
                source_row_index=row_index,
                source_row_sha256=row_hash,
                value=float(value),
            )
        )
    if not subjects:
        raise ValueError(f"Endpoint artifact has no rows for endpoint type {endpoint_type!r}.")
    assert unit is not None
    return tuple(subjects), unit


def _verify_subject_lineage(
    subjects: Sequence[RankableSubject],
    population_columns: Sequence[str],
    population_rows: Sequence[Mapping[str, object]],
) -> None:
    """Reject any OTPK lineage claim that disagrees with the real population table."""
    for subject in subjects:
        if not 0 <= subject.source_row_index < len(population_rows):
            raise ValueError(
                f"Endpoint subject {subject.subject_id!r} references a row outside the "
                "verified population."
            )
        actual_hash = source_row_sha256(
            population_columns, population_rows[subject.source_row_index]
        )
        if actual_hash != subject.source_row_sha256:
            raise ValueError(
                f"Endpoint subject {subject.subject_id!r} lineage does not match the verified "
                "population row."
            )


def _write_members_table(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    columns: dict[str, pa.Array] = {
        "source_subject_id": pa.array(
            [row["source_subject_id"] for row in rows], type=pa.string()
        ),
        "source_row_index": pa.array([row["source_row_index"] for row in rows], type=pa.int64()),
        "source_row_sha256": pa.array(
            [row["source_row_sha256"] for row in rows], type=pa.string()
        ),
        "rank": pa.array([row["rank"] for row in rows], type=pa.int64()),
        "endpoint_value": pa.array([row["endpoint_value"] for row in rows], type=pa.float64()),
    }
    table = pa.table(columns)
    pq.write_table(table, path, compression="zstd")
