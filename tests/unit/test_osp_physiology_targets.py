"""Contract tests for the generic OSP physiological-state target mapping."""

from __future__ import annotations

import pytest

from opentrials.adapters.osp import (
    UnsupportedPhysiologyTargetError,
    physiology_coverage_for,
    resolve_osp_physiology_column,
)
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.physiology import RENAL_GLOMERULAR_FILTRATION_RATE

PROFILE = ACICLOVIR_IV_CAPABILITY_PROFILE


def test_resolves_the_one_verified_renal_target() -> None:
    assert resolve_osp_physiology_column(PROFILE, RENAL_GLOMERULAR_FILTRATION_RATE) == (
        "Organism|Kidney|GFRmat"
    )


def test_rejects_an_unverified_target() -> None:
    with pytest.raises(UnsupportedPhysiologyTargetError):
        resolve_osp_physiology_column(PROFILE, "hepatic.function")


def test_coverage_never_claims_more_than_glomerular_filtration() -> None:
    coverage = physiology_coverage_for(PROFILE, RENAL_GLOMERULAR_FILTRATION_RATE)
    assert coverage.modeled == ("renal.glomerular_filtration",)
    assert "renal.tubular_secretion" in coverage.unmodeled
    lowered = coverage.interpretation.lower()
    # The interpretation must explicitly disclaim a disease-state reading
    # (it is allowed to *mention* CKD only to deny it, never to assert it).
    assert "not a disease-state" in lowered
    assert "ckd or renal impairment) claim" in lowered


def test_coverage_lookup_rejects_an_unverified_target() -> None:
    with pytest.raises(UnsupportedPhysiologyTargetError):
        physiology_coverage_for(PROFILE, "hepatic.function")
