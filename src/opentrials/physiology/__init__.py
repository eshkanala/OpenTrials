"""Typed physiological-state perturbation -- pure domain types only.

Storage (``storage.physiology``) and OSP-specific target resolution
(``adapters.osp.physiology_targets``) live in their own modules and must be
imported directly by full path; this package re-exports only
dependency-free types, matching the import-cycle-avoidance discipline used
by ``cohort`` and ``responders`` elsewhere in this project.
"""

from opentrials.physiology.overrides import PhysiologicalStateOverride, PhysiologyCoverageReport

__all__ = ["PhysiologicalStateOverride", "PhysiologyCoverageReport"]
