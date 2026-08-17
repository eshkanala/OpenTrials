"""Strict, auditable translation from OpenTrials interventions to OSP plans."""

from __future__ import annotations

from enum import StrEnum

from pint.errors import DimensionalityError, UndefinedUnitError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.compound.intervention import Intervention, Route
from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue
from opentrials.core.units import unit_registry


class InterventionFeatureStatus(StrEnum):
    """How an OpenTrials intervention feature was handled by OSP translation."""

    MAPPED = "MAPPED"
    UNSUPPORTED = "UNSUPPORTED"


class InterventionTranslationItem(BaseModel):
    """One field-level translation decision, suitable for audit output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_field: str = Field(min_length=1)
    status: InterventionFeatureStatus
    target_field: str | None = None
    detail: str = Field(min_length=1)


class OspInterventionTranslationReport(BaseModel):
    """Complete mapping and failure record for one intervention translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[InterventionTranslationItem, ...] = Field(min_length=1)

    @property
    def mapped(self) -> tuple[InterventionTranslationItem, ...]:
        return tuple(item for item in self.items if item.status is InterventionFeatureStatus.MAPPED)

    @property
    def unsupported(self) -> tuple[InterventionTranslationItem, ...]:
        return tuple(
            item for item in self.items if item.status is InterventionFeatureStatus.UNSUPPORTED
        )


class OspCompoundMapping(BaseModel):
    """An explicit mapping from an OpenTrials compound ID to an OSP molecule ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    opentrials_compound_id: str = Field(min_length=1)
    osp_molecule_id: str = Field(min_length=1)


class OspAdministrationTarget(BaseModel):
    """A pre-inspected OSP administration and its mutable parameter paths.

    B4a defines this contract only. B4b must populate targets only after
    inspecting the actual PKML and confirming its administration semantics.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    osp_molecule_id: str = Field(min_length=1)
    route: Route
    dose_parameter_path: str = Field(min_length=1)
    dose_unit: str = Field(min_length=1)
    administration_time_parameter_path: str = Field(min_length=1)
    administration_time_unit: str = Field(min_length=1)
    infusion_duration_parameter_path: str | None = None
    infusion_duration_unit: str | None = None

    @model_validator(mode="after")
    def validate_parameter_units(self) -> OspAdministrationTarget:
        try:
            unit_registry.Quantity(1, self.dose_unit).to("milligram")
        except (UndefinedUnitError, DimensionalityError) as error:
            raise ValueError("OSP administration dose_unit must have mass dimensions.") from error
        try:
            unit_registry.Quantity(1, self.administration_time_unit).to("second")
        except (UndefinedUnitError, DimensionalityError) as error:
            raise ValueError("OSP administration_time_unit must have time dimensions.") from error
        duration_fields = (self.infusion_duration_parameter_path, self.infusion_duration_unit)
        if any(field is None for field in duration_fields) and any(
            field is not None for field in duration_fields
        ):
            raise ValueError(
                "OSP infusion-duration parameter path and unit must be provided together."
            )
        if self.infusion_duration_unit is not None:
            try:
                unit_registry.Quantity(1, self.infusion_duration_unit).to("second")
            except (UndefinedUnitError, DimensionalityError) as error:
                raise ValueError("OSP infusion_duration_unit must have time dimensions.") from error
        return self


class OspInterventionProfile(BaseModel):
    """Explicit, PKML-specific mapping data consumed by the B4a translator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compound_mappings: tuple[OspCompoundMapping, ...] = Field(min_length=1)
    administration_targets: tuple[OspAdministrationTarget, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unambiguous_mappings(self) -> OspInterventionProfile:
        compound_ids = tuple(mapping.opentrials_compound_id for mapping in self.compound_mappings)
        if len(compound_ids) != len(set(compound_ids)):
            raise ValueError("OSP compound mappings must be unique by OpenTrials compound ID.")
        target_keys = tuple(
            (target.osp_molecule_id, target.route) for target in self.administration_targets
        )
        if len(target_keys) != len(set(target_keys)):
            raise ValueError("OSP administration targets must be unique by molecule ID and route.")
        return self


class OspParameterAssignment(BaseModel):
    """One planned OSP parameter assignment; not proof that it was executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_path: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    source_field: str = Field(min_length=1)


class OspInterventionPlan(BaseModel):
    """A complete, reviewable modification plan for one single-dose intervention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    intervention_id: str = Field(min_length=1)
    regimen_id: str = Field(min_length=1)
    requested_compound_id: str = Field(min_length=1)
    requested_dose: ScientificValue
    requested_route: Route
    requested_administration_time: ScientificValue
    requested_infusion_duration: ScientificValue | None = None
    osp_molecule_id: str = Field(min_length=1)
    osp_administration_target_id: str = Field(min_length=1)
    executable_route: Route
    assignments: tuple[OspParameterAssignment, ...] = Field(min_length=2, max_length=3)


class OspInterventionTranslation(BaseModel):
    """A plan plus its report, or a report alone when translation is rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: OspInterventionPlan | None = None
    report: OspInterventionTranslationReport


class InterventionTranslationError(ValueError):
    """Raised when an intervention cannot be mapped without scientific ambiguity."""

    def __init__(self, translation: OspInterventionTranslation) -> None:
        self.translation = translation
        unsupported_fields = ", ".join(item.source_field for item in translation.report.unsupported)
        super().__init__(f"Unsupported OSP intervention features: {unsupported_fields}.")


class OspInterventionTranslator:
    """Build single-dose OSP parameter plans from explicit pre-inspected mappings.

    The translator never selects a fallback administration. It performs no PKML
    access, no R invocation, and no parameter mutation.
    """

    def __init__(self, profile: OspInterventionProfile) -> None:
        self._profile = profile

    def translate(self, intervention: Intervention) -> OspInterventionTranslation:
        items: list[InterventionTranslationItem] = []
        compound_id = intervention.compound.identity.compound_id
        compound_mapping = next(
            (
                mapping
                for mapping in self._profile.compound_mappings
                if mapping.opentrials_compound_id == compound_id
            ),
            None,
        )
        if compound_mapping is None:
            return self._raise_unsupported(
                items,
                "compound.identity.compound_id",
                f"No explicit OSP molecule mapping exists for compound {compound_id!r}.",
            )
        items.append(
            InterventionTranslationItem(
                source_field="compound.identity.compound_id",
                status=InterventionFeatureStatus.MAPPED,
                target_field="osp_molecule_id",
                detail=(
                    f"Maps {compound_id!r} to OSP molecule {compound_mapping.osp_molecule_id!r}."
                ),
            )
        )
        doses = intervention.regimen.doses
        if len(doses) != 1:
            return self._raise_unsupported(
                items,
                "regimen.doses",
                "v0.1-B4a supports exactly one dose; multi-dose regimen translation is deferred.",
            )
        dose = doses[0]
        target = next(
            (
                candidate
                for candidate in self._profile.administration_targets
                if candidate.osp_molecule_id == compound_mapping.osp_molecule_id
                and candidate.route is dose.route
            ),
            None,
        )
        if target is None:
            return self._raise_unsupported(
                items,
                "regimen.doses[0].route",
                (
                    "No explicit OSP administration target exists for molecule "
                    f"{compound_mapping.osp_molecule_id!r} and route {dose.route.value!r}."
                ),
            )
        try:
            executable_dose = dose.amount.to(target.dose_unit)
            executable_time = dose.administration_time.to(target.administration_time_unit)
        except UnitCompatibilityError as error:
            return self._raise_unsupported(
                items,
                "regimen.doses[0]",
                f"Requested dose cannot be converted to the selected OSP target: {error}",
            )
        executable_duration: ScientificValue | None = None
        if dose.infusion_duration is not None and target.infusion_duration_unit is None:
            return self._raise_unsupported(
                items,
                "regimen.doses[0].infusion_duration",
                (
                    "The selected OSP administration target has no verified "
                    "infusion-duration parameter."
                ),
            )
        if dose.infusion_duration is None and target.infusion_duration_unit is not None:
            return self._raise_unsupported(
                items,
                "regimen.doses[0].infusion_duration",
                "The selected OSP administration target requires an explicit infusion duration.",
            )
        if dose.infusion_duration is not None and target.infusion_duration_unit is not None:
            try:
                executable_duration = dose.infusion_duration.to(target.infusion_duration_unit)
            except UnitCompatibilityError as error:
                return self._raise_unsupported(
                    items,
                    "regimen.doses[0].infusion_duration",
                    (f"Requested infusion duration cannot be converted to OSP target: {error}"),
                )
        items.extend(
            (
                InterventionTranslationItem(
                    source_field="regimen.doses[0].amount",
                    status=InterventionFeatureStatus.MAPPED,
                    target_field=target.dose_parameter_path,
                    detail=(
                        f"Converts requested dose to {target.dose_unit!r} for the selected target."
                    ),
                ),
                InterventionTranslationItem(
                    source_field="regimen.doses[0].route",
                    status=InterventionFeatureStatus.MAPPED,
                    target_field="osp_administration_target_id",
                    detail=(
                        f"Maps {dose.route.value!r} only to explicit target {target.target_id!r}; "
                        "no fallback route is permitted."
                    ),
                ),
                InterventionTranslationItem(
                    source_field="regimen.doses[0].administration_time",
                    status=InterventionFeatureStatus.MAPPED,
                    target_field=target.administration_time_parameter_path,
                    detail=(
                        "Converts requested administration time to "
                        f"{target.administration_time_unit!r} for the selected target."
                    ),
                ),
            )
        )
        if executable_duration is not None and target.infusion_duration_parameter_path is not None:
            items.append(
                InterventionTranslationItem(
                    source_field="regimen.doses[0].infusion_duration",
                    status=InterventionFeatureStatus.MAPPED,
                    target_field=target.infusion_duration_parameter_path,
                    detail=(
                        "Converts requested infusion duration to "
                        f"{target.infusion_duration_unit!r} for the selected target."
                    ),
                )
            )
        return OspInterventionTranslation(
            plan=OspInterventionPlan(
                intervention_id=intervention.intervention_id,
                regimen_id=intervention.regimen.regimen_id,
                requested_compound_id=compound_id,
                requested_dose=dose.amount,
                requested_route=dose.route,
                requested_administration_time=dose.administration_time,
                requested_infusion_duration=dose.infusion_duration,
                osp_molecule_id=compound_mapping.osp_molecule_id,
                osp_administration_target_id=target.target_id,
                executable_route=target.route,
                assignments=(
                    OspParameterAssignment(
                        parameter_path=target.dose_parameter_path,
                        value=executable_dose.value,
                        unit=target.dose_unit,
                        source_field="regimen.doses[0].amount",
                    ),
                    OspParameterAssignment(
                        parameter_path=target.administration_time_parameter_path,
                        value=executable_time.value,
                        unit=target.administration_time_unit,
                        source_field="regimen.doses[0].administration_time",
                    ),
                    *(
                        (
                            OspParameterAssignment(
                                parameter_path=target.infusion_duration_parameter_path,
                                value=executable_duration.value,
                                unit=target.infusion_duration_unit,
                                source_field="regimen.doses[0].infusion_duration",
                            ),
                        )
                        if executable_duration is not None
                        and target.infusion_duration_parameter_path is not None
                        and target.infusion_duration_unit is not None
                        else ()
                    ),
                ),
            ),
            report=OspInterventionTranslationReport(items=tuple(items)),
        )

    @staticmethod
    def _raise_unsupported(
        items: list[InterventionTranslationItem], source_field: str, detail: str
    ) -> OspInterventionTranslation:
        items.append(
            InterventionTranslationItem(
                source_field=source_field,
                status=InterventionFeatureStatus.UNSUPPORTED,
                detail=detail,
            )
        )
        translation = OspInterventionTranslation(
            report=OspInterventionTranslationReport(items=tuple(items))
        )
        raise InterventionTranslationError(translation)
