"""Strict OSP mapping for the single verified Aciclovir IV uncertainty target."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp.intervention import OspParameterAssignment
from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.uncertainty.execution import MaterializedParameterValue

ACICLOVIR_IV_DOSE_TARGET = "intervention.aciclovir_iv.dose"
ACICLOVIR_IV_DOSE_PARAMETER_PATH = "Events|IV 250mg 10min|Application_1|ProtocolSchemaItem|Dose"
ACICLOVIR_IV_MODEL_SHA256 = (
    "sha256:efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
)


class UnsupportedUncertaintyTargetError(ValueError):
    """Raised before OSP invocation when no verified uncertainty mapping exists."""


class OspUncertaintyAssignment(BaseModel):
    """One resolved, execution-ready uncertainty assignment with semantic request evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draw_id: str = Field(min_length=1)
    requested: ScientificValue
    assignment: OspParameterAssignment


def resolve_aciclovir_iv_dose_uncertainty(
    draw_id: str,
    value: MaterializedParameterValue,
    *,
    model_sha256: str,
) -> OspUncertaintyAssignment:
    """Resolve only the independently verified dose target for the pinned PKML."""
    if model_sha256 != ACICLOVIR_IV_MODEL_SHA256:
        raise ValueError(
            "Uncertainty scenario model hash does not match the verified Aciclovir PKML."
        )
    if value.target != ACICLOVIR_IV_DOSE_TARGET:
        raise UnsupportedUncertaintyTargetError(
            f"No verified OSP execution mapping exists for uncertainty target {value.target!r}."
        )
    requested = ScientificValue(value=value.value, unit=value.unit, value_type=ValueType.ASSUMED)
    try:
        executable = requested.to("kg")
    except UnitCompatibilityError as error:
        raise UnsupportedUncertaintyTargetError(
            f"Uncertainty target {value.target!r} requires a mass-compatible value."
        ) from error
    if executable.value <= 0:
        raise ValueError("Aciclovir IV uncertainty doses must be greater than zero.")
    return OspUncertaintyAssignment(
        draw_id=draw_id,
        requested=requested,
        assignment=OspParameterAssignment(
            parameter_path=ACICLOVIR_IV_DOSE_PARAMETER_PATH,
            value=executable.value,
            unit="kg",
            source_field=value.target,
        ),
    )
