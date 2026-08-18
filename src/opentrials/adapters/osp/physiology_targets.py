"""Resolve a declared physiology target against a registered model's own profile.

v0.7-B: this module used to hardcode one model's verified physiology-target
mapping directly (the v0.6-A capability probe's finding that the pinned
Aciclovir model's ``Organism|Kidney|GFRmat`` column is the only verified
physiological-state lever). That mapping now lives as data on the model's
own ``ModelCapabilityProfile`` (see ``models.profiles.aciclovir_iv``) --
this module only resolves a requested target against whichever profile is
supplied, so it works unchanged for any future registered model that
declares its own verified physiology targets.
"""

from __future__ import annotations

from opentrials.models.capability import ModelCapabilityProfile
from opentrials.physiology.overrides import PhysiologyCoverageReport


class UnsupportedPhysiologyTargetError(ValueError):
    """Raised before touching a population table when no verified mapping exists."""


def resolve_osp_physiology_column(profile: ModelCapabilityProfile, target: str) -> str:
    """Return the exact OTPGEN population-table column for a verified target."""
    for capability in profile.physiology_targets:
        if capability.target == target:
            return capability.parameter_path
    raise UnsupportedPhysiologyTargetError(
        f"No verified physiological-state mapping exists for target {target!r} on "
        f"model {profile.package.manifest.id!r}."
    )


def physiology_coverage_for(
    profile: ModelCapabilityProfile, target: str
) -> PhysiologyCoverageReport:
    """Return the fixed, honest coverage statement for a verified target."""
    for capability in profile.physiology_targets:
        if capability.target == target:
            return PhysiologyCoverageReport(
                modeled=capability.modeled,
                unmodeled=capability.unmodeled,
                interpretation=capability.interpretation,
            )
    raise UnsupportedPhysiologyTargetError(
        f"No verified physiology coverage statement exists for target {target!r} on "
        f"model {profile.package.manifest.id!r}."
    )
