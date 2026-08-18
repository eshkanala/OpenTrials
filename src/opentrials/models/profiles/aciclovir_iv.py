"""The registered capability profile for the pinned Aciclovir IV model.

This is the first, and so far only, registered profile -- the "reference
implementation" v0.7 explicitly keeps aciclovir as. Every OSP-specific value
here (PKML hash, parameter paths) is the same value the execution pipeline
now reads *from this profile* rather than from its own hard-coded constants
(v0.7-B removed the duplication v0.7-A's drift-guard test was written to
catch); nothing here is invented.
"""

from __future__ import annotations

from opentrials.compound.intervention import Route
from opentrials.models.capability import (
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
    PhysiologyTargetCapability,
    UnsupportedCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.physiology import RENAL_GLOMERULAR_FILTRATION_RATE

PKML_SHA256 = "efbc7a3004534780bab46ca75a15dfd37ee271d4b8eec8c304b7ef5a2f083de7"
IV_CONTAINER = "Events|IV 250mg 10min|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"

ACICLOVIR_IV_CAPABILITY_PROFILE = ModelCapabilityProfile(
    package=ModelPackage(
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
        artifact_uri=(
            "file:///Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/"
            "Aciclovir.pkml"
        ),
        artifact_hash=f"sha256:{PKML_SHA256}",
        parameter_set_id="vergin-1995-iv-as-packaged",
        parameter_hash=f"sha256:{PKML_SHA256}",
        package_hash=f"sha256:{PKML_SHA256}",
    ),
    compounds=(
        CompoundCapability(compound_id="aciclovir", engine_molecule_id="Aciclovir"),
    ),
    administrations=(
        AdministrationCapability(
            target_id="iv-250mg-10min",
            compound_id="aciclovir",
            route=Route.INTRAVENOUS,
            administration_container_path=IV_CONTAINER,
            dose_parameter_path=f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Dose",
            dose_unit="kg",
            administration_time_parameter_path=(
                f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Start time"
            ),
            administration_time_unit="min",
            infusion_duration_parameter_path=(
                f"{IV_CONTAINER}Application_1|ProtocolSchemaItem|Infusion time"
            ),
            infusion_duration_unit="min",
            supported_doses=(125.0, 250.0),
            supported_dose_unit="mg",
            fixed_administration_time_min=0.0,
            fixed_infusion_duration_min=10.0,
        ),
    ),
    physiology_targets=(
        PhysiologyTargetCapability(
            target=RENAL_GLOMERULAR_FILTRATION_RATE,
            parameter_path="Organism|Kidney|GFRmat",
            unit="L/min",
            modeled=("renal.glomerular_filtration",),
            unmodeled=(
                "renal.tubular_secretion",
                "renal.blood_flow",
                "renal.protein_binding_effects",
            ),
            interpretation=(
                "Only glomerular filtration was perturbed, via a direct scale of the "
                "model's own per-individual GFRmat parameter. Tubular secretion and "
                "other renal-clearance pathways were left unmodified. This is a "
                "verified physiological-parameter perturbation, not a disease-state "
                "(e.g. CKD or renal impairment) claim -- a complete renal-impairment "
                "phenotype would need to also scale tubular secretion and other "
                "renal mechanisms, which this override does not do."
            ),
        ),
    ),
    outputs=(
        OutputCapability(
            output_id="total-plasma-concentration",
            parameter_path=TOTAL_PLASMA_PATH,
            analyte="aciclovir",
            matrix="peripheral venous plasma",
            fraction="total",
            measurement="concentration",
            unit="umol/L",
            time_unit="min",
        ),
    ),
    unsupported_capabilities=(
        UnsupportedCapability(
            capability="repeated_dosing",
            reason=(
                "ospsuite's R API has no dosing-protocol-authoring function -- confirmed "
                "by enumerating all 163 exported functions (see HANDOFF v0.5). Only "
                "parameter mutation on an already-built protocol is possible."
            ),
        ),
        UnsupportedCapability(
            capability="oral_route",
            reason="No compatible, rights-cleared oral aciclovir model is available locally.",
        ),
    ),
)
