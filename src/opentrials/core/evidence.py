"""Evidence records and collections for scientific provenance."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.distributions import Distribution
from opentrials.core.scientific_value import ScientificValue


class EvidenceSourceType(StrEnum):
    """Kinds of sources from which an evidence record can originate."""

    PEER_REVIEWED_ARTICLE = "PEER_REVIEWED_ARTICLE"
    CLINICAL_TRIAL = "CLINICAL_TRIAL"
    ASSAY_DATABASE = "ASSAY_DATABASE"
    REGULATORY_DOCUMENT = "REGULATORY_DOCUMENT"
    PUBLIC_DATASET = "PUBLIC_DATASET"
    MODEL_DERIVED_RESULT = "MODEL_DERIVED_RESULT"
    EXPERT_ASSUMPTION = "EXPERT_ASSUMPTION"
    COMPUTATIONAL_PREDICTION = "COMPUTATIONAL_PREDICTION"


class Evidence(BaseModel):
    """A citable scientific observation, assumption, or computational result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    source_type: EvidenceSourceType
    source_identifier: str = Field(min_length=1)
    citation: str | None = None
    dataset_id: str | None = None
    experimental_method: str | None = None
    species: str | None = None
    population: str | None = None
    tissue: str | None = None
    biological_context: str | None = None
    assay: str | None = None
    sample_size: int | None = Field(default=None, gt=0)
    measured_quantity: str | None = None
    result: ScientificValue | None = None
    uncertainty: Distribution | None = None
    quality_metadata: dict[str, Any] = Field(default_factory=dict)
    license: str | None = None
    retrieval_version: str | None = None
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_result_context(self) -> Evidence:
        if self.uncertainty is not None and self.result is None:
            raise ValueError("Uncertainty requires a corresponding result.")
        if self.result is not None and self.uncertainty is not None:
            if self.result.unit != self.uncertainty.unit:
                raise ValueError("Evidence result and uncertainty must use the same unit.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for snapshots and reproducibility."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class EvidenceSet(BaseModel):
    """An immutable, de-duplicated collection of evidence records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids(self) -> EvidenceSet:
        ids = tuple(record.id for record in self.evidence)
        if len(ids) != len(set(ids)):
            raise ValueError("EvidenceSet cannot contain duplicate evidence IDs.")
        return self

    def by_id(self, evidence_id: str) -> Evidence | None:
        """Return an evidence record by ID, if this set contains it."""
        return next((record for record in self.evidence if record.id == evidence_id), None)
