"""Serializable scientific assumptions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AssumptionScope(StrEnum):
    MODEL = "MODEL"
    RUN = "RUN"
    TRIAL = "TRIAL"
    POPULATION = "POPULATION"


class Assumption(BaseModel):
    """An explicit, queryable scientific assumption with rationale and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assumption_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    scope: AssumptionScope
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    uncertainty_impact: str | None = None
