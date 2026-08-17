"""Immutable manifests for reproducible simulation runs."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrials.models.package import SHA256_PATTERN

RUN_ID_PATTERN = r"^OTR-[A-Za-z0-9_-]+$"


class RunStatus(StrEnum):
    """Lifecycle state of a simulation run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ModelRunReference(BaseModel):
    """The exact immutable model package consumed by a simulation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    package_hash: str = Field(pattern=SHA256_PATTERN)


class RunManifest(BaseModel):
    """The complete reproducibility record for one simulation attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    status: RunStatus
    trial_spec_hash: str = Field(pattern=SHA256_PATTERN)
    population_hash: str = Field(pattern=SHA256_PATTERN)
    models: tuple[ModelRunReference, ...] = Field(min_length=1)
    software_versions: dict[str, str] = Field(min_length=1)
    data_snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    seed: int
    solver_configuration: dict[str, Any] = Field(default_factory=dict)
    code_revision: str = Field(min_length=1)
    operating_environment: dict[str, str] = Field(min_length=1)
    started_at: datetime
    completed_at: datetime | None = None
    output_hashes: dict[str, str] = Field(default_factory=dict)
    logs_uri: str | None = None

    @field_validator("software_versions", "operating_environment")
    @classmethod
    def reject_blank_mapping_values(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not value.strip() for key, value in values.items()):
            raise ValueError("Manifest mapping keys and values cannot be blank.")
        return values

    @field_validator("data_snapshot_hashes", "output_hashes")
    @classmethod
    def validate_hash_mapping(cls, values: dict[str, str]) -> dict[str, str]:
        for name, content_hash in values.items():
            if not name.strip():
                raise ValueError("Artifact names cannot be blank.")
            if not re.fullmatch(SHA256_PATTERN, content_hash):
                raise ValueError("Artifact hashes must use the sha256:<hex> format.")
        return values

    @model_validator(mode="after")
    def validate_run_state(self) -> RunManifest:
        model_ids = tuple(reference.model_id for reference in self.models)
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("A run cannot reference a model ID more than once.")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Run completion time cannot precede start time.")
        if self.status in {RunStatus.SUCCEEDED, RunStatus.FAILED} and self.completed_at is None:
            raise ValueError("Terminal run statuses require a completion time.")
        if self.status is RunStatus.SUCCEEDED and not self.output_hashes:
            raise ValueError("Successful runs require output hashes.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for reproduction and integrity checks."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
