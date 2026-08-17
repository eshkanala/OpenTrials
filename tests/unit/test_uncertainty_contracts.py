from pathlib import Path

import pytest
from pydantic import ValidationError

from opentrials.core import Distribution, DistributionPurpose, DistributionType
from opentrials.storage.uncertainty import UncertaintyScenarioArtifactStore
from opentrials.uncertainty import (
    CorrelationGroup,
    SamplingMethod,
    UncertainParameter,
    UncertaintySamplingPlan,
    UncertaintyScenario,
)

MODEL_HASH = "sha256:" + "a" * 64


def parameter(parameter_id: str, target: str) -> UncertainParameter:
    return UncertainParameter(
        parameter_id=parameter_id,
        target=target,
        distribution=Distribution(
            distribution_type=DistributionType.NORMAL,
            purpose=DistributionPurpose.PARAMETER_UNCERTAINTY,
            unit="L/hour",
            parameters={"mean": 3.0, "standard_deviation": 0.5},
        ),
        evidence_ids=(f"evidence-{parameter_id}",),
        provenance_ids=(f"provenance-{parameter_id}",),
    )


def scenario() -> UncertaintyScenario:
    return UncertaintyScenario(
        scenario_id="OTUSC-clearance-001",
        target_model_sha256=MODEL_HASH,
        parameters=(
            parameter("clearance", "compound.clearance"),
            parameter("renal_clearance", "compound.renal_clearance"),
        ),
        correlations=(
            CorrelationGroup(
                group_id="clearance-correlation",
                parameter_ids=("clearance", "renal_clearance"),
                matrix=((1.0, 0.4), (0.4, 1.0)),
            ),
        ),
        sampling=UncertaintySamplingPlan(
            method=SamplingMethod.LATIN_HYPERCUBE,
            requested_draw_count=1000,
            requested_seed=42,
        ),
        evidence_ids=("evidence-scenario",),
        provenance_ids=("provenance-scenario",),
        assumptions=("Parameter uncertainty is independent of population variability.",),
    )


def test_uncertainty_scenario_is_declarative_and_deterministic() -> None:
    first = scenario()
    second = scenario()

    assert first == second
    assert first.sampling.requested_seed == 42
    assert first.parameters[0].distribution.purpose is DistributionPurpose.PARAMETER_UNCERTAINTY


def test_uncertain_parameter_rejects_population_variability_distribution() -> None:
    with pytest.raises(ValidationError, match="PARAMETER_UNCERTAINTY"):
        UncertainParameter(
            parameter_id="weight",
            target="organism.weight",
            distribution=Distribution(
                distribution_type=DistributionType.NORMAL,
                purpose=DistributionPurpose.POPULATION_VARIABILITY,
                unit="kg",
                parameters={"mean": 70.0, "standard_deviation": 10.0},
            ),
            evidence_ids=("evidence-weight",),
            provenance_ids=("provenance-weight",),
        )


def test_correlation_group_rejects_non_positive_semidefinite_matrix() -> None:
    with pytest.raises(ValidationError, match="positive semidefinite"):
        CorrelationGroup(
            group_id="invalid",
            parameter_ids=("a", "b", "c"),
            matrix=((1.0, 0.9, 0.9), (0.9, 1.0, -0.9), (0.9, -0.9, 1.0)),
        )


def test_scenario_rejects_unknown_or_overlapping_correlation_parameters() -> None:
    payload = scenario().model_dump()
    payload["correlations"] = (
        CorrelationGroup(
            group_id="unknown",
            parameter_ids=("clearance", "unknown"),
            matrix=((1.0, 0.2), (0.2, 1.0)),
        ),
    )

    with pytest.raises(ValidationError, match="unknown uncertain parameters"):
        UncertaintyScenario(**payload)


def test_uncertainty_scenario_artifact_is_immutable_and_verifiable(tmp_path: Path) -> None:
    store = UncertaintyScenarioArtifactStore(tmp_path / "uncertainty")
    directory = store.create_uncertainty_scenario("OTUSC-clearance-001")
    manifest = store.write_uncertainty_scenario(scenario())

    assert store.verify_uncertainty_scenario("OTUSC-clearance-001") == manifest
    assert manifest.scenario_canonical_sha256.startswith("sha256:")
    assert (
        '"schema":"opentrials.uncertainty-scenario-artifact"'
        in (directory / "manifest.json").read_text()
    )
    with pytest.raises(FileExistsError, match="already exists"):
        store.write_uncertainty_scenario(scenario())
