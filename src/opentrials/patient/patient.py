"""Synthetic virtual-patient domain schemas."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue


class Sex(StrEnum):
    """A biological sex field, kept distinct from social identity categories."""

    FEMALE = "FEMALE"
    MALE = "MALE"
    INTERSEX = "INTERSEX"
    UNSPECIFIED = "UNSPECIFIED"


class PatientIdentity(BaseModel):
    """Synthetic identity and generator provenance for a virtual patient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: str = Field(min_length=1)
    population_id: str = Field(min_length=1)
    generation_seed: int
    generator_version: str = Field(min_length=1)
    created_at: datetime
    is_synthetic: Literal[True] = True


class Demographics(BaseModel):
    """Core demographic characteristics relevant to a virtual patient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    age: ScientificValue
    sex: Sex = Sex.UNSPECIFIED
    pregnancy_state: str | None = None
    gestational_age: ScientificValue | None = None
    postnatal_age: ScientificValue | None = None

    @model_validator(mode="after")
    def validate_time_dimensions(self) -> Demographics:
        for name, value in {
            "age": self.age,
            "gestational_age": self.gestational_age,
            "postnatal_age": self.postnatal_age,
        }.items():
            if value is None:
                continue
            try:
                years = value.to("year").value
            except UnitCompatibilityError as error:
                raise ValueError(f"{name} must have time dimensions.") from error
            if years < 0:
                raise ValueError(f"{name} cannot be negative.")
        return self


class Anthropometrics(BaseModel):
    """Unit-aware anthropometric state for a virtual patient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    height: ScientificValue | None = None
    weight: ScientificValue | None = None
    body_mass_index: ScientificValue | None = None
    body_surface_area: ScientificValue | None = None
    lean_body_mass: ScientificValue | None = None
    fat_mass: ScientificValue | None = None
    body_fat_percentage: ScientificValue | None = None

    @model_validator(mode="after")
    def validate_dimensions(self) -> Anthropometrics:
        expected_units = {
            "height": "meter",
            "weight": "kilogram",
            "body_mass_index": "kilogram / meter**2",
            "body_surface_area": "meter**2",
            "lean_body_mass": "kilogram",
            "fat_mass": "kilogram",
            "body_fat_percentage": "percent",
        }
        for name, target_unit in expected_units.items():
            value = getattr(self, name)
            if value is None:
                continue
            try:
                converted_value = value.to(target_unit).value
            except UnitCompatibilityError as error:
                raise ValueError(f"{name} has incompatible dimensions.") from error
            if converted_value < 0:
                raise ValueError(f"{name} cannot be negative.")
        return self


class Patient(BaseModel):
    """A synthetic virtual patient and its static Phase 0 scientific state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: PatientIdentity
    demographics: Demographics
    anthropometrics: Anthropometrics = Field(default_factory=Anthropometrics)
    physiology: dict[str, ScientificValue] = Field(default_factory=dict)
    laboratory_values: dict[str, ScientificValue] = Field(default_factory=dict)
    pharmacogenomic_phenotypes: dict[str, str] = Field(default_factory=dict)
    disease_state_ids: tuple[str, ...] = ()
    medication_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    def canonical_json(self) -> str:
        """Serialize deterministically for population hashes and manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
