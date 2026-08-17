"""Population specifications and materialized synthetic populations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue
from opentrials.patient.patient import Patient, Sex


class AgeRange(BaseModel):
    """Inclusive age constraints expressed as unit-aware scientific values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: ScientificValue
    maximum: ScientificValue

    @model_validator(mode="after")
    def validate_range(self) -> AgeRange:
        try:
            minimum_years = self.minimum.to("year").value
            maximum_years = self.maximum.to("year").value
        except UnitCompatibilityError as error:
            raise ValueError("Population age bounds must have time dimensions.") from error
        if minimum_years < 0:
            raise ValueError("Population minimum age cannot be negative.")
        if minimum_years > maximum_years:
            raise ValueError("Population minimum age cannot exceed maximum age.")
        return self


class PopulationSpec(BaseModel):
    """Deterministic input specification for a future population generator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    size: int = Field(gt=0)
    seed: int
    generator_version: str = Field(min_length=1)
    age_range: AgeRange | None = None
    sexes: tuple[Sex, ...] = ()
    inclusion_criteria: tuple[str, ...] = ()
    enrichment: dict[str, int] = Field(default_factory=dict)
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_specification(self) -> PopulationSpec:
        if len(self.sexes) != len(set(self.sexes)):
            raise ValueError("Population sexes cannot contain duplicates.")
        if any(not criterion.strip() for criterion in self.inclusion_criteria):
            raise ValueError("Population inclusion criteria cannot be blank.")
        if any(not name.strip() or count <= 0 for name, count in self.enrichment.items()):
            raise ValueError("Population enrichment names must be nonblank and counts positive.")
        if sum(self.enrichment.values()) > self.size:
            raise ValueError("Population enrichment cannot exceed requested population size.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for population generation and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class Population(BaseModel):
    """A materialized, synthetic virtual population with generator provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    specification: PopulationSpec
    patients: tuple[Patient, ...]
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_population(self) -> Population:
        if self.id != self.specification.id:
            raise ValueError("Population ID must match its specification ID.")
        if len(self.patients) != self.specification.size:
            raise ValueError("Population must contain exactly the specified number of patients.")
        patient_ids = tuple(patient.identity.patient_id for patient in self.patients)
        if len(patient_ids) != len(set(patient_ids)):
            raise ValueError("Population patient IDs must be unique.")
        if any(patient.identity.population_id != self.id for patient in self.patients):
            raise ValueError("Every patient must reference its containing population ID.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for result storage and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
