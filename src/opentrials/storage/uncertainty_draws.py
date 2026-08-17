"""Immutable Parquet artifacts for materialized uncertainty draws."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.uncertainty.execution import MaterializedUncertaintyDrawSet

DRAW_COLUMNS = ("draw_id", "draw_index", "parameter_id", "parameter_target", "value", "unit")
DRAW_ARTIFACT_SCHEMA = "opentrials.uncertainty-draw-artifact"
DRAW_PATH = "draws.parquet"


def _rows(draws: MaterializedUncertaintyDrawSet) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "draw_id": f"DRAW-{draw.draw_index + 1:06d}",
            "draw_index": draw.draw_index,
            "parameter_id": assignment.parameter_id,
            "parameter_target": assignment.target,
            "value": assignment.value,
            "unit": assignment.unit,
        }
        for draw in draws.draws
        for assignment in draw.assignments
    )


def semantic_draw_hash(rows: tuple[dict[str, object], ...]) -> str:
    return sha256({"columns": DRAW_COLUMNS, "rows": rows})


class DrawTableArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = DRAW_PATH
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    semantic_content_sha256: str = Field(pattern=SHA256_PATTERN)


class UncertaintyDrawArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draw_artifact_id: str = Field(pattern=r"^OTUDR-[A-Za-z0-9_-]+$")
    draws: MaterializedUncertaintyDrawSet
    draws_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    table: DrawTableArtifact


class UncertaintyDrawArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create_draw_artifact(self, artifact_id: str) -> Path:
        if not artifact_id.startswith("OTUDR-"):
            raise ValueError("Draw artifact IDs must begin with 'OTUDR-'.")
        path = self.root / artifact_id
        path.mkdir(parents=True, exist_ok=False)
        return path

    def write_draws(
        self, artifact_id: str, draws: MaterializedUncertaintyDrawSet
    ) -> UncertaintyDrawArtifactManifest:
        directory = self.root / artifact_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Draw artifact directory does not exist: {artifact_id!r}.")
        path = directory / DRAW_PATH
        manifest_path = directory / "manifest.json"
        if path.exists() or manifest_path.exists():
            raise FileExistsError(f"Draw artifact already exists for: {artifact_id!r}.")
        rows = _rows(draws)
        pq.write_table(
            pa.table({c: [r[c] for r in rows] for c in DRAW_COLUMNS}), path, compression="zstd"
        )
        manifest = UncertaintyDrawArtifactManifest(
            draw_artifact_id=artifact_id,
            draws=draws,
            draws_canonical_sha256=sha256(draws),
            table=DrawTableArtifact(
                rows=len(rows),
                columns=len(DRAW_COLUMNS),
                file_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                semantic_content_sha256=semantic_draw_hash(rows),
            ),
        )
        manifest_path.write_text(
            document(DRAW_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def verify_draw_artifact(self, artifact_id: str) -> UncertaintyDrawArtifactManifest:
        path = self.root / artifact_id / "manifest.json"
        try:
            document_value = SchemaDocument.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid draw artifact manifest: {path}") from error
        if document_value.schema_id != DRAW_ARTIFACT_SCHEMA:
            raise ValueError("Unexpected draw artifact manifest schema.")
        manifest = UncertaintyDrawArtifactManifest.model_validate(document_value.payload)
        if (
            manifest.draw_artifact_id != artifact_id
            or sha256(manifest.draws) != manifest.draws_canonical_sha256
        ):
            raise ValueError(
                "Draw artifact identity or canonical hash does not match its manifest."
            )
        parquet_path = self.root / artifact_id / manifest.table.path
        if (
            "sha256:" + hashlib.sha256(parquet_path.read_bytes()).hexdigest()
            != manifest.table.file_sha256
        ):
            raise ValueError("Draw Parquet file hash does not match its manifest.")
        table = pq.read_table(parquet_path)
        if (
            tuple(table.column_names) != DRAW_COLUMNS
            or table.num_rows != manifest.table.rows
            or table.num_columns != manifest.table.columns
        ):
            raise ValueError("Draw Parquet shape does not match its manifest.")
        rows = tuple(
            {column: table.column(column)[index].as_py() for column in DRAW_COLUMNS}
            for index in range(table.num_rows)
        )
        if semantic_draw_hash(rows) != manifest.table.semantic_content_sha256:
            raise ValueError("Draw Parquet semantic hash does not match its manifest.")
        return manifest
