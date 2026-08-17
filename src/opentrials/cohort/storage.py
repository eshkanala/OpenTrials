"""Immutable Parquet membership artifacts for evaluated cohorts and subgroups."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.cohort.definitions import (
    MEMBERSHIP_ID_PATTERN,
    CohortDefinition,
    CohortKind,
    FieldCatalog,
)
from opentrials.cohort.evaluator import CohortEvaluator, MembershipRow, source_row_sha256
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.storage.populations import PopulationArtifactStore

MEMBERSHIP_ARTIFACT_SCHEMA = "opentrials.cohort-membership-artifact"
MEMBERS_PATH = "members.parquet"
MEMBERS_COLUMNS = ("source_subject_id", "source_row_index", "source_row_sha256")


class MembershipTableArtifact(BaseModel):
    """Integrity details for the possibly empty member-reference table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = MEMBERS_PATH
    rows: int = Field(ge=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class EvaluatorProvenance(BaseModel):
    """Versioned identity of the deterministic evaluator implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluator_id: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)


class ParentMembershipReference(BaseModel):
    """Pinned parent artifact used to constrain subgroup evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    membership_id: str = Field(pattern=MEMBERSHIP_ID_PATTERN)
    members_semantic_sha256: str = Field(pattern=SHA256_PATTERN)


class CohortMembershipArtifactManifest(BaseModel):
    """Complete immutable selection provenance and member-table integrity record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    membership_id: str = Field(pattern=MEMBERSHIP_ID_PATTERN)
    definition: CohortDefinition
    definition_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    field_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    source_subject_id_column: str = Field(min_length=1)
    parent_membership: ParentMembershipReference | None = None
    evaluator: EvaluatorProvenance
    members: MembershipTableArtifact


def semantic_membership_hash(
    column_names: Sequence[str], rows: Sequence[Mapping[str, object]]
) -> str:
    """Hash member references independently of Parquet physical encoding."""
    columns = tuple(column_names)
    return sha256(
        {"columns": columns, "rows": [{column: row[column] for column in columns} for row in rows]}
    )


class CohortMembershipArtifactStore:
    """Persist evaluated cohort membership only after verifying its OTPGEN source."""

    def __init__(self, root: Path, population_store: PopulationArtifactStore) -> None:
        self.root = root
        self.population_store = population_store

    def create_membership(self, membership_id: str) -> Path:
        if not membership_id.startswith("OTMEM-"):
            raise ValueError("Membership IDs must begin with 'OTMEM-'.")
        directory = self.root / membership_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_membership(
        self,
        membership_id: str,
        *,
        definition: CohortDefinition,
        field_catalog: FieldCatalog,
        evaluator: CohortEvaluator | None = None,
    ) -> CohortMembershipArtifactManifest:
        """Verify source/lineage, evaluate, and persist members exactly once."""
        directory = self.root / membership_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Membership directory does not exist: {membership_id!r}.")
        parquet_path = directory / MEMBERS_PATH
        manifest_path = directory / "manifest.json"
        if parquet_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Membership artifacts already exist for membership: {membership_id!r}."
            )
        source_manifest = self.population_store.verify_population(definition.source_generation_id)
        source_table = pq.read_table(
            self.population_store.root
            / definition.source_generation_id
            / source_manifest.individuals.path
        )
        source_columns = tuple(source_table.column_names)
        source_rows = tuple(dict(row) for row in source_table.to_pylist())
        active_evaluator = evaluator or CohortEvaluator()
        parent_members: tuple[MembershipRow, ...] | None = None
        parent_reference: ParentMembershipReference | None = None
        if definition.kind is CohortKind.SUBGROUP:
            assert definition.parent_membership_id is not None
            parent_manifest = self.verify_membership(definition.parent_membership_id)
            if parent_manifest.source_generation_id != definition.source_generation_id:
                raise ValueError(
                    "Subgroup parent membership belongs to a different source generation."
                )
            if (
                parent_manifest.source_population_semantic_sha256
                != definition.source_population_semantic_sha256
            ):
                raise ValueError(
                    "Subgroup parent membership has a different source population hash."
                )
            parent_rows = self._read_member_rows(definition.parent_membership_id)
            self._verify_parent_rows(
                parent_rows, source_columns, source_rows, field_catalog.subject_id_column
            )
            parent_members = tuple(
                MembershipRow(
                    source_subject_id=str(row["source_subject_id"]),
                    source_row_index=self._member_row_index(row),
                    source_row_sha256=str(row["source_row_sha256"]),
                )
                for row in parent_rows
            )
            parent_reference = ParentMembershipReference(
                membership_id=definition.parent_membership_id,
                members_semantic_sha256=parent_manifest.members.semantic_content_sha256,
            )
        evaluated = active_evaluator.evaluate(
            definition,
            field_catalog=field_catalog,
            source_manifest=source_manifest,
            source_columns=source_columns,
            source_rows=source_rows,
            parent_members=parent_members,
        )
        rows = tuple(
            {
                "source_subject_id": member.source_subject_id,
                "source_row_index": member.source_row_index,
                "source_row_sha256": member.source_row_sha256,
            }
            for member in evaluated.members
        )
        table = pa.table({column: [row[column] for row in rows] for column in MEMBERS_COLUMNS})
        pq.write_table(table, parquet_path, compression="zstd")
        manifest = CohortMembershipArtifactManifest(
            membership_id=membership_id,
            definition=definition,
            definition_sha256=definition.canonical_sha256(),
            source_generation_id=definition.source_generation_id,
            source_population_semantic_sha256=definition.source_population_semantic_sha256,
            field_catalog_sha256=field_catalog.canonical_sha256(),
            source_subject_id_column=field_catalog.subject_id_column,
            parent_membership=parent_reference,
            evaluator=EvaluatorProvenance(
                evaluator_id=active_evaluator.evaluator_id,
                evaluator_version=active_evaluator.evaluator_version,
            ),
            members=MembershipTableArtifact(
                rows=len(rows),
                columns=len(MEMBERS_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_membership_hash(MEMBERS_COLUMNS, rows),
            ),
        )
        manifest_path.write_text(
            document(MEMBERSHIP_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def read_manifest(self, membership_id: str) -> CohortMembershipArtifactManifest:
        path = self.root / membership_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid cohort membership manifest: {path}") from error
        if envelope.schema_id != MEMBERSHIP_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected cohort membership schema: {envelope.schema_id!r}.")
        return CohortMembershipArtifactManifest.model_validate(envelope.payload)

    def verify_membership(self, membership_id: str) -> CohortMembershipArtifactManifest:
        manifest = self.read_manifest(membership_id)
        parquet_path = self.root / membership_id / manifest.members.path
        actual_file_hash = "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        if actual_file_hash != manifest.members.file_sha256:
            raise ValueError("Membership Parquet file hash does not match its manifest.")
        rows = self._read_member_rows(membership_id)
        actual_semantic_hash = semantic_membership_hash(MEMBERS_COLUMNS, rows)
        if actual_semantic_hash != manifest.members.semantic_content_sha256:
            raise ValueError("Membership Parquet semantic hash does not match its manifest.")
        if manifest.definition_sha256 != manifest.definition.canonical_sha256():
            raise ValueError("Membership definition hash does not match its manifest.")
        source_manifest = self.population_store.verify_population(manifest.source_generation_id)
        if (
            source_manifest.individuals.semantic_content_sha256
            != manifest.source_population_semantic_sha256
        ):
            raise ValueError("Membership source population hash does not match its manifest.")
        source_table = pq.read_table(
            self.population_store.root
            / manifest.source_generation_id
            / source_manifest.individuals.path
        )
        self._verify_parent_rows(
            rows,
            tuple(source_table.column_names),
            tuple(dict(row) for row in source_table.to_pylist()),
            manifest.source_subject_id_column,
        )
        return manifest

    def _read_member_rows(self, membership_id: str) -> tuple[dict[str, object], ...]:
        table = pq.read_table(self.root / membership_id / MEMBERS_PATH)
        if tuple(table.column_names) != MEMBERS_COLUMNS:
            raise ValueError("Membership Parquet columns do not match the membership contract.")
        return tuple(dict(row) for row in table.to_pylist())

    @staticmethod
    def _member_row_index(row: Mapping[str, object]) -> int:
        index = row["source_row_index"]
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Membership contains an invalid source row index.")
        return index

    @staticmethod
    def _verify_parent_rows(
        parent_rows: Sequence[Mapping[str, object]],
        source_columns: Sequence[str],
        source_rows: Sequence[Mapping[str, object]],
        subject_id_column: str,
    ) -> None:
        for member in parent_rows:
            index = member["source_row_index"]
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(source_rows)
            ):
                raise ValueError("Parent membership contains an invalid source row index.")
            row = source_rows[index]
            if str(row[subject_id_column]) != member["source_subject_id"]:
                raise ValueError(
                    "Parent membership subject ID does not match the verified source row."
                )
            if source_row_sha256(source_columns, row) != member["source_row_sha256"]:
                raise ValueError(
                    "Parent membership row hash does not match the verified source row."
                )
            row = source_rows[index]
            if str(row[subject_id_column]) != member["source_subject_id"]:
                raise ValueError(
                    "Parent membership subject ID does not match the verified source row."
                )
            if source_row_sha256(source_columns, row) != member["source_row_sha256"]:
                raise ValueError(
                    "Parent membership row hash does not match the verified source row."
                )
