"""Contract tests for the generic model capability profile schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opentrials.compound.intervention import Route
from opentrials.models.capability import (
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
    PhysiologyTargetCapability,
    UnsupportedCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage

HASH = "sha256:" + "a" * 64


def package() -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="test.model",
            version="1.0.0",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "umol/L"},
            applicability=Applicability(species=("human",)),
            license="test",
        ),
        artifact_uri="file:///tmp/test.pkml",
        artifact_hash=HASH,
        parameter_set_id="test",
        parameter_hash=HASH,
        package_hash=HASH,
    )


def administration() -> AdministrationCapability:
    return AdministrationCapability(
        target_id="iv",
        compound_id="test-compound",
        route=Route.INTRAVENOUS,
        administration_container_path="Events|IV|",
        dose_parameter_path="Events|IV|Dose",
        dose_unit="kg",
        administration_time_parameter_path="Events|IV|Start time",
        administration_time_unit="min",
    )


def output() -> OutputCapability:
    return OutputCapability(
        output_id="plasma",
        parameter_path="Organism|Plasma",
        analyte="test-compound",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
        unit="umol/L",
        time_unit="min",
    )


def test_profile_requires_at_least_one_compound_administration_and_output() -> None:
    with pytest.raises(ValidationError):
        ModelCapabilityProfile(
            package=package(),
            compounds=(),
            administrations=(administration(),),
            outputs=(output(),),
        )
    with pytest.raises(ValidationError):
        ModelCapabilityProfile(
            package=package(),
            compounds=(CompoundCapability(compound_id="c", engine_molecule_id="C"),),
            administrations=(),
            outputs=(output(),),
        )
    with pytest.raises(ValidationError):
        ModelCapabilityProfile(
            package=package(),
            compounds=(CompoundCapability(compound_id="c", engine_molecule_id="C"),),
            administrations=(administration(),),
            outputs=(),
        )


def test_profile_accepts_a_complete_declaration() -> None:
    profile = ModelCapabilityProfile(
        package=package(),
        compounds=(CompoundCapability(compound_id="c", engine_molecule_id="C"),),
        administrations=(administration(),),
        physiology_targets=(
            PhysiologyTargetCapability(
                target="renal.glomerular_filtration_rate",
                parameter_path="Organism|Kidney|GFRmat",
                unit="L/min",
                modeled=("renal.glomerular_filtration",),
                unmodeled=("renal.tubular_secretion",),
                interpretation="test coverage statement",
            ),
        ),
        outputs=(output(),),
        unsupported_capabilities=(
            UnsupportedCapability(capability="repeated_dosing", reason="test reason"),
        ),
    )
    assert profile.package.manifest.id == "test.model"
    assert profile.compounds[0].compound_id == "c"
    assert profile.physiology_targets[0].target == "renal.glomerular_filtration_rate"
    assert profile.unsupported_capabilities[0].capability == "repeated_dosing"


def test_physiology_target_requires_at_least_one_modeled_mechanism() -> None:
    with pytest.raises(ValidationError):
        PhysiologyTargetCapability(
            target="renal.glomerular_filtration_rate",
            parameter_path="Organism|Kidney|GFRmat",
            unit="L/min",
            modeled=(),
            interpretation="test",
        )


def test_unsupported_capability_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        UnsupportedCapability(capability="repeated_dosing", reason="")
