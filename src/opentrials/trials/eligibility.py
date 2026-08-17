"""Machine-readable trial eligibility contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.scientific_value import ScientificValue


class EligibilityOperator(StrEnum):
    """Operators available to the Phase 0 machine-readable criteria language."""

    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    IN = "IN"
    NOT_IN = "NOT_IN"
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"


class EligibilityCriterion(BaseModel):
    """One structured inclusion or exclusion condition on patient state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    operator: EligibilityOperator
    value: ScientificValue | str | bool | tuple[str, ...] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_value_for_operator(self) -> EligibilityCriterion:
        numeric_operators = {
            EligibilityOperator.GREATER_THAN,
            EligibilityOperator.GREATER_THAN_OR_EQUAL,
            EligibilityOperator.LESS_THAN,
            EligibilityOperator.LESS_THAN_OR_EQUAL,
        }
        membership_operators = {EligibilityOperator.IN, EligibilityOperator.NOT_IN}
        boolean_operators = {EligibilityOperator.IS_TRUE, EligibilityOperator.IS_FALSE}

        if self.operator in numeric_operators and not isinstance(self.value, ScientificValue):
            raise ValueError("Numeric eligibility operators require a ScientificValue.")
        if self.operator in membership_operators:
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError(
                    "Membership eligibility operators require a nonempty tuple of strings."
                )
        if self.operator in boolean_operators and self.value is not None:
            raise ValueError("Boolean eligibility operators do not accept a comparison value.")
        if (
            self.operator in {EligibilityOperator.EQUALS, EligibilityOperator.NOT_EQUALS}
            and self.value is None
        ):
            raise ValueError("Equality eligibility operators require a comparison value.")
        return self


class Eligibility(BaseModel):
    """A complete set of executable inclusion and exclusion criteria."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inclusion: tuple[EligibilityCriterion, ...] = ()
    exclusion: tuple[EligibilityCriterion, ...] = ()
    narrative: str | None = None

    @model_validator(mode="after")
    def validate_unique_criteria(self) -> Eligibility:
        identifiers = tuple(criterion.criterion_id for criterion in self.inclusion + self.exclusion)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(
                "Eligibility criterion IDs must be unique across inclusion and exclusion."
            )
        return self
