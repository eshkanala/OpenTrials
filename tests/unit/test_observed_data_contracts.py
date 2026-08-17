import pytest
from pydantic import ValidationError

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def aciclovir_intervention() -> Intervention:
    compound = Compound(
        identity=CompoundIdentity(
            compound_id="aciclovir",
            preferred_name="Aciclovir",
            canonical_smiles="C1=NC2=C(N1CO)NC(=NC2=O)NCCO",
        ),
        molecular_weight=observed(225.2, "g/mol"),
        evidence_ids=("evidence-aciclovir",),
    )
    dose = Dose(
        amount=observed(250, "mg"),
        route=Route.INTRAVENOUS,
        administration_time=observed(0, "minute"),
    )
    return Intervention(
        intervention_id="aciclovir-iv-250-mg",
        compound=compound,
        regimen=Regimen(regimen_id="aciclovir-iv-single-dose", doses=(dose,)),
        evidence_ids=("evidence-regimen",),
    )


def pk_observation(observation_id: str = "observation-001") -> ObservedPkObservation:
    return ObservedPkObservation(
        observation_id=observation_id,
        subject_or_population_id="subject-001",
        time=observed(30, "minute"),
        value=observed(4.2, "mg/L"),
        analyte="aciclovir",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
        assay="LC-MS/MS",
        evidence_ids=("evidence-observation-001",),
    )


def observed_dataset(
    observations: tuple[ObservedPkObservation, ...] | None = None,
) -> ObservedDataset:
    study = ObservedStudy(
        study_id="study-aciclovir-iv-001",
        title="Aciclovir intravenous pharmacokinetics",
        evidence_ids=("evidence-study-001",),
        population_description="Adults with normal renal function",
        intervention=aciclovir_intervention(),
        assay_context="Plasma aciclovir measured by LC-MS/MS.",
    )
    return ObservedDataset(
        dataset_id="aciclovir-iv-observed-001",
        role=DatasetRole.EXTERNAL_VALIDATION,
        study=study,
        observations=observations or (pk_observation(),),
        license="CC-BY-4.0",
        source_identifier="doi:10.0000/aciclovir-iv",
        provenance_ids=("provenance-001",),
    )


def test_observed_dataset_retains_external_validation_role() -> None:
    dataset = observed_dataset()

    assert dataset.role is DatasetRole.EXTERNAL_VALIDATION
    assert dataset.study.intervention.regimen.doses[0].route is Route.INTRAVENOUS


def test_observed_dataset_rejects_duplicate_observation_ids() -> None:
    duplicate = pk_observation().model_copy(update={"subject_or_population_id": "subject-002"})

    with pytest.raises(ValidationError, match="observation IDs must be unique"):
        observed_dataset((pk_observation(), duplicate))


def test_observed_pk_observation_requires_evidence() -> None:
    observation_data = pk_observation().model_dump()
    observation_data["evidence_ids"] = ()

    with pytest.raises(ValidationError, match="at least 1 item"):
        ObservedPkObservation.model_validate(observation_data)


def test_observed_pk_observation_rejects_non_time_units() -> None:
    with pytest.raises(ValidationError, match="time dimensions"):
        ObservedPkObservation(
            observation_id="observation-invalid-time",
            subject_or_population_id="subject-001",
            time=observed(2, "mL"),
            value=observed(4.2, "mg/L"),
            analyte="aciclovir",
            matrix="plasma",
            fraction="total",
            measurement="concentration",
            evidence_ids=("evidence-observation-001",),
        )
