"""Canonical observed measurement records."""

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.scientific_value import ScientificValue


class Observation(BaseModel):
    """One measured variable at a time in a declared biological context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1)
    subject_or_population_id: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    value: ScientificValue
    time: ScientificValue
    condition: str | None = None
    evidence_id: str = Field(min_length=1)
