"""Strict OSP mapping for verified OpenTrials physiological-state targets.

Only one target has an empirically verified execution path today (see the
v0.6-A capability probe recorded in HANDOFF.md): ``ospsuite-R`` exposes no
disease- or organ-impairment population API at all -- neither
``createPopulationCharacteristics()`` nor ``createIndividualCharacteristics()``
has a disease parameter, and the package help index has zero renal/kidney/
impairment/disease topics. But the pinned Aciclovir model carries a real,
physiologically meaningful per-individual glomerular filtration rate
(``Organism|Kidney|GFRmat``, litres/minute) that is already a standard
column in every population OSP generates. Scaling it was verified to
round-trip exactly through ``populationFromDataFrame()``/
``populationToDataFrame()`` and to produce a monotonic, mechanistically
sensible PK consequence when executed. Nothing else is claimed.
"""

from __future__ import annotations

from opentrials.physiology.overrides import PhysiologyCoverageReport

RENAL_GLOMERULAR_FILTRATION_RATE = "renal.glomerular_filtration_rate"

OSP_PHYSIOLOGY_TARGET_COLUMNS: dict[str, str] = {
    RENAL_GLOMERULAR_FILTRATION_RATE: "Organism|Kidney|GFRmat",
}

_COVERAGE_BY_TARGET: dict[str, PhysiologyCoverageReport] = {
    RENAL_GLOMERULAR_FILTRATION_RATE: PhysiologyCoverageReport(
        modeled=("renal.glomerular_filtration",),
        unmodeled=(
            "renal.tubular_secretion",
            "renal.blood_flow",
            "renal.protein_binding_effects",
        ),
        interpretation=(
            "Only glomerular filtration was perturbed, via a direct scale of the "
            "model's own per-individual GFRmat parameter. Tubular secretion and "
            "other renal-clearance pathways were left unmodified. This is a "
            "verified physiological-parameter perturbation, not a disease-state "
            "(e.g. CKD or renal impairment) claim -- a complete renal-impairment "
            "phenotype would need to also scale tubular secretion and other "
            "renal mechanisms, which this override does not do."
        ),
    ),
}


class UnsupportedPhysiologyTargetError(ValueError):
    """Raised before touching a population table when no verified mapping exists."""


def resolve_osp_physiology_column(target: str) -> str:
    """Return the exact OTPGEN population-table column for a verified target."""
    try:
        return OSP_PHYSIOLOGY_TARGET_COLUMNS[target]
    except KeyError as error:
        raise UnsupportedPhysiologyTargetError(
            f"No verified OSP physiological-state mapping exists for target {target!r}."
        ) from error


def physiology_coverage_for(target: str) -> PhysiologyCoverageReport:
    """Return the fixed, honest coverage statement for a verified target."""
    try:
        return _COVERAGE_BY_TARGET[target]
    except KeyError as error:
        raise UnsupportedPhysiologyTargetError(
            f"No verified physiology coverage statement exists for target {target!r}."
        ) from error
