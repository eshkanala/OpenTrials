"""Virtual-trial protocol and trial-arm schemas."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.compound.intervention import Intervention
from opentrials.patient.population import PopulationSpec
from opentrials.trials.eligibility import Eligibility
from opentrials.trials.endpoints import Endpoint
from opentrials.trials.schedule import ObservationSchedule


class RandomizationType(StrEnum):
    """Phase 0 trial allocation designs."""

    NONE = "NONE"
    PARALLEL = "PARALLEL"


class TrialArm(BaseModel):
    """One trial arm with a compound intervention and population allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    intervention: Intervention
    allocation: float = Field(gt=0, le=1)
    description: str | None = None


class Trial(BaseModel):
    """An immutable, reproducible virtual-trial protocol definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    question_of_interest: str = Field(min_length=1)
    population: PopulationSpec
    eligibility: Eligibility = Field(default_factory=Eligibility)
    arms: tuple[TrialArm, ...] = Field(min_length=1)
    randomization: RandomizationType
    endpoints: tuple[Endpoint, ...] = Field(min_length=1)
    seed: int
    observation_schedule: ObservationSchedule | None = Field(
        default=None,
        description=(
            "The trial's declared sample-collection timeline, distinct from dosing "
            "timing (see trials.schedule). Currently only honored for multi-arm "
            "(two or more declared arms) execution -- see sdk.project.Project.run."
        ),
    )
    analysis_plan: str | None = None
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_protocol(self) -> Trial:
        arm_ids = tuple(arm.arm_id for arm in self.arms)
        endpoint_ids = tuple(endpoint.endpoint_id for endpoint in self.endpoints)
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("Trial arm IDs must be unique.")
        if len(endpoint_ids) != len(set(endpoint_ids)):
            raise ValueError("Trial endpoint IDs must be unique.")
        if self.randomization is RandomizationType.NONE and len(self.arms) != 1:
            raise ValueError("Non-randomized trials must contain exactly one arm.")
        if self.randomization is RandomizationType.PARALLEL:
            if len(self.arms) < 2:
                raise ValueError("Parallel-randomized trials require at least two arms.")
            total_allocation = sum(arm.allocation for arm in self.arms)
            if abs(total_allocation - 1.0) > 1e-9:
                raise ValueError("Parallel trial arm allocations must sum to one.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for trial and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
