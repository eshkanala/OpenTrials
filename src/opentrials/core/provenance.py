"""Provenance records representing transformations in scientific workflows."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProvenanceActivityType(StrEnum):
    """Kinds of transformations that can connect scientific artifacts."""

    MEASUREMENT = "MEASUREMENT"
    TRANSFORMATION = "TRANSFORMATION"
    MODEL_EXECUTION = "MODEL_EXECUTION"
    SUMMARIZATION = "SUMMARIZATION"
    IMPORT = "IMPORT"


class ProvenanceRecord(BaseModel):
    """One directed transformation from input artifacts to an output artifact.

    Records form graph edges without requiring a graph-database dependency in
    Phase 0. Artifact identifiers may reference scientific values, evidence,
    models, runs, or future domain objects.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    activity_type: ProvenanceActivityType
    input_ids: tuple[str, ...] = Field(min_length=1)
    output_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    performed_at: datetime
    agent: str | None = None
    software_version: str | None = None
    assumptions: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()

    @field_validator("input_ids", "evidence_ids")
    @classmethod
    def reject_blank_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Identifiers cannot be blank.")
        return values

    @model_validator(mode="after")
    def validate_directed_edge(self) -> ProvenanceRecord:
        if len(self.input_ids) != len(set(self.input_ids)):
            raise ValueError("Provenance input IDs must be unique.")
        if self.output_id in self.input_ids:
            raise ValueError("A provenance output cannot also be one of its inputs.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for provenance snapshots and manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
