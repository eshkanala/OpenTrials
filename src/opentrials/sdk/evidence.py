"""The default, pre-composed set of evidence connectors this project ships.

Mirrors ``sdk.registry.default_model_registry``'s own composition pattern
exactly: ``evidence.connector.DataConnector`` is deliberately generic and
knows nothing about any specific source (see its own module docstring).
Composing it with the connectors this project actually ships is a top-level
concern, not a core one -- this is that composition, and the one place a
new connector needs to be added to become reachable from the SDK/Studio.
"""

from __future__ import annotations

from pathlib import Path

from opentrials.evidence.connector import DataConnector
from opentrials.evidence.connectors import (
    OspBundledLaskin1982Connector,
    OspBundledPkObservationsConnector,
)
from opentrials.orchestration.evidence_ingestion import ingest_evidence
from opentrials.storage.connector_run import DataConnectorRunManifest


def default_evidence_connectors(*, r_libs_user: str | None = None) -> tuple[DataConnector, ...]:
    """Build every evidence connector this project ships, ready to run."""
    return (
        OspBundledPkObservationsConnector(r_libs_user=r_libs_user),
        OspBundledLaskin1982Connector(r_libs_user=r_libs_user),
    )


def ingest_and_persist(
    connector: DataConnector, *, evidence_root: Path
) -> DataConnectorRunManifest:
    """Run one connector and immutably persist its raw/observed/connector-run artifacts.

    A thin SDK-level wrapper over the existing generic
    ``orchestration.evidence_ingestion.ingest_evidence`` -- derives its three
    sub-roots from one ``evidence_root`` (mirroring how ``sdk.project.Project.run``
    derives ``population_root`` from ``output_root``), so a caller only needs
    to know where evidence lives for this project, not the artifact layout.
    Returns the real, hash-chained ``OTCONN-*`` manifest -- the identifier a
    caller should record (e.g. in ``Trial.evidence_ids``), not the connector's
    own class identity, since only the manifest is independently re-verifiable.
    """
    return ingest_evidence(
        connector,
        raw_snapshot_root=evidence_root / "raw",
        observed_root=evidence_root / "observed",
        connector_run_root=evidence_root / "connector_runs",
    )
