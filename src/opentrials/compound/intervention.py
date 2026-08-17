"""Dose, regimen, and intervention contracts."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.compound.compound import Compound
from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue


class Route(StrEnum):
    """Extensible administration routes supported by the founding specification."""

    ORAL = "ORAL"
    INTRAVENOUS = "INTRAVENOUS"
    INTRAMUSCULAR = "INTRAMUSCULAR"
    SUBCUTANEOUS = "SUBCUTANEOUS"
    INHALED = "INHALED"
    TRANSDERMAL = "TRANSDERMAL"
    INTRANASAL = "INTRANASAL"
    OCULAR = "OCULAR"
    RECTAL = "RECTAL"
    OTHER = "OTHER"


class Dose(BaseModel):
    """One administration amount and route, relative to a trial time origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: ScientificValue
    route: Route
    administration_time: ScientificValue = Field(
        description="Time elapsed from the enclosing regimen's reference time."
    )
    infusion_duration: ScientificValue | None = Field(
        default=None,
        description="Duration of an intravenous infusion; absent for non-infusion administrations.",
    )
    formulation_id: str | None = None

    @model_validator(mode="after")
    def validate_dimensions(self) -> Dose:
        try:
            amount = self.amount.to("milligram").value
        except UnitCompatibilityError as error:
            raise ValueError("Dose amount must have mass dimensions.") from error
        try:
            administration_time = self.administration_time.to("second").value
        except UnitCompatibilityError as error:
            raise ValueError("Dose administration time must have time dimensions.") from error
        if amount <= 0:
            raise ValueError("Dose amount must be greater than zero.")
        if administration_time < 0:
            raise ValueError("Dose administration time cannot be negative.")
        if self.infusion_duration is not None:
            if self.route is not Route.INTRAVENOUS:
                raise ValueError("Infusion duration is supported only for intravenous doses.")
            try:
                infusion_duration = self.infusion_duration.to("second").value
            except UnitCompatibilityError as error:
                raise ValueError("Infusion duration must have time dimensions.") from error
            if infusion_duration <= 0:
                raise ValueError("Infusion duration must be greater than zero.")
        return self


class Regimen(BaseModel):
    """An ordered set of administrations for one intervention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    regimen_id: str = Field(min_length=1)
    doses: tuple[Dose, ...] = Field(min_length=1)
    duration: ScientificValue | None = None
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_schedule(self) -> Regimen:
        administration_times = tuple(
            dose.administration_time.to("second").value for dose in self.doses
        )
        if administration_times != tuple(sorted(administration_times)):
            raise ValueError("Regimen doses must be ordered by administration time.")
        if self.duration is not None:
            try:
                duration = self.duration.to("second").value
            except UnitCompatibilityError as error:
                raise ValueError("Regimen duration must have time dimensions.") from error
            if duration <= 0:
                raise ValueError("Regimen duration must be greater than zero.")
            if administration_times[-1] > duration:
                raise ValueError("Regimen doses cannot occur after the regimen duration.")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically for trial and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class InterventionType(StrEnum):
    """Types of interventions supported by the core abstraction."""

    COMPOUND = "COMPOUND"


class Intervention(BaseModel):
    """A compound combined with an administration regimen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intervention_id: str = Field(min_length=1)
    intervention_type: InterventionType = InterventionType.COMPOUND
    compound: Compound
    regimen: Regimen
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    def canonical_json(self) -> str:
        """Serialize deterministically for trial and run manifests."""
        return json.dumps(
            self.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
