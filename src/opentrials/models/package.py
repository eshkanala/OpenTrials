"""A pinned, installable model package description."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from opentrials.models.manifest import ModelManifest

SHA256_PATTERN = r"^sha256:[a-f0-9]{64}$"


class ModelPackage(BaseModel):
    """A model manifest plus immutable references to its executable artifacts.

    Artifact acquisition and execution are adapter responsibilities. This
    schema only identifies exactly which package content a run consumed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ModelManifest
    artifact_uri: str = Field(min_length=1)
    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    parameter_set_id: str = Field(min_length=1)
    parameter_hash: str = Field(pattern=SHA256_PATTERN)
    package_hash: str = Field(pattern=SHA256_PATTERN)
    changelog_uri: str | None = None

    def canonical_json(self) -> str:
        """Serialize deterministically for registry and run-manifest references."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
