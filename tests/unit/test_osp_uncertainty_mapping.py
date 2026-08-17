import pytest

from opentrials.adapters.osp.uncertainty import (
    ACICLOVIR_IV_DOSE_PARAMETER_PATH,
    ACICLOVIR_IV_MODEL_SHA256,
    UnsupportedUncertaintyTargetError,
    resolve_aciclovir_iv_dose_uncertainty,
)
from opentrials.uncertainty.execution import MaterializedParameterValue


def value(
    *, target: str = "intervention.aciclovir_iv.dose", unit: str = "mg", amount: float = 125.0
) -> MaterializedParameterValue:
    return MaterializedParameterValue(parameter_id="dose", target=target, value=amount, unit=unit)


def test_resolves_mass_compatible_dose_to_the_one_verified_osp_path() -> None:
    resolved = resolve_aciclovir_iv_dose_uncertainty(
        "draw-000001", value(), model_sha256=ACICLOVIR_IV_MODEL_SHA256
    )

    assert resolved.requested.to("mg").value == 125.0
    assert resolved.assignment.parameter_path == ACICLOVIR_IV_DOSE_PARAMETER_PATH
    assert resolved.assignment.value == 0.000125
    assert resolved.assignment.unit == "kg"


def test_rejects_unknown_target_wrong_model_and_non_mass_value_before_execution() -> None:
    with pytest.raises(UnsupportedUncertaintyTargetError, match="No verified OSP"):
        resolve_aciclovir_iv_dose_uncertainty(
            "draw-1",
            value(target="physiology.renal_clearance"),
            model_sha256=ACICLOVIR_IV_MODEL_SHA256,
        )
    with pytest.raises(ValueError, match="model hash"):
        resolve_aciclovir_iv_dose_uncertainty("draw-1", value(), model_sha256="sha256:" + "0" * 64)
    with pytest.raises(UnsupportedUncertaintyTargetError, match="mass-compatible"):
        resolve_aciclovir_iv_dose_uncertainty(
            "draw-1", value(unit="minute"), model_sha256=ACICLOVIR_IV_MODEL_SHA256
        )
