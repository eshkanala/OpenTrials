"""The local filesystem ``RegistryBackend`` -- Registry v0.1's persistence layer.

Follows the exact write-once artifact-store discipline every other store
in this project uses (``storage.populations``, ``storage.connector_run``,
``cohort.storage``): one directory per record, a ``manifest.json`` wrapped
in the canonical ``SchemaDocument`` envelope, a content hash computed at
write time and independently re-derived at ``verify()`` time -- never
trusted from the manifest alone.

``RegistryBackend`` is a ``Protocol``, not a base class, so a future
SQLite- or hosted-service-backed implementation can be swapped in without
Studio (or anything else) changing a single call site -- the one
explicit requirement this backend was built against.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from opentrials.core.serialization import SchemaDocument, canonical_json, document, sha256
from opentrials.registry.schema import (
    PAYLOAD_TYPES,
    REGISTRY_ENTRY_SCHEMA,
    EvidenceClass,
    RegistryCompatibility,
    RegistryEntryManifest,
    RegistryRecordKind,
    RegistrySource,
    coerce_payload,
)


class RegistryError(ValueError):
    """A user-facing registry error: unknown record, hash mismatch, bad payload."""


class RegistryBackend(Protocol):
    """The interface every Registry backend (filesystem, SQLite, hosted) must satisfy."""

    def put(
        self,
        kind: RegistryRecordKind,
        payload: BaseModel,
        *,
        logical_id: str,
        evidence_class: EvidenceClass,
        license: str,
        source: RegistrySource,
        version: str = "1.0.0",
        provenance_ids: tuple[str, ...] = (),
        compatibility: RegistryCompatibility | None = None,
        superseded_id: str | None = None,
    ) -> RegistryEntryManifest: ...

    def get(self, record_id: str) -> tuple[RegistryEntryManifest, BaseModel]: ...

    def verify(self, record_id: str) -> RegistryEntryManifest: ...

    def list(self, kind: RegistryRecordKind | None = None) -> tuple[RegistryEntryManifest, ...]: ...

    def get_latest(self, logical_id: str) -> tuple[RegistryEntryManifest, BaseModel]: ...


class FilesystemRegistryBackend:
    """Persist Registry records as one directory per record under ``root``.

    ``root/<record_id>/manifest.json`` -- the ``RegistryEntryManifest``,
    wrapped in the standard ``SchemaDocument`` envelope.
    ``root/<record_id>/payload.json`` -- the kind-specific payload's
    canonical JSON (never embedded in the manifest, matching every other
    store's manifest/sidecar split).
    ``root/_latest/<logical_id>.json`` -- the *only* file this backend
    ever overwrites: a small pointer to the current record_id for a
    logical identity, so "give me the latest model" doesn't require
    scanning every version ever registered. Each versioned record itself
    stays write-once and immutable.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(
        self,
        kind: RegistryRecordKind,
        payload: BaseModel,
        *,
        logical_id: str,
        evidence_class: EvidenceClass,
        license: str,
        source: RegistrySource,
        version: str = "1.0.0",
        provenance_ids: tuple[str, ...] = (),
        compatibility: RegistryCompatibility | None = None,
        superseded_id: str | None = None,
    ) -> RegistryEntryManifest:
        expected_type = PAYLOAD_TYPES[kind]
        if type(payload) is not expected_type:  # noqa: E721 -- exact-type check on purpose
            raise RegistryError(
                f"Payload type mismatch for {kind!r}: expected "
                f"{expected_type.__name__}, got {type(payload).__name__}."
            )

        record_id = f"OTREG-{kind.value}-{uuid.uuid4().hex}"
        directory = self.root / record_id
        directory.mkdir(parents=True, exist_ok=False)

        payload_json = canonical_json(payload)
        (directory / "payload.json").write_text(payload_json, encoding="utf-8")
        payload_sha256 = sha256(payload)

        manifest = RegistryEntryManifest(
            record_id=record_id,
            logical_id=logical_id,
            kind=kind,
            version=version,
            evidence_class=evidence_class,
            license=license,
            source=source,
            compatibility=compatibility,
            provenance_ids=provenance_ids,
            payload_sha256=payload_sha256,
            superseded_id=superseded_id,
            created_at=datetime.now(UTC),
        )
        (directory / "manifest.json").write_text(
            document(REGISTRY_ENTRY_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )

        latest_dir = self.root / "_latest"
        latest_dir.mkdir(parents=True, exist_ok=True)
        (latest_dir / f"{logical_id}.json").write_text(
            json.dumps({"record_id": record_id}), encoding="utf-8"
        )
        return manifest

    def _read_manifest(self, record_id: str) -> RegistryEntryManifest:
        manifest_path = self.root / record_id / "manifest.json"
        if not manifest_path.is_file():
            raise RegistryError(f"Unknown registry record: {record_id!r}")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        try:
            envelope = SchemaDocument.model_validate(raw)
        except ValidationError as error:
            raise RegistryError(f"Invalid registry manifest envelope: {error}") from error
        if envelope.schema_id != REGISTRY_ENTRY_SCHEMA:
            raise RegistryError(
                f"Expected schema {REGISTRY_ENTRY_SCHEMA!r}; got {envelope.schema_id!r}."
            )
        try:
            return RegistryEntryManifest.model_validate(envelope.payload)
        except ValidationError as error:
            raise RegistryError(f"Invalid registry manifest: {error}") from error

    def get(self, record_id: str) -> tuple[RegistryEntryManifest, BaseModel]:
        manifest = self._read_manifest(record_id)
        payload_path = self.root / record_id / "payload.json"
        raw_payload: dict[str, Any] = json.loads(payload_path.read_text(encoding="utf-8"))
        try:
            payload = coerce_payload(manifest.kind, raw_payload)
        except ValidationError as error:
            raise RegistryError(f"Invalid registry payload: {error}") from error
        return manifest, payload

    def verify(self, record_id: str) -> RegistryEntryManifest:
        """Re-verify the payload's hash from disk -- never trust the manifest alone."""
        manifest, payload = self.get(record_id)
        actual_sha256 = sha256(payload)
        if actual_sha256 != manifest.payload_sha256:
            raise RegistryError(
                f"Registry record {record_id!r} failed verification: payload hash "
                f"mismatch (manifest claims {manifest.payload_sha256}, actual "
                f"content hashes to {actual_sha256})."
            )
        return manifest

    def list(self, kind: RegistryRecordKind | None = None) -> tuple[RegistryEntryManifest, ...]:
        if not self.root.is_dir():
            return ()
        manifests = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or entry.name == "_latest":
                continue
            manifest = self._read_manifest(entry.name)
            if kind is None or manifest.kind is kind:
                manifests.append(manifest)
        manifests.sort(key=lambda m: m.created_at, reverse=True)
        return tuple(manifests)

    def get_latest(self, logical_id: str) -> tuple[RegistryEntryManifest, BaseModel]:
        pointer_path = self.root / "_latest" / f"{logical_id}.json"
        if not pointer_path.is_file():
            raise RegistryError(f"No registered record found for logical_id: {logical_id!r}")
        record_id = json.loads(pointer_path.read_text(encoding="utf-8"))["record_id"]
        return self.get(record_id)
