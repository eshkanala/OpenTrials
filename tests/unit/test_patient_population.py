from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.patient import (
    AgeRange,
    Anthropometrics,
    Demographics,
    Patient,
    PatientIdentity,
    Population,
    PopulationSpec,
    Sex,
)

CREATED_AT = datetime(2026, 8, 16, tzinfo=UTC)


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def make_spec(**changes: object) -> PopulationSpec:
    values: dict[str, object] = {
        "id": "healthy-adults-v1",
        "size": 1,
        "seed": 42,
        "generator_version": "0.1.0",
        "age_range": AgeRange(minimum=observed(18, "year"), maximum=observed(65, "year")),
        "sexes": (Sex.FEMALE, Sex.MALE),
    }
    values.update(changes)
    return PopulationSpec(**values)


def make_patient(population_id: str = "healthy-adults-v1") -> Patient:
    return Patient(
        identity=PatientIdentity(
            patient_id="VP-001",
            population_id=population_id,
            generation_seed=42,
            generator_version="0.1.0",
            created_at=CREATED_AT,
        ),
        demographics=Demographics(age=observed(32, "year"), sex=Sex.FEMALE),
        anthropometrics=Anthropometrics(
            height=observed(170, "cm"),
            weight=observed(65, "kg"),
            body_mass_index=observed(22.5, "kg/m^2"),
        ),
    )


def test_population_spec_is_seeded_and_deterministic() -> None:
    first = make_spec()
    second = make_spec()

    assert first.seed == 42
    assert first.canonical_json() == second.canonical_json()


def test_patient_identity_is_synthetic_only() -> None:
    patient = make_patient()

    assert patient.identity.is_synthetic is True
    assert '"patient_id":"VP-001"' in patient.canonical_json()


def test_demographics_reject_non_time_age() -> None:
    with pytest.raises(ValidationError, match="time dimensions"):
        Demographics(age=observed(70, "kg"))


def test_anthropometrics_reject_incompatible_dimensions() -> None:
    with pytest.raises(ValidationError, match="incompatible dimensions"):
        Anthropometrics(height=observed(75, "kg"))


def test_population_requires_matching_materialized_patients() -> None:
    population = Population(
        id="healthy-adults-v1",
        specification=make_spec(),
        patients=(make_patient(),),
        created_at=CREATED_AT,
    )

    assert population.patients[0].identity.population_id == population.id


def test_population_rejects_wrong_patient_count() -> None:
    with pytest.raises(ValidationError, match="exactly the specified"):
        Population(
            id="healthy-adults-v1",
            specification=make_spec(size=2),
            patients=(make_patient(),),
            created_at=CREATED_AT,
        )


def test_population_rejects_patient_from_another_population() -> None:
    with pytest.raises(ValidationError, match="containing population"):
        Population(
            id="healthy-adults-v1",
            specification=make_spec(),
            patients=(make_patient(population_id="other-population"),),
            created_at=CREATED_AT,
        )
