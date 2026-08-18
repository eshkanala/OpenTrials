"""The immutable, authoritative provenance record for one executed physiology trial.

``OTPHYTRIAL`` mirrors ``OTTRIAL`` (see ``storage.trial_run``) but for a
prospective physiological-state comparison rather than a multi-arm trial:
one source population, executed unchanged, at N>=2 declared physiological
states sharing the same intervention/dose/route/schedule. Like OTTRIAL it
computes nothing itself -- every field is a hash/id already produced by
another store -- and ``verify_physiology_trial()`` re-verifies every
referenced sub-artifact from its own store rather than trusting the
roll-up's own claims.
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
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.physiology import PhysiologyPopulationArtifactStore
from opentrials.storage.physiology_comparison import PhysiologyComparisonArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.trial_run import ObservationScheduleRecord

PHYSIOLOGY_TRIAL_ID_PATTERN = r"^OTPHYTRIAL-[A-Za-z0-9_-]+$"
PHYSIOLOGY_TRIAL_ARTIFACT_SCHEMA = "opentrials.physiology-trial-run-artifact"


class PhysiologyStateRunRecord(BaseModel):
    """Complete provenance for one declared physiological state's OSP run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_id: str = Field(min_length=1)
    physiology_population_id: str = Field(pattern=r"^OTPHYS-[A-Za-z0-9_-]+$")
    physiology_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    override_target: str = Field(min_length=1)
    override_scale_factor: float = Field(gt=0)
    executed_run_id: str = Field(min_length=1)
    raw_response_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_verification_sha256: str = Field(pattern=SHA256_PATTERN)
    physiology_state_verified: bool
    observation_schedule_verified: bool | None = None
    result_id: str = Field(pattern=r"^OTRES-[A-Za-z0-9_-]+$")
    result_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)


class PhysiologyTrialArtifactManifest(BaseModel):
    """The complete, immutable, reconstructible provenance record of one physiology trial."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    trial_run_id: str = Field(pattern=PHYSIOLOGY_TRIAL_ID_PATTERN)
    trial_id: str = Field(min_length=1)
    trial_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    model_id: str = Field(min_length=1)
    model_sha256: str = Field(pattern=SHA256_PATTERN)
    observation_schedule: ObservationScheduleRecord | None = None
    baseline_state_id: str = Field(min_length=1)
    states: tuple[PhysiologyStateRunRecord, ...] = Field(min_length=2)
    comparison_id: str = Field(pattern=r"^OTPHYCMP-[A-Za-z0-9_-]+$")
    comparison_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    software_versions: dict[str, str]
    created_at: datetime


class PhysiologyTrialArtifactStore:
    """Persist and reload the immutable OTPHYTRIAL provenance record."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_trial_run(self, trial_run_id: str) -> Path:
        if not trial_run_id.startswith("OTPHYTRIAL-"):
            raise ValueError("Physiology trial run IDs must begin with 'OTPHYTRIAL-'.")
        directory = self.root / trial_run_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_trial_run(
        self, trial_run_id: str, manifest: PhysiologyTrialArtifactManifest
    ) -> PhysiologyTrialArtifactManifest:
        """Persist an already-assembled, already-verified trial-run record exactly once."""
        directory = self.root / trial_run_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Physiology trial directory does not exist: {trial_run_id!r}."
            )
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(
                f"Physiology trial artifact already exists for: {trial_run_id!r}."
            )
        if manifest.trial_run_id != trial_run_id:
            raise ValueError("Manifest trial_run_id does not match the target directory.")
        manifest_path.write_text(
            document(PHYSIOLOGY_TRIAL_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, trial_run_id: str) -> PhysiologyTrialArtifactManifest:
        path = self.root / trial_run_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            envelope = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid physiology trial run manifest: {path}") from error
        if envelope.schema_id != PHYSIOLOGY_TRIAL_ARTIFACT_SCHEMA:
            raise ValueError(f"Unexpected physiology trial run schema: {envelope.schema_id!r}.")
        return PhysiologyTrialArtifactManifest.model_validate(envelope.payload)

    def verify_physiology_trial(
        self,
        trial_run_id: str,
        *,
        population_store: PopulationArtifactStore,
        physiology_store: PhysiologyPopulationArtifactStore,
        endpoint_stores: Mapping[str, PkEndpointArtifactStore],
        comparison_store: PhysiologyComparisonArtifactStore,
    ) -> PhysiologyTrialArtifactManifest:
        """Reload the record and re-verify every referenced sub-artifact's hash.

        This never trusts the roll-up's own claims, only what each
        sub-artifact's own store independently re-verifies right now.
        """
        manifest = self.read_manifest(trial_run_id)

        population_manifest = population_store.verify_population(manifest.source_generation_id)
        if (
            population_manifest.individuals.semantic_content_sha256
            != manifest.source_population_semantic_sha256
        ):
            raise ValueError("OTPHYTRIAL source population hash does not match its manifest.")

        for state in manifest.states:
            physiology_manifest = physiology_store.verify_physiology_population(
                state.physiology_population_id
            )
            if (
                physiology_manifest.individuals.semantic_content_sha256
                != state.physiology_population_semantic_sha256
            ):
                raise ValueError(
                    f"OTPHYTRIAL physiology-population hash for state {state.state_id!r} does "
                    "not match its manifest."
                )
            if state.state_id not in endpoint_stores:
                raise ValueError(f"No endpoint store supplied for state {state.state_id!r}.")
            endpoint_manifest = endpoint_stores[state.state_id].verify_endpoints(
                state.endpoint_id
            )
            if (
                endpoint_manifest.endpoints.semantic_content_sha256
                != state.endpoint_semantic_sha256
            ):
                raise ValueError(
                    f"OTPHYTRIAL endpoint hash for state {state.state_id!r} does not match its "
                    "manifest."
                )

        comparison_manifest = comparison_store.verify_comparison(manifest.comparison_id)
        if (
            comparison_manifest.state_summaries.semantic_content_sha256
            != manifest.comparison_semantic_sha256
        ):
            raise ValueError("OTPHYTRIAL comparison hash does not match its manifest.")

        return manifest
