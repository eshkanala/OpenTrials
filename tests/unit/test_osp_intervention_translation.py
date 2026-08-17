from __future__ import annotations

import pytest
from pydantic import ValidationError

from opentrials.adapters.osp import (
    InterventionTranslationError,
    OspAdministrationTarget,
    OspCompoundMapping,
    OspInterventionProfile,
    OspInterventionTranslator,
)
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def intervention(
    *, compound_id: str = "aciclovir", route: Route = Route.ORAL, dose_count: int = 1
) -> Intervention:
    doses = tuple(
        Dose(
            amount=assumed(400, "mg"),
            route=route,
            administration_time=assumed(index, "hour"),
        )
        for index in range(dose_count)
    )
    return Intervention(
        intervention_id="aciclovir-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id=compound_id, preferred_name="Aciclovir")
        ),
        regimen=Regimen(regimen_id="aciclovir-regimen", doses=doses),
    )


def profile(*, route: Route = Route.ORAL) -> OspInterventionProfile:
    return OspInterventionProfile(
        compound_mappings=(
            OspCompoundMapping(opentrials_compound_id="aciclovir", osp_molecule_id="Aciclovir"),
        ),
        administration_targets=(
            OspAdministrationTarget(
                target_id="aciclovir-oral-administration",
                osp_molecule_id="Aciclovir",
                route=route,
                dose_parameter_path="Events|Aciclovir|Dose",
                dose_unit="mg",
                administration_time_parameter_path="Events|Aciclovir|StartTime",
                administration_time_unit="minute",
            ),
        ),
    )


def test_translator_builds_an_explicit_single_dose_plan() -> None:
    translation = OspInterventionTranslator(profile()).translate(intervention())

    assert translation.plan is not None
    assert translation.plan.requested_route is Route.ORAL
    assert translation.plan.executable_route is Route.ORAL
    assert translation.plan.osp_molecule_id == "Aciclovir"
    assert translation.plan.assignments[0].value == 400
    assert translation.plan.assignments[0].unit == "mg"
    assert translation.plan.assignments[1].value == 0
    assert translation.plan.assignments[1].unit == "minute"
    assert not translation.report.unsupported


def test_translator_rejects_an_unknown_compound_without_a_fallback() -> None:
    with pytest.raises(InterventionTranslationError) as error:
        OspInterventionTranslator(profile()).translate(intervention(compound_id="unknown"))

    assert error.value.translation.plan is None
    assert (
        error.value.translation.report.unsupported[0].source_field
        == "compound.identity.compound_id"
    )


def test_translator_rejects_a_route_without_an_explicit_target() -> None:
    with pytest.raises(InterventionTranslationError) as error:
        OspInterventionTranslator(profile(route=Route.INTRAVENOUS)).translate(intervention())

    assert error.value.translation.plan is None
    assert error.value.translation.report.unsupported[-1].source_field == "regimen.doses[0].route"


def test_profile_rejects_ambiguous_administration_targets() -> None:
    target = profile().administration_targets[0]

    with pytest.raises(ValidationError, match="must be unique"):
        OspInterventionProfile(
            compound_mappings=profile().compound_mappings,
            administration_targets=(
                target,
                target.model_copy(update={"target_id": "another-target"}),
            ),
        )


def test_profile_rejects_an_incompatible_dose_parameter_unit() -> None:
    with pytest.raises(ValidationError, match="mass dimensions"):
        OspAdministrationTarget(
            target_id="invalid-dose-unit",
            osp_molecule_id="Aciclovir",
            route=Route.ORAL,
            dose_parameter_path="Events|Aciclovir|Dose",
            dose_unit="liter",
            administration_time_parameter_path="Events|Aciclovir|StartTime",
            administration_time_unit="minute",
        )


def test_translator_rejects_multi_dose_regimens_until_explicitly_supported() -> None:
    with pytest.raises(InterventionTranslationError) as error:
        OspInterventionTranslator(profile()).translate(intervention(dose_count=2))

    assert error.value.translation.plan is None
    assert error.value.translation.report.unsupported[-1].source_field == "regimen.doses"
