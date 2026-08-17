"""Strict compatibility assessment for observed PK validation datasets."""

from __future__ import annotations

from enum import StrEnum
from math import isclose
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.exceptions import UnitCompatibilityError
from opentrials.core.scientific_value import ScientificValue
from opentrials.trials.endpoints import Endpoint, EndpointType
from opentrials.trials.trial import Trial, TrialArm
from opentrials.validation.observed import ObservedDataset
from opentrials.validation.study import DatasetRole

_FLOAT_TOLERANCE = 1e-9


class ValidationEligibility(StrEnum):
    """Whether a dataset may support the requested validation comparison."""

    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_LIMITATIONS = "ELIGIBLE_WITH_LIMITATIONS"
    INELIGIBLE = "INELIGIBLE"


class CompatibilityStatus(StrEnum):
    """Outcome of one compatibility criterion."""

    MATCH = "MATCH"
    LIMITATION = "LIMITATION"
    MISMATCH = "MISMATCH"


class CompatibilityItem(BaseModel):
    """One auditable compatibility finding."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1)
    status: CompatibilityStatus
    detail: str = Field(min_length=1)


class PredictedPkSeriesDescriptor(BaseModel):
    """Declared context and sampling schedule of a predicted PK series."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    trial_arm_id: str = Field(min_length=1)
    analyte: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    fraction: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    time_unit: str = Field(min_length=1)
    sample_times: tuple[ScientificValue, ...] = Field(min_length=1)


class ValidationCompatibilityReport(BaseModel):
    """Immutable compatibility decision and its individual findings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    trial_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    eligibility: ValidationEligibility
    items: tuple[CompatibilityItem, ...] = Field(min_length=1)

    @property
    def has_mismatches(self) -> bool:
        """Whether any required compatibility condition failed."""
        return any(item.status is CompatibilityStatus.MISMATCH for item in self.items)

    @property
    def has_limitations(self) -> bool:
        """Whether interpretation has documented limitations."""
        return any(item.status is CompatibilityStatus.LIMITATION for item in self.items)

    @property
    def is_eligible(self) -> bool:
        """Whether the dataset remains usable for validation."""
        return self.eligibility is not ValidationEligibility.INELIGIBLE


def _item(field: str, status: CompatibilityStatus, detail: str) -> CompatibilityItem:
    return CompatibilityItem(field=field, status=status, detail=detail)


def _same_value(left: ScientificValue, right: ScientificValue) -> bool:
    """Compare quantities after conversion using a narrow absolute float tolerance."""
    return isclose(left.to(right.unit).value, right.value, rel_tol=0.0, abs_tol=_FLOAT_TOLERANCE)


def _select_arm(trial: Trial, arm_id: str) -> tuple[TrialArm | None, CompatibilityItem]:
    arms = tuple(arm for arm in trial.arms if arm.arm_id == arm_id and arm.name.strip())
    if len(arms) == 1:
        return arms[0], _item("trial_arm", CompatibilityStatus.MATCH, f"Selected arm {arm_id!r}.")
    return None, _item(
        "trial_arm",
        CompatibilityStatus.MISMATCH,
        f"Expected exactly one named trial arm with ID {arm_id!r}; found {len(arms)}.",
    )


def _select_pk_endpoint(trial: Trial) -> tuple[Endpoint | None, CompatibilityItem]:
    endpoints = [
        endpoint for endpoint in trial.endpoints if endpoint.endpoint_type is EndpointType.PK
    ]
    if not endpoints:
        return None, _item("pk_endpoint", CompatibilityStatus.MISMATCH, "Trial has no PK endpoint.")
    endpoint = endpoints[0]
    if len(endpoints) > 1:
        return endpoint, _item(
            "pk_endpoint",
            CompatibilityStatus.LIMITATION,
            (
                f"Trial has {len(endpoints)} PK endpoints; used first endpoint "
                f"{endpoint.endpoint_id!r}."
            ),
        )
    return endpoint, _item(
        "pk_endpoint",
        CompatibilityStatus.MATCH,
        f"Selected PK endpoint {endpoint.endpoint_id!r}.",
    )


def assess_validation_compatibility(
    trial: Trial,
    dataset: ObservedDataset,
    predicted: PredictedPkSeriesDescriptor,
) -> ValidationCompatibilityReport:
    """Assess whether observed PK data can validly compare with a predicted series.

    Comparisons are intentionally conservative: incompatible scientific context or
    regimen produces a mismatch, while unprovable population comparability and
    declared study limitations remain explicit limitations.
    """
    items: list[CompatibilityItem] = []
    arm, arm_item = _select_arm(trial, predicted.trial_arm_id)
    items.append(arm_item)

    if arm is not None:
        observed_intervention = dataset.study.intervention
        trial_intervention = arm.intervention
        observed_doses = observed_intervention.regimen.doses
        trial_doses = trial_intervention.regimen.doses
        items.append(
            _item(
                "compound_id",
                CompatibilityStatus.MATCH
                if observed_intervention.compound.identity.compound_id
                == trial_intervention.compound.identity.compound_id
                else CompatibilityStatus.MISMATCH,
                "Observed and trial-arm compound IDs match."
                if observed_intervention.compound.identity.compound_id
                == trial_intervention.compound.identity.compound_id
                else "Observed and trial-arm compound IDs differ.",
            )
        )
        items.append(
            _item(
                "dose_count",
                CompatibilityStatus.MATCH
                if len(observed_doses) == len(trial_doses) == 1
                else CompatibilityStatus.MISMATCH,
                "Both interventions contain one dose."
                if len(observed_doses) == len(trial_doses) == 1
                else "Validation requires exactly one observed and one trial-arm dose.",
            )
        )
        if len(observed_doses) == len(trial_doses) == 1:
            observed_dose, trial_dose = observed_doses[0], trial_doses[0]
            for field, observed_value, trial_value in (
                ("dose_amount", observed_dose.amount, trial_dose.amount),
                (
                    "administration_time",
                    observed_dose.administration_time,
                    trial_dose.administration_time,
                ),
            ):
                try:
                    matches = _same_value(observed_value, trial_value)
                except UnitCompatibilityError:
                    matches = False
                items.append(
                    _item(
                        field,
                        CompatibilityStatus.MATCH if matches else CompatibilityStatus.MISMATCH,
                        (
                            f"Observed {field.replace('_', ' ')} "
                            f"{'matches' if matches else 'does not match'} the trial arm."
                        ),
                    )
                )
            route_matches = observed_dose.route is trial_dose.route
            items.append(
                _item(
                    "route",
                    CompatibilityStatus.MATCH if route_matches else CompatibilityStatus.MISMATCH,
                    "Observed route matches the trial arm."
                    if route_matches
                    else "Observed route does not match the trial arm.",
                )
            )
            observed_duration = observed_dose.infusion_duration
            trial_duration = trial_dose.infusion_duration
            if (observed_duration is None) != (trial_duration is None):
                duration_matches = False
            elif observed_duration is None or trial_duration is None:
                duration_matches = True
            else:
                try:
                    duration_matches = _same_value(observed_duration, trial_duration)
                except UnitCompatibilityError:
                    duration_matches = False
            items.append(
                _item(
                    "infusion_duration",
                    CompatibilityStatus.MATCH if duration_matches else CompatibilityStatus.MISMATCH,
                    "Observed infusion-duration presence and value match the trial arm."
                    if duration_matches
                    else (
                        "Observed infusion-duration presence or value does not match the trial arm."
                    ),
                )
            )

    endpoint, endpoint_item = _select_pk_endpoint(trial)
    items.append(endpoint_item)
    for field in ("analyte", "matrix", "fraction", "measurement"):
        mismatched = any(
            getattr(observation, field) != getattr(predicted, field)
            for observation in dataset.observations
        )
        items.append(
            _item(
                field,
                CompatibilityStatus.MISMATCH if mismatched else CompatibilityStatus.MATCH,
                (
                    f"All observed {field} values "
                    f"{'match' if not mismatched else 'do not match'} the predicted descriptor."
                ),
            )
        )

    for observation in dataset.observations:
        try:
            _ = observation.value.to(predicted.unit)
        except UnitCompatibilityError:
            items.append(
                _item(
                    "observation_units",
                    CompatibilityStatus.MISMATCH,
                    (
                        f"Observation {observation.observation_id!r} cannot convert to "
                        f"predicted unit {predicted.unit!r}."
                    ),
                )
            )
            break
    else:
        items.append(
            _item(
                "observation_units",
                CompatibilityStatus.MATCH,
                f"All observed values convert to predicted unit {predicted.unit!r}.",
            )
        )

    try:
        predicted_times = tuple(time.to(predicted.time_unit) for time in predicted.sample_times)
    except UnitCompatibilityError:
        items.append(
            _item(
                "predicted_sample_times",
                CompatibilityStatus.MISMATCH,
                f"Predicted sample times cannot convert to {predicted.time_unit!r}.",
            )
        )
        predicted_times = ()
    if endpoint is not None:
        try:
            start, end = (
                endpoint.time_window.start.to(predicted.time_unit).value,
                endpoint.time_window.end.to(predicted.time_unit).value,
            )
            observed_times = tuple(
                observation.time.to(predicted.time_unit).value
                for observation in dataset.observations
            )
            in_window = all(
                start - _FLOAT_TOLERANCE <= time <= end + _FLOAT_TOLERANCE
                for time in observed_times
            )
            on_schedule = all(
                any(
                    isclose(time, expected.value, rel_tol=0.0, abs_tol=_FLOAT_TOLERANCE)
                    for expected in predicted_times
                )
                for time in observed_times
            )
            items.append(
                _item(
                    "sample_times",
                    CompatibilityStatus.MATCH
                    if in_window and on_schedule
                    else CompatibilityStatus.MISMATCH,
                    (
                        "Observed sample times fall within the selected PK endpoint window "
                        + "and match predicted sample times."
                        if in_window and on_schedule
                        else (
                            "Observed sample times are outside the selected PK endpoint "
                            "window or do not match predicted sample times."
                        )
                    ),
                )
            )
        except UnitCompatibilityError:
            items.append(
                _item(
                    "sample_times",
                    CompatibilityStatus.MISMATCH,
                    (
                        "Observed sample times or endpoint bounds cannot convert to the "
                        "predicted time unit."
                    ),
                )
            )

    items.append(
        _item(
            "population",
            CompatibilityStatus.LIMITATION,
            (
                "Trial population specification cannot prove comparability with the "
                "observed free-text population description."
            ),
        )
    )
    if dataset.study.study_limitations:
        items.append(
            _item(
                "study_limitations", CompatibilityStatus.LIMITATION, dataset.study.study_limitations
            )
        )
    role_status = {
        DatasetRole.EXTERNAL_VALIDATION: CompatibilityStatus.MATCH,
        DatasetRole.HELD_OUT_TEST: CompatibilityStatus.MATCH,
        DatasetRole.INTERNAL_VALIDATION: CompatibilityStatus.LIMITATION,
        DatasetRole.TRAINING: CompatibilityStatus.MISMATCH,
        DatasetRole.CALIBRATION: CompatibilityStatus.MISMATCH,
    }[dataset.role]
    items.append(_item("dataset_role", role_status, f"Dataset role is {dataset.role.value}."))

    eligibility = (
        ValidationEligibility.INELIGIBLE
        if any(item.status is CompatibilityStatus.MISMATCH for item in items)
        else ValidationEligibility.ELIGIBLE_WITH_LIMITATIONS
        if any(item.status is CompatibilityStatus.LIMITATION for item in items)
        else ValidationEligibility.ELIGIBLE
    )
    return ValidationCompatibilityReport(
        trial_id=trial.trial_id,
        dataset_id=dataset.dataset_id,
        eligibility=eligibility,
        items=tuple(items),
    )
