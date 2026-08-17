"""Canonical observed pharmacokinetic data contracts."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opentrials.compound.intervention import Intervention
from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue
from opentrials.validation.study import DatasetRole


class ObservedStudy(BaseModel):
    """The study context and intervention for observed data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    population_description: str = Field(min_length=1)
    intervention: Intervention
    study_limitations: str | None = None
    assay_context: str | None = None

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not evidence_id for evidence_id in value):
            raise ValueError("Observed-study evidence IDs must be nonempty.")
        if len(value) != len(set(value)):
            raise ValueError("Observed-study evidence IDs must be unique.")
        return value

    def canonical_json(self) -> str:
        """Serialize deterministically for reproducibility manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class ObservedPkObservation(BaseModel):
    """One observed pharmacokinetic measurement in a declared assay context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1)
    subject_or_population_id: str = Field(min_length=1)
    time: ScientificValue
    value: ScientificValue
    analyte: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    assay: str | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    condition: str | None = None

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not evidence_id for evidence_id in value):
            raise ValueError("Observed-PK-observation evidence IDs must be nonempty.")
        if len(value) != len(set(value)):
            raise ValueError("Observed-PK-observation evidence IDs must be unique.")
        return value

    @model_validator(mode="after")
    def validate_time_dimensions(self) -> ObservedPkObservation:
        try:
            self.time.to("second")
        except UnitCompatibilityError as error:
            raise ValueError("Observed PK observation time must have time dimensions.") from error
        return self


class ObservedDataset(BaseModel):
    """An immutable observed-data collection with its intended dataset role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1)
    role: DatasetRole
    study: ObservedStudy
    observations: tuple[ObservedPkObservation, ...] = Field(min_length=1)
    license: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not provenance_id for provenance_id in value):
            raise ValueError("Observed-dataset provenance IDs must be nonempty.")
        if len(value) != len(set(value)):
            raise ValueError("Observed-dataset provenance IDs must be unique.")
        return value

    @model_validator(mode="after")
    def validate_observation_ids(self) -> ObservedDataset:
        observation_ids = tuple(observation.observation_id for observation in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("Observed-dataset observation IDs must be unique.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for reproducibility manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
