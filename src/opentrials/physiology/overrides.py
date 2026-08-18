"""Pure domain types for typed physiological-state perturbation.

A ``PhysiologicalStateOverride`` never names an engine-specific parameter: it
declares an OpenTrials-level physiological target (for example
``"renal.glomerular_filtration_rate"``). Resolving a target to an executable
path is the adapter's job (see ``adapters.osp.physiology_targets``),
following the same translation-layer discipline already used for dose and
intervention mapping.

This module has no storage or adapter dependency so it can be imported from
anywhere without risk of the import cycle documented elsewhere in this
project (storage <-> higher-level package re-exports).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

RENAL_GLOMERULAR_FILTRATION_RATE = "renal.glomerular_filtration_rate"
"""The one physiology target vocabulary this project has verified so far.

This is an OpenTrials-level concept identifier, not engine- or model-
specific -- any registered model's ``ModelCapabilityProfile`` may declare
support for it (see ``PhysiologyTargetCapability.target``), each mapping it
to its own engine parameter path. See HANDOFF v0.6-A for the capability
probe that first verified it.
"""


class PhysiologicalStateOverride(BaseModel):
    """A declared, evidence-attached perturbation of one physiological target.

    The only verified operation is a multiplicative scale of each
    individual's own existing value for ``target`` -- this is exactly what
    the v0.6-A capability probe empirically proved against the pinned
    Aciclovir model (round-trip-safe, and monotonic in its PK consequence).
    An absolute per-individual override was neither requested nor verified,
    so it is deliberately not offered here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str = Field(min_length=1)
    scale_factor: float = Field(gt=0)
    unit: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()


class PhysiologyCoverageReport(BaseModel):
    """What one override did and did not physiologically model.

    Travels with every override so no downstream report, comparison, or UI
    can silently upgrade "one parameter was scaled" into a disease claim
    (for example "renal impairment" or "CKD") that was never verified.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    modeled: tuple[str, ...] = Field(min_length=1)
    unmodeled: tuple[str, ...] = ()
    interpretation: str = Field(min_length=1)
