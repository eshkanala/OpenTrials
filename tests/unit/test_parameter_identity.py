"""Contract tests for sdk.parameter_identity's canonical vocabulary + alias resolution."""

from __future__ import annotations

import pytest

from opentrials.sdk.parameter_identity import (
    check_unit_compatible,
    parameter_identity,
    resolve_parameter_alias,
)


def test_parameter_identity_looks_up_a_known_canonical_id() -> None:
    identity = parameter_identity("renal_clearance")
    assert identity.reference_unit == "L/hour"


def test_parameter_identity_raises_for_an_unknown_canonical_id() -> None:
    with pytest.raises(ValueError, match="Unknown canonical parameter identity"):
        parameter_identity("not_a_real_parameter")


def test_resolve_parameter_alias_matches_case_insensitively() -> None:
    identity = resolve_parameter_alias("clr")
    assert identity is not None
    assert identity.canonical_id == "renal_clearance"


def test_resolve_parameter_alias_matches_the_canonical_id_itself() -> None:
    identity = resolve_parameter_alias("renal_clearance")
    assert identity is not None
    assert identity.canonical_id == "renal_clearance"


def test_resolve_parameter_alias_returns_none_for_an_unknown_name() -> None:
    assert resolve_parameter_alias("not a real parameter name") is None


def test_check_unit_compatible_accepts_a_dimensionally_equivalent_unit() -> None:
    check_unit_compatible("renal_clearance", "mL/min")  # must not raise


def test_check_unit_compatible_accepts_percent_for_a_dimensionless_fraction() -> None:
    check_unit_compatible("plasma_protein_binding_fraction", "percent")  # must not raise


def test_check_unit_compatible_rejects_a_dimensionally_incompatible_unit() -> None:
    with pytest.raises(ValueError, match="not dimensionally compatible"):
        check_unit_compatible("renal_clearance", "L")
