from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType
from opentrials.patient import PopulationSpec
from opentrials.simulation import MockSimulationEngine
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    RandomizationType,
    TimeWindow,
    Trial,
    TrialArm,
)

HASH = "sha256:" + "d" * 64


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def trial() -> Trial:
    intervention = Intervention(
        intervention_id="demo-intervention",
        compound=Compound(identity=CompoundIdentity(compound_id="demo", preferred_name="Demo")),
        regimen=Regimen(
            regimen_id="demo-regimen",
            doses=(
                Dose(
                    amount=observed(1, "mg"),
                    route=Route.ORAL,
                    administration_time=observed(0, "hour"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id="demo-trial",
        title="Demo trial",
        question_of_interest="Does the engine satisfy its contract?",
        population=PopulationSpec(id="demo-pop", size=1, seed=42, generator_version="0.1.0"),
        arms=(TrialArm(arm_id="arm", name="Arm", intervention=intervention, allocation=1.0),),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="concentration",
                endpoint_type=EndpointType.PK,
                measurement="concentration",
                time_window=TimeWindow(start=observed(0, "hour"), end=observed(1, "hour")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="none",
                unit="mg/L",
            ),
        ),
        seed=42,
    )


def package() -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="mock.demo",
            version="1.0.0",
            model_type=ModelType.PBPK,
            engine="mock",
            inputs=("dose",),
            outputs=("concentration",),
            units={"concentration": "mg/L"},
            applicability=Applicability(species=("human",)),
            license="Apache-2.0",
        ),
        artifact_uri="mock://demo",
        artifact_hash=HASH,
        parameter_set_id="default",
        parameter_hash=HASH,
        package_hash=HASH,
    )


def test_mock_engine_has_no_biological_outputs() -> None:
    engine = MockSimulationEngine()
    prepared = engine.prepare("OTR-mock-001", (package(),), trial())
    raw = engine.run(prepared)
    result = engine.extract(raw)

    assert raw.payload["kind"] == "mock"
    assert not result.artifact_uris
    assert "no biological simulation output" in result.warnings[0]


def test_mock_engine_rejects_an_empty_package_set() -> None:
    validation = MockSimulationEngine().validate((), trial())

    assert validation.is_valid is False
    assert "At least one model package" in validation.errors[0]
