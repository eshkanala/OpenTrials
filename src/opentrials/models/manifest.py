"""Versioned manifests that declare a computational model's contract."""

from __future__ import annotations

import json
from enum import StrEnum

from pint.errors import UndefinedUnitError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrials.core.exceptions import InvalidUnitError
from opentrials.core.units import unit_registry

SEMVER_PATTERN = (
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
MODEL_ID_PATTERN = r"^[a-z][a-z0-9_.-]*$"


class ModelType(StrEnum):
    """High-level categories used to discover and compose model packages."""

    PHYSIOLOGY = "PHYSIOLOGY"
    PBPK = "PBPK"
    PKPD = "PKPD"
    QSP = "QSP"
    DISEASE = "DISEASE"
    PATHWAY = "PATHWAY"
    TOXICITY = "TOXICITY"
    SURROGATE = "SURROGATE"


class Applicability(BaseModel):
    """The population and contexts for which a model may be appropriate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    species: tuple[str, ...] = Field(min_length=1)
    populations: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("species", "populations", "contexts", "limitations")
    @classmethod
    def reject_blank_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Applicability values cannot be blank.")
        return values


class ModelManifest(BaseModel):
    """Immutable declaration of a versioned model's interface and evidence context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0.0", pattern=SEMVER_PATTERN)
    id: str = Field(pattern=MODEL_ID_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    model_type: ModelType
    engine: str = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = Field(min_length=1)
    units: dict[str, str] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    applicability: Applicability
    validated_populations: tuple[str, ...] = ()
    not_validated: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    license: str = Field(min_length=1)

    @field_validator(
        "inputs", "outputs", "assumptions", "validated_populations", "not_validated", "evidence_ids"
    )
    @classmethod
    def reject_blank_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Manifest values cannot be blank.")
        return values

    @field_validator("units")
    @classmethod
    def validate_units(cls, values: dict[str, str]) -> dict[str, str]:
        for name, unit in values.items():
            if not name.strip():
                raise ValueError("Unit names cannot be blank.")
            try:
                unit_registry.Unit(unit)
            except UndefinedUnitError as error:
                raise InvalidUnitError(f"Unknown unit: {unit!r}") from error
        return values

    @model_validator(mode="after")
    def validate_interface(self) -> ModelManifest:
        if len(self.inputs) != len(set(self.inputs)):
            raise ValueError("Model manifest input names must be unique.")
        if len(self.outputs) != len(set(self.outputs)):
            raise ValueError("Model manifest output names must be unique.")
        missing_units = set(self.outputs).difference(self.units)
        if missing_units:
            raise ValueError(f"Model outputs require units: {sorted(missing_units)!r}.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for package identity and reproducibility."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
