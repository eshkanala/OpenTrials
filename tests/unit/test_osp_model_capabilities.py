from __future__ import annotations

import pytest

from opentrials.adapters.osp import (
    OspAdministrationTarget,
    OspCompoundMapping,
    OspModelCapabilityChecker,
    OspModelCapabilityProfile,
)
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def aciclovir_intervention(route: Route) -> Intervention:
    return Intervention(
        intervention_id="aciclovir-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="aciclovir-regimen",
            doses=(
                Dose(amount=assumed(400, "mg"), route=route, administration_time=assumed(0, "h")),
            ),
        ),
    )


def model_package() -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="osp.aciclovir.iv.vergin-1995",
            version="1.0.0",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "micromole / liter"},
            applicability=Applicability(species=("human",)),
            license="upstream license pending verification",
        ),
        artifact_uri="file:///models/Aciclovir.pkml",
        artifact_hash="sha256:" + "a" * 64,
        parameter_set_id="vergin-1995-iv",
        parameter_hash="sha256:" + "b" * 64,
        package_hash="sha256:" + "c" * 64,
    )


def iv_profile() -> OspModelCapabilityProfile:
    return OspModelCapabilityProfile(
        model_package=model_package(),
        osp_simulation_name="Vergin 1995 IV",
        compound_mappings=(
            OspCompoundMapping(opentrials_compound_id="aciclovir", osp_molecule_id="Aciclovir"),
        ),
        administration_targets=(
            OspAdministrationTarget(
                target_id="iv-250mg-10min",
                osp_molecule_id="Aciclovir",
                route=Route.INTRAVENOUS,
                dose_parameter_path="Events|IV 250mg 10min|Application_1|ProtocolSchemaItem|Dose",
                dose_unit="mg",
                administration_time_parameter_path=(
                    "Events|IV 250mg 10min|Application_1|ProtocolSchemaItem|Start time"
                ),
                administration_time_unit="h",
            ),
        ),
    )


def test_profile_without_verified_administration_target_cannot_become_an_execution_profile() -> (
    None
):
    profile = iv_profile().model_copy(update={"administration_targets": ()})

    with pytest.raises(ValueError, match="No verified OSP administration target"):
        profile.intervention_profile()


def test_capability_report_rejects_oral_trial_for_verified_iv_only_model() -> None:
    report = OspModelCapabilityChecker().assess(iv_profile(), aciclovir_intervention(Route.ORAL))

    assert report.model_id == "osp.aciclovir.iv.vergin-1995"
    assert report.osp_simulation_name == "Vergin 1995 IV"
    assert not report.is_executable
    assert tuple(item.requested_feature for item in report.unsupported) == (
        "route",
        "dose_type",
        "administration_time",
    )
    assert "ORAL" in report.unsupported[0].detail


def test_capability_report_accepts_a_matching_inspected_iv_single_dose_target() -> None:
    report = OspModelCapabilityChecker().assess(
        iv_profile(), aciclovir_intervention(Route.INTRAVENOUS)
    )

    assert report.is_executable
    assert tuple(item.requested_feature for item in report.supported) == (
        "compound",
        "route",
        "dose_type",
        "administration_time",
    )
    assert report.supported[-1].model_feature.endswith("Start time")
