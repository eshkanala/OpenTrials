"""Contract tests for the pure physiological-state-override domain types."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opentrials.physiology import PhysiologicalStateOverride, PhysiologyCoverageReport


def test_override_requires_a_positive_scale_factor() -> None:
    with pytest.raises(ValidationError):
        PhysiologicalStateOverride(
            target="renal.glomerular_filtration_rate",
            scale_factor=0,
            unit="L/min",
            purpose="test",
        )
    with pytest.raises(ValidationError):
        PhysiologicalStateOverride(
            target="renal.glomerular_filtration_rate",
            scale_factor=-0.5,
            unit="L/min",
            purpose="test",
        )


def test_override_accepts_a_verified_shape() -> None:
    override = PhysiologicalStateOverride(
        target="renal.glomerular_filtration_rate",
        scale_factor=0.6,
        unit="L/min",
        purpose="moderate-renal-function-perturbation",
        evidence_ids=("EV-1",),
        provenance_ids=("PROV-1",),
    )
    assert override.scale_factor == 0.6
    assert override.evidence_ids == ("EV-1",)


def test_override_has_no_absolute_value_field() -> None:
    """Only a verified multiplicative scale is supported -- see v0.6-A probe."""
    with pytest.raises(ValidationError):
        PhysiologicalStateOverride.model_validate(
            {
                "target": "renal.glomerular_filtration_rate",
                "value": 0.05,
                "unit": "L/min",
                "purpose": "test",
            }
        )


def test_coverage_report_requires_at_least_one_modeled_mechanism() -> None:
    with pytest.raises(ValidationError):
        PhysiologyCoverageReport(modeled=(), interpretation="nothing modeled")


def test_coverage_report_records_modeled_and_unmodeled_mechanisms() -> None:
    coverage = PhysiologyCoverageReport(
        modeled=("renal.glomerular_filtration",),
        unmodeled=("renal.tubular_secretion",),
        interpretation="partial renal-function perturbation",
    )
    assert coverage.modeled == ("renal.glomerular_filtration",)
    assert coverage.unmodeled == ("renal.tubular_secretion",)
