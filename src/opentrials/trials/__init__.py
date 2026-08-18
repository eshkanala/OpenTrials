"""Virtual-trial protocol domain schemas."""

from opentrials.trials.allocation import (
    APPORTIONMENT_METHOD,
    ArmAllocationEntry,
    ArmAllocationResult,
    allocate_population_to_arms,
)
from opentrials.trials.eligibility import Eligibility, EligibilityCriterion, EligibilityOperator
from opentrials.trials.endpoints import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
)
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

__all__ = [
    "APPORTIONMENT_METHOD",
    "ArmAllocationEntry",
    "ArmAllocationResult",
    "Eligibility",
    "EligibilityCriterion",
    "EligibilityOperator",
    "Endpoint",
    "EndpointAggregation",
    "EndpointType",
    "MissingnessRule",
    "RandomizationType",
    "TimeWindow",
    "Trial",
    "TrialArm",
    "allocate_population_to_arms",
]
