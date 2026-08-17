"""Deterministic materialization of declared uncertainty scenarios."""

from __future__ import annotations

import random
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.distributions import DistributionType
from opentrials.core.serialization import sha256
from opentrials.uncertainty.contracts import SamplingMethod, UncertaintyScenario


class MaterializedParameterValue(BaseModel):
    """One sampled, solver-independent parameter assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)


class MaterializedUncertaintyDraw(BaseModel):
    """One deterministic draw from a declarative uncertainty scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draw_index: int = Field(ge=0)
    assignments: tuple[MaterializedParameterValue, ...] = Field(min_length=1)


class MaterializedUncertaintyDrawSet(BaseModel):
    """A hash-pinned collection of draws, ready for an engine-specific translator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(pattern=r"^OTUSC-[A-Za-z0-9_-]+$")
    scenario_canonical_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_seed: int = Field(ge=0)
    materializer_seed: int = Field(ge=0)
    method: SamplingMethod
    algorithm: str = "opentrials.independent-random-v1"
    draws: tuple[MaterializedUncertaintyDraw, ...] = Field(min_length=1)


def materialize_uncertainty_draws(scenario: UncertaintyScenario) -> MaterializedUncertaintyDrawSet:
    """Materialize independent draws deterministically from a scenario seed.

    Correlated sampling deliberately remains blocked until an explicit copula and
    rank-transform contract is implemented. ``RANGE`` is likewise blocked: it is
    an interval, not a probability distribution.
    """

    if scenario.correlations:
        raise ValueError("Correlated draw materialization requires a declared copula algorithm.")
    if scenario.sampling.method is not SamplingMethod.MONTE_CARLO:
        raise ValueError(
            "LATIN_HYPERCUBE materialization is not implemented by independent-random-v1."
        )
    generator = random.Random(scenario.sampling.requested_seed)
    draws = tuple(
        MaterializedUncertaintyDraw(
            draw_index=draw_index,
            assignments=tuple(
                MaterializedParameterValue(
                    parameter_id=parameter.parameter_id,
                    target=parameter.target,
                    value=_sample(
                        parameter.distribution.distribution_type,
                        parameter.distribution.parameters,
                        parameter.distribution.values,
                        generator,
                    ),
                    unit=parameter.distribution.unit,
                )
                for parameter in scenario.parameters
            ),
        )
        for draw_index in range(scenario.sampling.requested_draw_count)
    )
    return MaterializedUncertaintyDrawSet(
        scenario_id=scenario.scenario_id,
        scenario_canonical_sha256=sha256(scenario),
        requested_seed=scenario.sampling.requested_seed,
        materializer_seed=scenario.sampling.requested_seed,
        method=scenario.sampling.method,
        draws=draws,
    )


def _sample(
    distribution_type: DistributionType,
    parameters: dict[str, float],
    values: Sequence[float],
    generator: random.Random,
) -> float:
    if distribution_type is DistributionType.POINT:
        return parameters["value"]
    if distribution_type is DistributionType.NORMAL:
        return generator.normalvariate(parameters["mean"], parameters["standard_deviation"])
    if distribution_type is DistributionType.LOG_NORMAL:
        return generator.lognormvariate(
            parameters["log_mean"], parameters["log_standard_deviation"]
        )
    if distribution_type is DistributionType.UNIFORM:
        return generator.uniform(parameters["lower"], parameters["upper"])
    if distribution_type is DistributionType.EMPIRICAL:
        return generator.choice(values)
    if distribution_type is DistributionType.RANGE:
        raise ValueError("RANGE cannot be sampled without a declared probability semantics.")
    raise AssertionError(f"Unsupported distribution type: {distribution_type!r}")
