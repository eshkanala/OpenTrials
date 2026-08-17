"""Immutable persistence for declarative uncertainty-study scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.package import SHA256_PATTERN
from opentrials.uncertainty import UncertaintyScenario

UNCERTAINTY_SCENARIO_ID_PREFIX = "OTUSC-"
UNCERTAINTY_SCENARIO_ARTIFACT_SCHEMA = "opentrials.uncertainty-scenario-artifact"


class UncertaintyScenarioArtifactManifest(BaseModel):
    """Provenance and canonical identity for one immutable uncertainty definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    scenario_id: str = Field(pattern=r"^OTUSC-[A-Za-z0-9_-]+$")
    scenario: UncertaintyScenario
    scenario_canonical_sha256: str = Field(pattern=SHA256_PATTERN)


class UncertaintyScenarioArtifactStore:
    """Persist declarative uncertainty scenarios without materializing draws."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_uncertainty_scenario(self, scenario_id: str) -> Path:
        """Create the unique directory for an uncertainty scenario artifact."""
        if not scenario_id.startswith(UNCERTAINTY_SCENARIO_ID_PREFIX):
            raise ValueError(
                f"Uncertainty scenario IDs must begin with {UNCERTAINTY_SCENARIO_ID_PREFIX!r}."
            )
        directory = self.root / scenario_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def write_uncertainty_scenario(
        self, scenario: UncertaintyScenario, *, scenario_id: str | None = None
    ) -> UncertaintyScenarioArtifactManifest:
        """Write a complete declarative scenario exactly once."""
        artifact_id = scenario.scenario_id if scenario_id is None else scenario_id
        if artifact_id != scenario.scenario_id:
            raise ValueError("Artifact scenario ID must match UncertaintyScenario.scenario_id.")
        if not artifact_id.startswith(UNCERTAINTY_SCENARIO_ID_PREFIX):
            raise ValueError(
                f"Uncertainty scenario IDs must begin with {UNCERTAINTY_SCENARIO_ID_PREFIX!r}."
            )
        directory = self.root / artifact_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Uncertainty scenario directory does not exist: {artifact_id!r}."
            )
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(
                f"Uncertainty scenario artifact already exists for: {artifact_id!r}."
            )
        manifest = UncertaintyScenarioArtifactManifest(
            scenario_id=artifact_id,
            scenario=scenario,
            scenario_canonical_sha256=sha256(scenario),
        )
        manifest_path.write_text(
            document(UNCERTAINTY_SCENARIO_ARTIFACT_SCHEMA, manifest).canonical_json() + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(self, scenario_id: str) -> UncertaintyScenarioArtifactManifest:
        """Load and validate a schema-enveloped uncertainty scenario manifest."""
        path = self.root / scenario_id / "manifest.json"
        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            manifest_document = SchemaDocument.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid uncertainty scenario manifest: {path}") from error
        if manifest_document.schema_id != UNCERTAINTY_SCENARIO_ARTIFACT_SCHEMA:
            raise ValueError(
                f"Unexpected uncertainty scenario manifest schema: {manifest_document.schema_id!r}."
            )
        return UncertaintyScenarioArtifactManifest.model_validate(manifest_document.payload)

    def verify_uncertainty_scenario(self, scenario_id: str) -> UncertaintyScenarioArtifactManifest:
        """Verify directory identity and the scenario's canonical content hash."""
        manifest = self.read_manifest(scenario_id)
        if manifest.scenario_id != scenario_id:
            raise ValueError("Uncertainty scenario manifest ID does not match its directory ID.")
        if manifest.scenario.scenario_id != scenario_id:
            raise ValueError("Uncertainty scenario definition ID does not match its directory ID.")
        if sha256(manifest.scenario) != manifest.scenario_canonical_sha256:
            raise ValueError("Uncertainty scenario canonical hash does not match its manifest.")
        return manifest
