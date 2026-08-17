import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from opentrials.analysis.sensitivity import (
    SensitivityInput,
    SensitivityOutput,
    calculate_pearson_sensitivities,
)


def input(input_id: str, values: tuple[float, ...]) -> SensitivityInput:
    return SensitivityInput(input_id=input_id, values=values)


def output(output_id: str, values: tuple[float, ...]) -> SensitivityOutput:
    return SensitivityOutput(output_id=output_id, values=values)


def test_calculates_known_first_order_pearson_correlations_in_sorted_order() -> None:
    results = calculate_pearson_sensitivities(
        (
            input("z-input", (1, 2, 3, 4)),
            input("a-input", (1, 2, 3, 4)),
        ),
        (
            output("z-output", (4, 3, 2, 1)),
            output("a-output", (2, 4, 6, 8)),
        ),
    )

    assert [(result.input_id, result.output_id) for result in results] == [
        ("a-input", "a-output"),
        ("a-input", "z-output"),
        ("z-input", "a-output"),
        ("z-input", "z-output"),
    ]
    assert [result.correlation for result in results] == pytest.approx((1.0, -1.0, 1.0, -1.0))


@pytest.mark.parametrize("value", (math.inf, -math.inf, math.nan))
def test_rejects_nonfinite_draw_values(value: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        SensitivityInput(input_id="clearance", values=(1.0, value))


@pytest.mark.parametrize(
    ("inputs", "outputs", "message"),
    [
        ((input("a", (1, 2)),), (output("y", (1, 2, 3)),), "equal row counts"),
        ((input("a", (1, 2)), input("a", (2, 3))), (output("y", (1, 2)),), "unique"),
        ((input("a", (1, 2)),), (output("y", (1, 2)), output("y", (2, 3))), "unique"),
        ((input("a", (1, 1)),), (output("y", (1, 2)),), "input 'a'.*nonzero variance"),
        ((input("a", (1, 2)),), (output("y", (1, 1)),), "output 'y'.*nonzero variance"),
    ],
)
def test_rejects_invalid_alignment_identity_or_variance(
    inputs: tuple[SensitivityInput, ...],
    outputs: tuple[SensitivityOutput, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_pearson_sensitivities(inputs, outputs)


@pytest.mark.parametrize(
    ("constructor", "identifier"),
    [
        (lambda: SensitivityInput(input_id="x", values=(1.0, 2.0)), "input_id"),
        (lambda: SensitivityOutput(output_id="y", values=(1.0, 2.0)), "output_id"),
    ],
)
def test_models_are_immutable(
    constructor: Callable[[], SensitivityInput | SensitivityOutput], identifier: str
) -> None:
    model = constructor()

    with pytest.raises(ValidationError, match="frozen"):
        setattr(model, identifier, "changed")
