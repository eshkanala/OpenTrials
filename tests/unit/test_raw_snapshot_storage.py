"""Contract tests for the immutable OTRAW raw-snapshot artifact store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.evidence.connector import RawSnapshot
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore


def test_raw_snapshot_round_trips_and_verifies(tmp_path: Path) -> None:
    store = RawSnapshotArtifactStore(tmp_path / "raw")
    store.create_raw_snapshot("OTRAW-001")
    snapshot = RawSnapshot(
        content=b"hello world",
        media_type="text/plain",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    manifest = store.write_raw_snapshot("OTRAW-001", snapshot)

    assert manifest.byte_length == len(b"hello world")
    assert manifest.content_sha256 == snapshot.content_sha256()
    assert store.read_content("OTRAW-001") == b"hello world"

    verified = store.verify_raw_snapshot("OTRAW-001")
    assert verified == manifest


def test_raw_snapshot_rejects_wrong_id_prefix(tmp_path: Path) -> None:
    store = RawSnapshotArtifactStore(tmp_path / "raw")
    with pytest.raises(ValueError, match="OTRAW-"):
        store.create_raw_snapshot("bad-id")


def test_raw_snapshot_cannot_be_written_twice(tmp_path: Path) -> None:
    store = RawSnapshotArtifactStore(tmp_path / "raw")
    store.create_raw_snapshot("OTRAW-002")
    snapshot = RawSnapshot(
        content=b"x", media_type="text/plain", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    store.write_raw_snapshot("OTRAW-002", snapshot)
    with pytest.raises(FileExistsError):
        store.write_raw_snapshot("OTRAW-002", snapshot)


def test_verify_detects_tampered_content(tmp_path: Path) -> None:
    store = RawSnapshotArtifactStore(tmp_path / "raw")
    store.create_raw_snapshot("OTRAW-003")
    snapshot = RawSnapshot(
        content=b"original", media_type="text/plain", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    store.write_raw_snapshot("OTRAW-003", snapshot)

    (tmp_path / "raw" / "OTRAW-003" / "raw.bin").write_bytes(b"tamperd!")  # same byte length

    with pytest.raises(ValueError, match="content hash"):
        store.verify_raw_snapshot("OTRAW-003")
