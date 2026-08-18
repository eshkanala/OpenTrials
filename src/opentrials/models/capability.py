"""What one registered model actually supports, as data rather than code.

v0.7-A's whole purpose: replace scattered ``if compound == "aciclovir"``-shaped
knowledge in orchestration modules with one declarative profile the generic
execution pipeline can query. This module stays deliberately engine-agnostic
-- it must never import an adapter (``adapters.osp`` or any future engine
adapter), matching the same "core domain objects never depend on OSP"
discipline the rest of this project already follows. Where OSP's own
intervention types (``adapters.osp.intervention.OspAdministrationTarget`` and
friends) already capture almost the same shape, that is intentional and
temporary: v0.7-B's job is to have orchestration translate between this
generic profile and whatever an engine adapter needs, not to import one
engine's shape into the core here.

Nothing in this module executes anything. A profile only describes what a
registered model claims to support; verifying that claim against the actual
artifact (hashes, structural checks) remains the adapter's and
orchestration's job at execution time, exactly as before.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.compound.intervention import Route
from opentrials.models.package import ModelPackage


class CompoundCapability(BaseModel):
    """One compound this model can simulate, and the engine's identifier for it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    compound_id: str = Field(min_length=1)
    engine_molecule_id: str = Field(min_length=1)


class AdministrationCapability(BaseModel):
    """One route this model supports, and its mutable intervention parameters."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    compound_id: str = Field(min_length=1)
    route: Route
    administration_container_path: str = Field(min_length=1)
    dose_parameter_path: str = Field(min_length=1)
    dose_unit: str = Field(min_length=1)
    administration_time_parameter_path: str = Field(min_length=1)
    administration_time_unit: str = Field(min_length=1)
    infusion_duration_parameter_path: str | None = None
    infusion_duration_unit: str | None = None
    supported_doses: tuple[float, ...] = ()
    supported_dose_unit: str | None = None
    fixed_administration_time_min: float | None = None
    fixed_infusion_duration_min: float | None = None


class PhysiologyTargetCapability(BaseModel):
    """One physiological state this model's population can be perturbed on.

    Mirrors ``adapters.osp.physiology_targets``'s verified-target-only
    discipline: a target only belongs here once it has actually been
    empirically verified (round-trip, executed, and read back), not merely
    hypothesized. ``modeled``/``unmodeled``/``interpretation`` are the same
    coverage-report fields as ``physiology.PhysiologyCoverageReport``,
    duplicated here (not imported) so this module has no dependency beyond
    ``core``/``compound``/``models``.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    target: str = Field(min_length=1)
    parameter_path: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    modeled: tuple[str, ...] = Field(min_length=1)
    unmodeled: tuple[str, ...] = ()
    interpretation: str = Field(min_length=1)


class OutputCapability(BaseModel):
    """One raw model output path and its canonical measurement mapping."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    output_id: str = Field(min_length=1)
    parameter_path: str = Field(min_length=1)
    analyte: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    time_unit: str = Field(min_length=1)


class UnsupportedCapability(BaseModel):
    """An explicit, reasoned gap -- never a silent omission.

    Mirrors this project's ``BLOCKED_EXTERNAL_CAPABILITY`` discipline (e.g.
    repeated dosing, see HANDOFF v0.5): a capability a researcher might
    reasonably expect, recorded with why it is unavailable, rather than
    simply absent from the profile with no explanation.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ModelCapabilityProfile(BaseModel):
    """Everything the generic execution pipeline needs to know about one model.

    Composes the existing ``ModelPackage`` (identity, artifact hash,
    license, applicability -- unchanged) with the new, execution-oriented
    capability description this project has not had until now: which
    compounds, which administration routes and their mutable parameters,
    which physiology targets, and which raw outputs with their canonical
    measurement mapping.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    package: ModelPackage
    compounds: tuple[CompoundCapability, ...] = Field(min_length=1)
    administrations: tuple[AdministrationCapability, ...] = Field(min_length=1)
    physiology_targets: tuple[PhysiologyTargetCapability, ...] = ()
    outputs: tuple[OutputCapability, ...] = Field(min_length=1)
    unsupported_capabilities: tuple[UnsupportedCapability, ...] = ()
