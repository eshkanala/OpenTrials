import pytest

from opentrials.core import Distribution, DistributionPurpose, DistributionType
from opentrials.uncertainty import (
    CorrelationGroup,
    SamplingMethod,
    UncertainParameter,
    UncertaintySamplingPlan,
    UncertaintyScenario,
)
from opentrials.uncertainty.execution import materialize_uncertainty_draws

HASH = "sha256:" + "b" * 64


def scenario(*, correlated: bool = False) -> UncertaintyScenario:
    parameter = UncertainParameter(
        parameter_id="dose",
        target="intervention.aciclovir_iv.dose",
        distribution=Distribution(
            distribution_type=DistributionType.EMPIRICAL,
            purpose=DistributionPurpose.PARAMETER_UNCERTAINTY,
            unit="mg",
            values=(125.0, 250.0),
        ),
        evidence_ids=("evidence-dose",),
        provenance_ids=("provenance-dose",),
    )
    return UncertaintyScenario(
        scenario_id="OTUSC-dose-001",
        target_model_sha256=HASH,
        parameters=(parameter,),
        correlations=(
            CorrelationGroup(
                group_id="not-executable",
                parameter_ids=("dose", "other"),
                matrix=((1.0, 0.0), (0.0, 1.0)),
            ),
        )
        if correlated
        else (),
        sampling=UncertaintySamplingPlan(
            method=SamplingMethod.MONTE_CARLO, requested_draw_count=4, requested_seed=42
        ),
        evidence_ids=("evidence-scenario",),
        provenance_ids=("provenance-scenario",),
    )


def test_materialized_draws_are_deterministic_and_hash_pinned() -> None:
    first = materialize_uncertainty_draws(scenario())
    second = materialize_uncertainty_draws(scenario())

    assert first == second
    assert first.materializer_seed == 42
    assert len(first.draws) == 4
    assert {draw.assignments[0].value for draw in first.draws} <= {125.0, 250.0}
    assert first.scenario_canonical_sha256.startswith("sha256:")


def test_materialization_blocks_unimplemented_correlation_execution() -> None:
    with pytest.raises(ValueError, match="unknown uncertain parameters"):
        materialize_uncertainty_draws(scenario(correlated=True))


def test_materialization_blocks_range_without_probability_semantics() -> None:
    base = scenario().model_dump()
    base["parameters"] = (
        UncertainParameter(
            parameter_id="range",
            target="intervention.aciclovir_iv.dose",
            distribution=Distribution(
                distribution_type=DistributionType.RANGE,
                purpose=DistributionPurpose.PARAMETER_UNCERTAINTY,
                unit="mg",
                parameters={"lower": 125.0, "upper": 250.0},
            ),
            evidence_ids=("evidence-range",),
            provenance_ids=("provenance-range",),
        ),
    )
    with pytest.raises(ValueError, match="RANGE"):
        materialize_uncertainty_draws(UncertaintyScenario(**base))
