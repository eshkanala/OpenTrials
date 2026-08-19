"""The registered capability profile for the converted Midazolam oral tablet model.

v0.7-C's second registered profile -- deliberately chosen to stress
``ModelCapabilityProfile`` differently from the aciclovir profile: a
different compound, hepatic/gut CYP3A4+UGT1A4 metabolism (not renal
filtration), and an oral tablet route (not IV). Every value here was read
back from a real, live execution against the converted Midazolam.pkml --
see scripts/MIDAZOLAM_CONVERSION.md for the conversion provenance and
tests/integration/test_midazolam_po_pbpk.py for the live proof that it
runs through the generic execution pipeline unmodified.
"""

from __future__ import annotations

from opentrials.compound.intervention import Route
from opentrials.models.capability import (
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
    UnsupportedCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage

PKML_SHA256 = "394f05112be1a5197f2d4e6a52ebce950e32f0c5840192fa5127f055c6589cec"
PO_CONTAINER = "Events|po 10 mg|Tablet (Dormicum)|"
TOTAL_PLASMA_PATH = "Organism|PeripheralVenousBlood|Midazolam|Plasma (Peripheral Venous Blood)"

MIDAZOLAM_PO_CAPABILITY_PROFILE = ModelCapabilityProfile(
    package=ModelPackage(
        manifest=ModelManifest(
            id="osp.midazolam.po-10mg-tablet",
            version="12.4.4",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": "umol/L"},
            applicability=Applicability(species=("human",)),
            license="GPL-2.0 (Open-Systems-Pharmacology/Midazolam-Model, tag v1.1).",
        ),
        artifact_uri=(
            "file:///Users/eshkanala/Library/OpenTrials/models/midazolam/Midazolam.pkml"
        ),
        artifact_hash=f"sha256:{PKML_SHA256}",
        parameter_set_id="midazolam-model-v1.1-po-10mg-tablet",
        parameter_hash=f"sha256:{PKML_SHA256}",
        package_hash=f"sha256:{PKML_SHA256}",
    ),
    compounds=(
        CompoundCapability(compound_id="midazolam", engine_molecule_id="Midazolam"),
    ),
    administrations=(
        AdministrationCapability(
            target_id="po-10mg-tablet",
            compound_id="midazolam",
            route=Route.ORAL,
            administration_container_path=PO_CONTAINER,
            dose_parameter_path=f"{PO_CONTAINER}Application_1|ProtocolSchemaItem|Dose",
            dose_unit="kg",
            administration_time_parameter_path=(
                f"{PO_CONTAINER}Application_1|ProtocolSchemaItem|Start time"
            ),
            administration_time_unit="min",
            infusion_duration_parameter_path=None,
            infusion_duration_unit=None,
            supported_doses=(10.0,),
            supported_dose_unit="mg",
            fixed_administration_time_min=0.0,
        ),
    ),
    physiology_targets=(),
    outputs=(
        OutputCapability(
            output_id="total-plasma-concentration",
            parameter_path=TOTAL_PLASMA_PATH,
            analyte="midazolam",
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
                "ospsuite's R API has no dosing-protocol-authoring function -- the same "
                "confirmed limitation already recorded on the registered aciclovir "
                "profile (see HANDOFF v0.5)."
            ),
        ),
        UnsupportedCapability(
            capability="intravenous_route",
            reason=(
                "This registered profile is built from the snapshot's 'po 10 mg "
                "(tablet)' simulation only. The same snapshot declares IV protocols "
                "too, but none has been inspected, verified, or registered here -- "
                "registering one would require its own review, not an assumption "
                "that the oral protocol's verified values carry over."
            ),
        ),
    ),
)
