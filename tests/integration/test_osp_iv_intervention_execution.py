"""Opt-in proof that verified OpenTrials IV assignments control OSP execution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentrials.adapters.osp import OspParameterAssignment, OspSimulationEngine
from opentrials.analysis import PkEndpointType, calculate_pk_endpoints
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType
from opentrials.patient import PopulationSpec
from opentrials.storage import (
    PkEndpointArtifactStore,
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
)
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

PKML_PATH = Path("/Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/Aciclovir.pkml")
PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"

pytestmark = pytest.mark.osp_integration


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def iv_trial(dose_mg: float) -> Trial:
    intervention = Intervention(
        intervention_id=f"aciclovir-{dose_mg:g}-mg-iv",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id=f"aciclovir-{dose_mg:g}-mg-iv-regimen",
            doses=(
                Dose(
                    amount=assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                    infusion_duration=assumed(10, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id=f"aciclovir-{dose_mg:g}-mg-iv-engineering",
        title="Aciclovir IV OSP engineering integration",
        question_of_interest="Does verified IV assignment control the OSP model?",
        population=PopulationSpec(id="one-adult", size=1, seed=42, generator_version="0.1.0"),
        arms=(TrialArm(arm_id="iv", name="IV", intervention=intervention, allocation=1),),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "h"), end=assumed(24, "h")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="raw OSP engineering output",
                unit="umol/L",
            ),
        ),
        seed=42,
    )


def package() -> ModelPackage:
    return ModelPackage(
        manifest=ModelManifest(
            id="osp.aciclovir.vergin-1995-iv",
            version="12.4.4",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "umol/L"},
            applicability=Applicability(species=("human",)),
            license="Bundled ospsuite example; redistribution not asserted.",
        ),
        artifact_uri=PKML_PATH.as_uri(),
        artifact_hash=f"sha256:{PKML_SHA256}",
        parameter_set_id="vergin-1995-iv-as-packaged",
        parameter_hash=f"sha256:{PKML_SHA256}",
        package_hash=f"sha256:{PKML_SHA256}",
    )


def assignments(dose_mg: float) -> tuple[OspParameterAssignment, ...]:
    return (
        OspParameterAssignment(
            parameter_path=f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Dose",
            value=dose_mg / 1_000_000,
            unit="kg",
            source_field="regimen.doses[0].amount",
        ),
        OspParameterAssignment(
            parameter_path=f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Start time",
            value=0,
            unit="min",
            source_field="regimen.doses[0].administration_time",
        ),
        OspParameterAssignment(
            parameter_path=f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Infusion time",
            value=10,
            unit="min",
            source_field="regimen.doses[0].infusion_duration",
        ),
    )


def run_verified(dose_mg: float) -> object:
    engine = OspSimulationEngine(r_libs_user=os.environ["OPENTRIALS_OSP_R_LIBS_USER"])
    prepared = engine.prepare(f"OTR-osp-iv-{dose_mg:g}", (package(),), iv_trial(dose_mg))
    return engine.run(
        prepared,
        expected_pkml_sha256=PKML_SHA256,
        expected_administration_container=IV_CONTAINER,
        parameter_assignments=assignments(dose_mg),
    )


def test_verified_iv_perturbation_changes_osp_raw_output(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    if "OPENTRIALS_OSP_R_LIBS_USER" not in os.environ:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")
    if not PKML_PATH.is_file():
        pytest.skip(f"Bundled OSP aciclovir PKML is not available: {PKML_PATH}")

    baseline = run_verified(250)
    perturbed = run_verified(125)

    baseline_original_dose = baseline.payload["execution_verification"]["parameter_assignments"][0][
        "original"
    ]
    perturbed_original_dose = perturbed.payload["execution_verification"]["parameter_assignments"][
        0
    ]["original"]
    assert baseline_original_dose == perturbed_original_dose

    for result, dose_mg in ((baseline, 250), (perturbed, 125)):
        verification = result.payload["execution_verification"]
        assert verification["model_hash_verification"]["verified"] is True
        assert verification["route_container_verification"]["verified"] is True
        assert verification["solver_executed"] is True
        assert all(item["verified"] is True for item in verification["parameter_assignments"])
        assert verification["parameter_assignments"][0]["executed"]["value"] == dose_mg / 1_000_000
        assert result.payload["raw_result_rows"]

    assert (
        perturbed_original_dose["value"]
        != perturbed.payload["execution_verification"]["parameter_assignments"][0]["executed"][
            "value"
        ]
    )
    assert baseline.payload["raw_result_rows"] != perturbed.payload["raw_result_rows"]

    normalized_endpoint_values: list[dict[PkEndpointType, float]] = []
    selection = ResultSelectionMapping(
        source_path=TOTAL_PLASMA_PATH,
        analyte="aciclovir",
        matrix="peripheral venous plasma",
        fraction="total",
        measurement="concentration",
        time_unit="min",
    )
    for result, dose_mg in ((baseline, 250), (perturbed, 125)):
        result_id = f"OTRES-osp-iv-{dose_mg:g}"
        result_store = ResultArtifactStore(tmp_path / "results")
        result_store.create_result(result_id)
        selected_rows = tuple(
            row for row in result.payload["raw_result_rows"] if row["paths"] == TOTAL_PLASMA_PATH
        )
        result_manifest = result_store.write_concentration_time(
            result_id,
            source_raw_result=result.payload,
            raw_rows=selected_rows,
            engine_id="osp",
            model_id=package().manifest.id,
            run_id=result.run_id,
            selection=selection,
        )
        assert result_store.verify_result(result_id) == result_manifest
        normalized_rows = normalize_osp_concentration_time_rows(selected_rows, selection)
        endpoints = calculate_pk_endpoints(
            normalized_rows, result_manifest.concentration_time.semantic_content_sha256
        )
        endpoint_store = PkEndpointArtifactStore(tmp_path / "endpoints")
        endpoint_id = f"OTPK-osp-iv-{dose_mg:g}"
        endpoint_store.create_endpoint_artifact(endpoint_id)
        endpoint_manifest = endpoint_store.write_endpoints(
            endpoint_id,
            endpoints=endpoints,
            source_result_semantic_sha256=result_manifest.concentration_time.semantic_content_sha256,
            source_result_id=result_id,
            run_id=result.run_id,
            source_engine_id="osp",
            source_model_id=package().manifest.id,
        )
        assert endpoint_store.verify_endpoints(endpoint_id) == endpoint_manifest
        normalized_endpoint_values.append(
            {endpoint.endpoint_type: endpoint.value for endpoint in endpoints}
        )

    assert normalized_endpoint_values[0] != normalized_endpoint_values[1]
