"""Immutable byte-for-byte storage for evidence-connector raw snapshots.

An ``OTRAW`` artifact is the unmodified content a ``DataConnector.fetch()``
returned, persisted once and never rewritten -- the same "prove the input,
don't just trust it" discipline every other immutable artifact in this
project follows. It deliberately stores raw bytes, not an interpretation of
them; what those bytes mean is the connector's ``normalize()`` step and the
resulting ``ObservedDataset``/``Evidence`` records, persisted separately by
``ObservedArtifactStore``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document
from opentrials.evidence.connector import RawSnapshot
from opentrials.models.package import SHA256_PATTERN

RAW_SNAPSHOT_ID_PREFIX = "OTRAW-"
RAW_SNAPSHOT_ARTIFACT_SCHEMA = "opentrials.raw-snapshot-artifact"
RAW_SNAPSHOT_CONTENT_PATH = "raw.bin"


class RawSnapshotArtifactManifest(BaseModel):
    """Integrity and retrieval metadata for one immutable raw snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    raw_snapshot_id: str = Field(pattern=r"^OTRAW-[A-Za-z0-9_-]+$")
    media_type: str = Field(min_length=1)
    retrieved_at: str
    byte_length: int = Field(ge=0)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    path: str = RAW_SNAPSHOT_CONTENT_PATH


class RawSnapshotArtifactStore:
    """Persist immutable raw-content snapshots by ID, verified by content hash."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_raw_snapshot(self, raw_snapshot_id: str) -> Path:
        """Create the unique directory for one raw snapshot artifact."""
        if not raw_snapshot_id.startswith(RAW_SNAPSHOT_ID_PREFIX):
            raise ValueError(f"Raw snapshot IDs must begin with {RAW_SNAPSHOT_ID_PREFIX!r}.")
        directory = self.root / raw_snapshot_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_raw_snapshot(
        self, raw_snapshot_id: str, snapshot: RawSnapshot
    ) -> RawSnapshotArtifactManifest:
        """Write one raw snapshot's exact bytes exactly once."""
        if not raw_snapshot_id.startswith(RAW_SNAPSHOT_ID_PREFIX):
            raise ValueError(f"Raw snapshot IDs must begin with {RAW_SNAPSHOT_ID_PREFIX!r}.")
        directory = self.root / raw_snapshot_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Raw snapshot directory does not exist: {raw_snapshot_id!r}.")
        content_path = directory / RAW_SNAPSHOT_CONTENT_PATH
        manifest_path = directory / "manifest.json"
        if content_path.exists() or manifest_path.exists():
            raise FileExistsError(f"Raw snapshot artifacts already exist for: {raw_snapshot_id!r}.")

        content_path.write_bytes(snapshot.content)
        manifest = RawSnapshotArtifactManifest(
            raw_snapshot_id=raw_snapshot_id,
            media_type=snapshot.media_type,
            retrieved_at=snapshot.retrieved_at.isoformat(),
            byte_length=len(snapshot.content),
            content_sha256=snapshot.content_sha256(),
        )
        manifest_document = document(RAW_SNAPSHOT_ARTIFACT_SCHEMA, manifest)
        manifest_path.write_text(manifest_document.canonical_json() + "\n", encoding="utf-8")
        return manifest

    def read_manifest(self, raw_snapshot_id: str) -> RawSnapshotArtifactManifest:
        """Load and validate the versioned manifest for one raw snapshot."""
        path = self.root / raw_snapshot_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid raw snapshot manifest: {path}") from error
        if manifest_document.schema_id != RAW_SNAPSHOT_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected raw snapshot manifest schema: {manifest_document.schema_id!r}."
            )
        return RawSnapshotArtifactManifest.model_validate(manifest_document.payload)

    def read_content(self, raw_snapshot_id: str) -> bytes:
        """Read the persisted raw bytes for one snapshot, unmodified."""
        return (self.root / raw_snapshot_id / RAW_SNAPSHOT_CONTENT_PATH).read_bytes()

    def verify_raw_snapshot(self, raw_snapshot_id: str) -> RawSnapshotArtifactManifest:
        """Verify the persisted bytes still hash to what the manifest declares."""
        manifest = self.read_manifest(raw_snapshot_id)
        if manifest.raw_snapshot_id != raw_snapshot_id:
            raise ValueError("Raw snapshot manifest ID does not match its directory ID.")
        content = self.read_content(raw_snapshot_id)
        if len(content) != manifest.byte_length:
            raise ValueError("Raw snapshot byte length does not match its manifest.")
        actual_sha256 = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual_sha256 != manifest.content_sha256:
            raise ValueError("Raw snapshot content hash does not match its manifest.")
        return manifest
