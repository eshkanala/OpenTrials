"""Contract tests for the researcher-facing Project entry point."""

from __future__ import annotations

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.config.project import ProjectConfig
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models.capability import (
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.models.registry import ModelCapabilityRegistry
from opentrials.patient import PopulationSpec
from opentrials.sdk.project import Project, dose_mg_for_model
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
)
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

HASH = "sha256:" + "a" * 64


def _second_profile() -> ModelCapabilityProfile:
    return ModelCapabilityProfile(
        package=ModelPackage(
            manifest=ModelManifest(
                id="test.second-model",
                version="1.0.0",
                model_type=ModelType.PBPK,
                engine="osp",
                inputs=("intervention",),
                outputs=("plasma_concentration",),
                units={"plasma_concentration": "umol/L"},
                applicability=Applicability(species=("human",)),
                license="test",
            ),
            artifact_uri="file:///tmp/second.pkml",
            artifact_hash=HASH,
            parameter_set_id="test",
            parameter_hash=HASH,
            package_hash=HASH,
        ),
        compounds=(CompoundCapability(compound_id="second", engine_molecule_id="Second"),),
        administrations=(
            AdministrationCapability(
                target_id="iv",
                compound_id="second",
                route=Route.INTRAVENOUS,
                administration_container_path="Events|IV|",
                dose_parameter_path="Events|IV|Dose",
                dose_unit="kg",
                administration_time_parameter_path="Events|IV|Start time",
                administration_time_unit="min",
                supported_dose_unit="mg",
            ),
        ),
        outputs=(
            OutputCapability(
                output_id="plasma",
                parameter_path="Organism|Plasma",
                analyte="second",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
                unit="umol/L",
                time_unit="min",
            ),
        ),
    )


def _assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def _arm(arm_id: str, dose_mg: float) -> TrialArm:
    intervention = Intervention(
        intervention_id=f"aciclovir-{arm_id}",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id=f"{arm_id}-regimen",
            doses=(
                Dose(
                    amount=_assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=_assumed(0, "min"),
                    infusion_duration=_assumed(10, "min"),
                ),
            ),
        ),
    )
    return TrialArm(arm_id=arm_id, name=arm_id, intervention=intervention, allocation=1.0)


def _trial(*arms: TrialArm, randomization: RandomizationType = RandomizationType.NONE) -> Trial:
    return Trial(
        trial_id="DEMO-TRIAL",
        title="Demo trial",
        question_of_interest="Does the dose matter?",
        population=PopulationSpec(
            id="demo-population", size=10, seed=1, generator_version="0.1.0"
        ),
        arms=arms,
        randomization=randomization,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=_assumed(0, "h"), end=_assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=1,
    )


def test_model_resolves_explicit_model_id() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    project = Project(
        ProjectConfig(model_id="osp.aciclovir.vergin-1995-iv", trial=_trial(_arm("a", 250.0))),
        registry=registry,
    )

    assert project.model().package.manifest.id == "osp.aciclovir.vergin-1995-iv"


def test_model_resolves_the_one_registered_profile_when_id_omitted() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    project = Project(ProjectConfig(trial=_trial(_arm("a", 250.0))), registry=registry)

    assert project.model().package.manifest.id == "osp.aciclovir.vergin-1995-iv"


def test_model_raises_when_registry_is_empty_and_id_omitted() -> None:
    project = Project(
        ProjectConfig(trial=_trial(_arm("a", 250.0))), registry=ModelCapabilityRegistry()
    )

    with pytest.raises(ValueError, match="does not declare model_id"):
        project.model()


def test_model_raises_when_registry_is_ambiguous_and_id_omitted() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    registry.register(_second_profile())
    project = Project(ProjectConfig(trial=_trial(_arm("a", 250.0))), registry=registry)

    with pytest.raises(ValueError, match="does not declare model_id"):
        project.model()


def test_dose_mg_for_model_passes_through_matching_unit() -> None:
    dose = _arm("a", 250.0).intervention.regimen.doses[0]
    assert dose_mg_for_model(dose, ACICLOVIR_IV_CAPABILITY_PROFILE) == pytest.approx(250.0)


def test_dose_mg_for_model_converts_from_a_different_unit() -> None:
    intervention = Intervention(
        intervention_id="aciclovir-grams",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="grams-regimen",
            doses=(
                Dose(
                    amount=_assumed(0.25, "g"),
                    route=Route.INTRAVENOUS,
                    administration_time=_assumed(0, "min"),
                ),
            ),
        ),
    )
    dose = intervention.regimen.doses[0]
    assert dose_mg_for_model(dose, ACICLOVIR_IV_CAPABILITY_PROFILE) == pytest.approx(250.0)
