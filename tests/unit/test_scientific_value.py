import pytest
from pydantic import ValidationError

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue, ValueType


def test_converts_compatible_units_and_preserves_metadata() -> None:
    value = ScientificValue(
        value=1.5,
        unit="g",
        value_type=ValueType.OBSERVED,
        evidence_ids=("evidence-001",),
        method="validated assay",
    )

    converted = value.to("mg")

    assert converted.value == 1500.0
    assert converted.unit == "mg"
    assert converted.evidence_ids == ("evidence-001",)
    assert converted.method == "validated assay"
    assert value.unit == "g"


def test_rejects_incompatible_unit_conversion() -> None:
    value = ScientificValue(value=1.0, unit="mg", value_type=ValueType.OBSERVED)

    with pytest.raises(UnitCompatibilityError, match="incompatible"):
        value.to("second")


def test_rejects_unknown_units() -> None:
    with pytest.raises(ValidationError, match="Unknown unit"):
        ScientificValue(value=1.0, unit="definitely_not_a_unit", value_type=ValueType.ASSUMED)


def test_canonical_json_is_deterministic() -> None:
    first = ScientificValue(
        value=2.0,
        unit="L/h",
        value_type=ValueType.FITTED,
        conditions={"temperature": "37 degC", "species": "human"},
    )
    second = ScientificValue(
        value=2.0,
        unit="L/h",
        value_type=ValueType.FITTED,
        conditions={"species": "human", "temperature": "37 degC"},
    )

    assert first.canonical_json() == second.canonical_json()
    assert first.canonical_json() == (
        '{"conditions":{"species":"human","temperature":"37 degC"},'
        '"unit":"L/h","value":2.0,"value_type":"FITTED"}'
    )
