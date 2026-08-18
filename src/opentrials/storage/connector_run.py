"""Immutable top-level provenance record for one evidence-connector run.

An ``OTCONN`` artifact is the authoritative link between a raw snapshot
(``OTRAW``) and the observed dataset (``OTOBS``) a connector derived from
it -- it computes nothing itself and duplicates no content, exactly the
role ``VirtualTrialArtifactManifest``/``OTTRIAL`` plays for a trial's own
sub-artifacts. ``verify_connector_run()`` re-verifies the whole chain from
each sub-artifact's own store, never from values trusted at write time.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.models.package import SHA256_PATTERN
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore

CONNECTOR_RUN_ID_PREFIX = "OTCONN-"
CONNECTOR_RUN_ARTIFACT_SCHEMA = "opentrials.data-connector-run-artifact"


class DataConnectorRunManifest(BaseModel):
    """Versioned, independently re-verifiable record of one connector run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    run_id: str = Field(pattern=r"^OTCONN-[A-Za-z0-9_-]+$")
    identity: DataConnectorIdentity
    source: SourceDescriptor
    raw_snapshot_id: str = Field(pattern=r"^OTRAW-[A-Za-z0-9_-]+$")
    raw_snapshot_content_sha256: str = Field(pattern=SHA256_PATTERN)
    observed_dataset_id: str = Field(pattern=r"^OTOBS-[A-Za-z0-9_-]+$")
    observed_dataset_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    transformation_provenance: tuple[TransformationStep, ...] = Field(min_length=1)
    created_at: str


class DataConnectorRunArtifactStore:
    """Persist immutable evidence-connector-run provenance records by ID."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_connector_run(self, run_id: str) -> Path:
        """Create the unique directory for one connector-run artifact."""
        if not run_id.startswith(CONNECTOR_RUN_ID_PREFIX):
            raise ValueError(f"Connector run IDs must begin with {CONNECTOR_RUN_ID_PREFIX!r}.")
        directory = self.root / run_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_connector_run(
        self,
        run_id: str,
        *,
        identity: DataConnectorIdentity,
        source: SourceDescriptor,
        raw_snapshot_id: str,
        raw_snapshot_content_sha256: str,
        observed_dataset_id: str,
        observed_dataset_canonical_sha256: str,
        transformation_provenance: tuple[TransformationStep, ...],
        created_at: datetime,
    ) -> DataConnectorRunManifest:
        """Write one connector run's provenance record exactly once."""
        directory = self.root / run_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Connector run directory does not exist: {run_id!r}.")
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(f"Connector run artifact already exists for: {run_id!r}.")

        manifest = DataConnectorRunManifest(
            run_id=run_id,
            identity=identity,
            source=source,
            raw_snapshot_id=raw_snapshot_id,
            raw_snapshot_content_sha256=raw_snapshot_content_sha256,
            observed_dataset_id=observed_dataset_id,
            observed_dataset_canonical_sha256=observed_dataset_canonical_sha256,
            transformation_provenance=transformation_provenance,
            created_at=created_at.isoformat(),
        )
        manifest_document = document(CONNECTOR_RUN_ARTIFACT_SCHEMA, manifest)
        manifest_path.write_text(manifest_document.canonical_json() + "\n", encoding="utf-8")
        return manifest

    def read_manifest(self, run_id: str) -> DataConnectorRunManifest:
        """Load and validate the versioned manifest for one connector run."""
        path = self.root / run_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid connector run manifest: {path}") from error
        if manifest_document.schema_id != CONNECTOR_RUN_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected connector run manifest schema: {manifest_document.schema_id!r}."
            )
        return DataConnectorRunManifest.model_validate(manifest_document.payload)

    def verify_connector_run(
        self,
        run_id: str,
        *,
        raw_snapshot_store: RawSnapshotArtifactStore,
        observed_store: ObservedArtifactStore,
    ) -> DataConnectorRunManifest:
        """Re-verify the whole raw-snapshot -> observed-dataset chain from source stores."""
        manifest = self.read_manifest(run_id)
        if manifest.run_id != run_id:
            raise ValueError("Connector run manifest ID does not match its directory ID.")

        raw_snapshot_manifest = raw_snapshot_store.verify_raw_snapshot(manifest.raw_snapshot_id)
        if raw_snapshot_manifest.content_sha256 != manifest.raw_snapshot_content_sha256:
            raise ValueError(
                "Connector run's recorded raw snapshot hash does not match the verified "
                "raw snapshot artifact."
            )

        observed_manifest = observed_store.verify_observed_dataset(manifest.observed_dataset_id)
        if observed_manifest.dataset_canonical_sha256 != manifest.observed_dataset_canonical_sha256:
            raise ValueError(
                "Connector run's recorded observed-dataset hash does not match the verified "
                "observed dataset artifact."
            )
        if observed_manifest.license != manifest.source.license:
            raise ValueError(
                "Connector run's declared source license does not match the persisted "
                "observed dataset's license."
            )
        if observed_manifest.source_identifier != (
            manifest.source.doi or manifest.source.accession or manifest.source.source_url
        ):
            raise ValueError(
                "Connector run's declared source locator does not match the persisted "
                "observed dataset's source_identifier."
            )
        return manifest
