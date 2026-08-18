"""Fetch, normalize, and immutably persist one evidence-connector run.

The generic v0.8-A orchestration entry point: takes any ``DataConnector``
and turns its fetch-then-normalize cycle into three immutable, independently
re-verifiable artifacts. Nothing here knows about a specific source --
that knowledge lives entirely inside the connector passed in, matching the
same generality discipline v0.7-B established for model execution.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from opentrials.evidence.connector import DataConnector, run_connector
from opentrials.storage.connector_run import (
    DataConnectorRunArtifactStore,
    DataConnectorRunManifest,
)
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore


def ingest_evidence(
    connector: DataConnector,
    *,
    raw_snapshot_root: Path,
    observed_root: Path,
    connector_run_root: Path,
) -> DataConnectorRunManifest:
    """Run one connector's fetch/normalize cycle and persist every resulting artifact.

    Persists, in order: the raw snapshot exactly as fetched (``OTRAW``), the
    normalized observed dataset (``OTOBS``, via the same store every other
    observed-evidence artifact in this project already uses), and a
    top-level connector-run provenance record (``OTCONN``) linking the two
    by hash. The connector-run record trusts nothing from the in-memory
    result once persisted -- ``DataConnectorRunArtifactStore.verify_connector_run()``
    re-derives every hash from each sub-artifact's own store.
    """
    result = run_connector(connector)

    raw_snapshot_id = f"OTRAW-{uuid.uuid4().hex}"
    raw_snapshot_store = RawSnapshotArtifactStore(raw_snapshot_root)
    raw_snapshot_store.create_raw_snapshot(raw_snapshot_id)
    raw_snapshot_manifest = raw_snapshot_store.write_raw_snapshot(
        raw_snapshot_id, result.raw_snapshot
    )

    observed_store = ObservedArtifactStore(observed_root)
    observed_store.create_observed_dataset(result.dataset.dataset_id)
    observed_manifest = observed_store.write_observed_dataset(result.dataset)

    run_id = f"OTCONN-{uuid.uuid4().hex}"
    connector_run_store = DataConnectorRunArtifactStore(connector_run_root)
    connector_run_store.create_connector_run(run_id)
    return connector_run_store.write_connector_run(
        run_id,
        identity=result.identity,
        source=result.source,
        raw_snapshot_id=raw_snapshot_id,
        raw_snapshot_content_sha256=raw_snapshot_manifest.content_sha256,
        observed_dataset_id=result.dataset.dataset_id,
        observed_dataset_canonical_sha256=observed_manifest.dataset_canonical_sha256,
        transformation_provenance=result.transformation_provenance,
        created_at=datetime.now(UTC),
    )
