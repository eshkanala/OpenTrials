"""Auditable compatibility checks between a selected OSP model and an intervention."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.adapters.osp.intervention import (
    OspAdministrationTarget,
    OspCompoundMapping,
    OspInterventionProfile,
)
from opentrials.compound.intervention import Intervention
from opentrials.models.manifest import ModelType
from opentrials.models.package import ModelPackage


class OspModelCapabilityStatus(StrEnum):
    """Whether the selected model can explicitly support one requested feature."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class OspModelCapabilityItem(BaseModel):
    """One inspectable compatibility decision for a selected model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_feature: str = Field(min_length=1)
    status: OspModelCapabilityStatus
    model_feature: str | None = None
    detail: str = Field(min_length=1)


class OspModelCapabilityReport(BaseModel):
    """Static compatibility report; it is not evidence a simulation executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    package_hash: str = Field(min_length=1)
    osp_simulation_name: str = Field(min_length=1)
    items: tuple[OspModelCapabilityItem, ...] = Field(min_length=1)

    @property
    def supported(self) -> tuple[OspModelCapabilityItem, ...]:
        return tuple(
            item for item in self.items if item.status is OspModelCapabilityStatus.SUPPORTED
        )

    @property
    def unsupported(self) -> tuple[OspModelCapabilityItem, ...]:
        return tuple(
            item for item in self.items if item.status is OspModelCapabilityStatus.UNSUPPORTED
        )

    @property
    def is_executable(self) -> bool:
        """Whether every B4c capability required for translation is explicitly present."""
        return not self.unsupported


class OspModelCapabilityProfile(BaseModel):
    """Pre-inspected OSP capabilities tied to one immutable OpenTrials model package.

    This is model-selection data, not a PKML parser. Targets may only be added
    after read-only inspection establishes their semantics and parameter paths.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_package: ModelPackage
    osp_simulation_name: str = Field(min_length=1)
    compound_mappings: tuple[OspCompoundMapping, ...] = Field(min_length=1)
    administration_targets: tuple[OspAdministrationTarget, ...] = ()

    @model_validator(mode="after")
    def validate_selected_osp_model(self) -> OspModelCapabilityProfile:
        manifest = self.model_package.manifest
        if manifest.engine != "osp":
            raise ValueError("OSP capability profiles require a model package with engine 'osp'.")
        if manifest.model_type is not ModelType.PBPK:
            raise ValueError("OSP capability profiles require a PBPK model package.")
        compound_ids = tuple(mapping.opentrials_compound_id for mapping in self.compound_mappings)
        if len(compound_ids) != len(set(compound_ids)):
            raise ValueError("OSP compound mappings must be unique by OpenTrials compound ID.")
        target_keys = tuple(
            (target.osp_molecule_id, target.route) for target in self.administration_targets
        )
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("OSP administration targets must be unique by molecule ID and route.")
        return self

    def intervention_profile(self) -> OspInterventionProfile:
        """Return executable B4a mapping data only when a target has been verified."""
        if not self.administration_targets:
            raise ValueError("No verified OSP administration target is available for execution.")
        return OspInterventionProfile(
            compound_mappings=self.compound_mappings,
            administration_targets=self.administration_targets,
        )


class OspModelCapabilityChecker:
    """Assess an intervention against pre-inspected selected-model capabilities."""

    def assess(
        self, profile: OspModelCapabilityProfile, intervention: Intervention
    ) -> OspModelCapabilityReport:
        items: list[OspModelCapabilityItem] = []
        compound_id = intervention.compound.identity.compound_id
        mapping = next(
            (
                candidate
                for candidate in profile.compound_mappings
                if candidate.opentrials_compound_id == compound_id
            ),
            None,
        )
        if mapping is None:
            items.append(
                OspModelCapabilityItem(
                    requested_feature="compound",
                    status=OspModelCapabilityStatus.UNSUPPORTED,
                    detail=f"No explicit OSP molecule mapping exists for compound {compound_id!r}.",
                )
            )
            return self._report(profile, items)
        items.append(
            OspModelCapabilityItem(
                requested_feature="compound",
                status=OspModelCapabilityStatus.SUPPORTED,
                model_feature=f"OSP molecule {mapping.osp_molecule_id}",
                detail=f"Selected model explicitly maps compound {compound_id!r}.",
            )
        )
        doses = intervention.regimen.doses
        if len(doses) != 1:
            items.append(
                OspModelCapabilityItem(
                    requested_feature="regimen",
                    status=OspModelCapabilityStatus.UNSUPPORTED,
                    detail="B4c supports exactly one dose; multi-dose regimen support is deferred.",
                )
            )
            return self._report(profile, items)
        dose = doses[0]
        target = next(
            (
                candidate
                for candidate in profile.administration_targets
                if candidate.osp_molecule_id == mapping.osp_molecule_id
                and candidate.route is dose.route
            ),
            None,
        )
        if target is None:
            items.extend(
                (
                    OspModelCapabilityItem(
                        requested_feature="route",
                        status=OspModelCapabilityStatus.UNSUPPORTED,
                        detail=(
                            f"No inspected {dose.route.value!r} administration target exists for "
                            f"OSP molecule {mapping.osp_molecule_id!r}."
                        ),
                    ),
                    OspModelCapabilityItem(
                        requested_feature="dose_type",
                        status=OspModelCapabilityStatus.UNSUPPORTED,
                        detail=(
                            "No route-matched administration target exposes an absolute dose "
                            "parameter."
                        ),
                    ),
                    OspModelCapabilityItem(
                        requested_feature="administration_time",
                        status=OspModelCapabilityStatus.UNSUPPORTED,
                        detail=(
                            "No route-matched administration target exposes an administration-time "
                            "parameter."
                        ),
                    ),
                )
            )
            return self._report(profile, items)
        items.extend(
            (
                OspModelCapabilityItem(
                    requested_feature="route",
                    status=OspModelCapabilityStatus.SUPPORTED,
                    model_feature=target.target_id,
                    detail=f"Selected target explicitly supports route {dose.route.value!r}.",
                ),
                OspModelCapabilityItem(
                    requested_feature="dose_type",
                    status=OspModelCapabilityStatus.SUPPORTED,
                    model_feature=target.dose_parameter_path,
                    detail="Selected target exposes a mass-dimensional absolute-dose parameter.",
                ),
                OspModelCapabilityItem(
                    requested_feature="administration_time",
                    status=OspModelCapabilityStatus.SUPPORTED,
                    model_feature=target.administration_time_parameter_path,
                    detail=(
                        "Selected target exposes a time-dimensional administration-time parameter."
                    ),
                ),
            )
        )
        return self._report(profile, items)

    @staticmethod
    def _report(
        profile: OspModelCapabilityProfile, items: list[OspModelCapabilityItem]
    ) -> OspModelCapabilityReport:
        package = profile.model_package
        return OspModelCapabilityReport(
            model_id=package.manifest.id,
            model_version=package.manifest.version,
            package_hash=package.package_hash,
            osp_simulation_name=profile.osp_simulation_name,
            items=tuple(items),
        )
