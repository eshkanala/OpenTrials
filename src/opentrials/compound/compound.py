"""Compound identity and Phase 0 scientific property schemas."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opentrials.core.scientific_value import ScientificValue


class CompoundIdentity(BaseModel):
    """Stable molecular identity with interoperable chemical identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compound_id: str = Field(min_length=1)
    preferred_name: str = Field(min_length=1)
    synonyms: tuple[str, ...] = ()
    canonical_smiles: str | None = None
    isomeric_smiles: str | None = None
    inchi: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    external_identifiers: dict[str, str] = Field(default_factory=dict)

    @field_validator("synonyms")
    @classmethod
    def reject_blank_synonyms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Compound synonyms cannot be blank.")
        return values

    @field_validator("external_identifiers")
    @classmethod
    def reject_blank_external_identifiers(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            not source.strip() or not identifier.strip() for source, identifier in values.items()
        ):
            raise ValueError("External identifier sources and values cannot be blank.")
        return values


class Compound(BaseModel):
    """A known compound and evidence-linked Phase 0 molecular properties."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: CompoundIdentity
    molecular_weight: ScientificValue | None = None
    physicochemical_properties: dict[str, ScientificValue] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    def canonical_json(self) -> str:
        """Serialize deterministically for model, trial, and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
