import pytest
from pydantic import ValidationError

from opentrials.compound import (
    Compound,
    CompoundIdentity,
    Dose,
    Intervention,
    Regimen,
    Route,
)
from opentrials.core.scientific_value import ScientificValue, ValueType


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def make_compound() -> Compound:
    return Compound(
        identity=CompoundIdentity(
            compound_id="aciclovir",
            preferred_name="Aciclovir",
            canonical_smiles="C1=NC2=C(N1CO)NC(=NC2=O)NCCO",
            external_identifiers={"ChEMBL": "CHEMBL184"},
        ),
        molecular_weight=observed(225.2, "g/mol"),
        physicochemical_properties={"log_p": observed(-1.56, "dimensionless")},
        evidence_ids=("evidence-aciclovir-001",),
    )


def make_dose(time_hours: float = 0.0) -> Dose:
    return Dose(
        amount=observed(400, "mg"),
        route=Route.ORAL,
        administration_time=observed(time_hours, "hour"),
    )


def test_compound_retains_identity_and_evidence() -> None:
    compound = make_compound()

    assert compound.identity.compound_id == "aciclovir"
    assert compound.evidence_ids == ("evidence-aciclovir-001",)
    assert '"preferred_name":"Aciclovir"' in compound.canonical_json()


def test_dose_requires_mass_amount_and_time() -> None:
    with pytest.raises(ValidationError, match="mass dimensions"):
        Dose(
            amount=observed(4, "mL"),
            route=Route.ORAL,
            administration_time=observed(0, "hour"),
        )

    with pytest.raises(ValidationError, match="time dimensions"):
        Dose(
            amount=observed(400, "mg"),
            route=Route.ORAL,
            administration_time=observed(4, "mL"),
        )


def test_infusion_duration_requires_a_positive_intravenous_time() -> None:
    dose = Dose(
        amount=observed(250, "mg"),
        route=Route.INTRAVENOUS,
        administration_time=observed(0, "min"),
        infusion_duration=observed(10, "min"),
    )

    assert dose.infusion_duration is not None
    assert dose.infusion_duration.to("minute").value == 10

    with pytest.raises(ValidationError, match="only for intravenous"):
        Dose(
            amount=observed(250, "mg"),
            route=Route.ORAL,
            administration_time=observed(0, "min"),
            infusion_duration=observed(10, "min"),
        )
    with pytest.raises(ValidationError, match="greater than zero"):
        Dose(
            amount=observed(250, "mg"),
            route=Route.INTRAVENOUS,
            administration_time=observed(0, "min"),
            infusion_duration=observed(0, "min"),
        )


def test_regimen_requires_chronological_doses_within_duration() -> None:
    regimen = Regimen(
        regimen_id="aciclovir-400-mg-tid",
        doses=(make_dose(0), make_dose(8), make_dose(16)),
        duration=observed(24, "hour"),
    )

    assert len(regimen.doses) == 3

    with pytest.raises(ValidationError, match="ordered"):
        Regimen(regimen_id="out-of-order", doses=(make_dose(8), make_dose(0)))

    with pytest.raises(ValidationError, match="after the regimen duration"):
        Regimen(
            regimen_id="after-duration",
            doses=(make_dose(25),),
            duration=observed(24, "hour"),
        )


def test_intervention_combines_compound_and_regimen() -> None:
    intervention = Intervention(
        intervention_id="aciclovir-400-mg-oral",
        compound=make_compound(),
        regimen=Regimen(regimen_id="single-dose", doses=(make_dose(),)),
    )

    assert intervention.compound.identity.preferred_name == "Aciclovir"
    assert intervention.regimen.doses[0].route is Route.ORAL
