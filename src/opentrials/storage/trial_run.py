"""The immutable, authoritative provenance record for one executed virtual trial.

``OTTRIAL`` does not compute anything itself -- every field it records was
already independently verified by the artifact store that produced it
(OTPGEN, OTALLOC, per-arm OTRES/OTPK, OTACMP). It is a pure roll-up: the
single record answering "is this the trial that was actually executed?" by
referencing every other artifact's immutable ID and content hash. On
reload, ``verify_trial_run()`` re-verifies every referenced sub-artifact
against its own store rather than trusting the roll-up's claims.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document
from opentrials.models.package import SHA256_PATTERN
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.arm_comparison_artifacts import ArmComparisonArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore

TRIAL_RUN_ID_PATTERN = r"^OTTRIAL-[A-Za-z0-9_-]+$"
TRIAL_RUN_ARTIFACT_SCHEMA = "opentrials.virtual-trial-run-artifact"


class ObservationScheduleRecord(BaseModel):
    """Provenance of one declared, verified observation schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_id: str = Field(min_length=1)
    declared_times_min: tuple[float, ...] = Field(min_length=1)


class ArmRunRecord(BaseModel):
    """Complete provenance for one arm's independently executed OSP run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    requested_dose_mg: float = Field(gt=0)
    participant_count: int = Field(gt=0)
    executed_run_id: str = Field(min_length=1)
    raw_response_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_verification_sha256: str = Field(pattern=SHA256_PATTERN)
    observation_schedule_verified: bool | None = None
    result_id: str = Field(pattern=r"^OTRES-[A-Za-z0-9_-]+$")
    result_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)


class VirtualTrialArtifactManifest(BaseModel):
    """The complete, immutable, reconstructible provenance record of one trial."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    trial_run_id: str = Field(pattern=TRIAL_RUN_ID_PATTERN)
    trial_id: str = Field(min_length=1)
    trial_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    allocation_id: str = Field(pattern=r"^OTALLOC-[A-Za-z0-9_-]+$")
    allocation_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    allocation_seed: int
    allocation_apportionment_method: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_sha256: str = Field(pattern=SHA256_PATTERN)
    observation_schedule: ObservationScheduleRecord | None = None
    arms: tuple[ArmRunRecord, ...] = Field(min_length=2)
    comparison_id: str | None = Field(default=None, pattern=r"^OTACMP-[A-Za-z0-9_-]+$")
    comparison_semantic_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    software_versions: dict[str, str]
    created_at: datetime


class TrialRunArtifactStore:
    """Persist and reload the immutable OTTRIAL provenance record."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_trial_run(self, trial_run_id: str) -> Path:
        if not trial_run_id.startswith("OTTRIAL-"):
            raise ValueError("Trial run IDs must begin with 'OTTRIAL-'.")
        directory = self.root / trial_run_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_trial_run(
        self, trial_run_id: str, manifest: VirtualTrialArtifactManifest
    ) -> VirtualTrialArtifactManifest:
        """Persist an already-assembled, already-verified trial-run record exactly once."""
        directory = self.root / trial_run_id
        if not directory.is_dir():
            raise FileNotFoundError(f"Trial run directory does not exist: {trial_run_id!r}.")
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(f"Trial run artifact already exists for: {trial_run_id!r}.")
        if manifest.trial_run_id != trial_run_id:
            raise ValueError("Manifest trial_run_id does not match the target directory.")
        manifest_path.write_text(
            document(TRIAL_RUN_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n", encoding="utf-8"
        )
        return manifest

    def read_manifest(self, trial_run_id: str) -> VirtualTrialArtifactManifest:
        path = self.root / trial_run_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid virtual trial run manifest: {path}") from error
        if envelope.schema_id != TRIAL_RUN_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected virtual trial run schema: {envelope.schema_id!r}.")
        return VirtualTrialArtifactManifest.model_validate(envelope.payload)

    def verify_trial_run(
        self,
        trial_run_id: str,
        *,
        population_store: PopulationArtifactStore,
        allocation_store: TrialArmAllocationArtifactStore,
        endpoint_stores: Mapping[str, PkEndpointArtifactStore],
        comparison_store: ArmComparisonArtifactStore | None = None,
    ) -> VirtualTrialArtifactManifest:
        """Reload the record and re-verify every referenced sub-artifact's hash.

        This is the authoritative "was this the trial actually executed?"
        check: it never trusts the roll-up's own claims, only what each
        sub-artifact's own store independently re-verifies right now.
        """
        manifest = self.read_manifest(trial_run_id)

        population_manifest = population_store.verify_population(manifest.source_generation_id)
        if (
            population_manifest.individuals.semantic_content_sha256
            != manifest.source_population_semantic_sha256
        ):
            raise ValueError("OTTRIAL source population hash does not match its manifest.")

        allocation_manifest = allocation_store.verify_allocation(manifest.allocation_id)
        if (
            allocation_manifest.allocation.semantic_content_sha256
            != manifest.allocation_semantic_sha256
        ):
            raise ValueError("OTTRIAL allocation hash does not match its manifest.")
        if allocation_manifest.requested_seed != manifest.allocation_seed:
            raise ValueError("OTTRIAL allocation seed does not match its manifest.")

        for arm in manifest.arms:
            if arm.arm_id not in endpoint_stores:
                raise ValueError(f"No endpoint store supplied for arm {arm.arm_id!r}.")
            endpoint_manifest = endpoint_stores[arm.arm_id].verify_endpoints(arm.endpoint_id)
            if endpoint_manifest.endpoints.semantic_content_sha256 != arm.endpoint_semantic_sha256:
                raise ValueError(
                    f"OTTRIAL endpoint hash for arm {arm.arm_id!r} does not match its manifest."
                )

        if manifest.comparison_id is not None:
            if comparison_store is None:
                raise ValueError(
                    "OTTRIAL references a comparison but no comparison_store was given."
                )
            comparison_manifest = comparison_store.verify_comparison(manifest.comparison_id)
            arm_summary_hash = comparison_manifest.arm_summaries.semantic_content_sha256
            if (
                manifest.comparison_semantic_sha256 is not None
                and arm_summary_hash != manifest.comparison_semantic_sha256
            ):
                raise ValueError("OTTRIAL comparison hash does not match its manifest.")

        return manifest
