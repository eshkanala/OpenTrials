"""Self-consistency checks for the registered aciclovir capability profile.

Before v0.7-B, orchestration kept its own hard-coded copies of these values
and this test drift-guarded the registered profile against them. v0.7-B
removed the duplication: orchestration now reads every one of these values
*from* ``ACICLOVIR_IV_CAPABILITY_PROFILE`` itself, so there is no longer a
second, independent representation to drift-guard against. What remains
worth verifying here is that the profile's own declared fields are
internally consistent, and that the generic OSP-side capability resolvers
correctly read whatever profile they are handed.
"""

from __future__ import annotations

from opentrials.adapters.osp import physiology_coverage_for, resolve_osp_physiology_column
from opentrials.adapters.osp.capability import osp_intervention_profile_from_capability
from opentrials.models.profiles.aciclovir_iv import (
    ACICLOVIR_IV_CAPABILITY_PROFILE,
    IV_CONTAINER,
    PKML_SHA256,
    TOTAL_PLASMA_PATH,
)
from opentrials.physiology import RENAL_GLOMERULAR_FILTRATION_RATE

PROFILE = ACICLOVIR_IV_CAPABILITY_PROFILE


def test_package_identity_is_self_consistent() -> None:
    package = PROFILE.package
    assert package.artifact_hash == f"sha256:{PKML_SHA256}"
    assert package.parameter_hash == f"sha256:{PKML_SHA256}"
    assert package.package_hash == f"sha256:{PKML_SHA256}"
    assert package.manifest.id == "osp.aciclovir.vergin-1995-iv"
    assert package.manifest.engine == "osp"
    assert "human" in package.manifest.applicability.species


def test_administration_declares_the_one_verified_iv_target() -> None:
    administration = PROFILE.administrations[0]
    assert administration.administration_container_path == IV_CONTAINER
    assert administration.dose_parameter_path.startswith(IV_CONTAINER)
    assert administration.administration_time_parameter_path.startswith(IV_CONTAINER)
    assert administration.infusion_duration_parameter_path.startswith(IV_CONTAINER)
    assert administration.supported_doses == (125.0, 250.0)
    assert administration.supported_dose_unit == "mg"
    assert administration.fixed_administration_time_min == 0.0
    assert administration.fixed_infusion_duration_min == 10.0


def test_compound_maps_to_the_engine_molecule_the_administration_references() -> None:
    compound = PROFILE.compounds[0]
    administration = PROFILE.administrations[0]
    assert compound.compound_id == "aciclovir"
    assert administration.compound_id == compound.compound_id
    osp_profile = osp_intervention_profile_from_capability(PROFILE)
    assert osp_profile.compound_mappings[0].osp_molecule_id == compound.engine_molecule_id
    assert osp_profile.administration_targets[0].osp_molecule_id == compound.engine_molecule_id


def test_output_matches_the_registered_result_selection_path() -> None:
    assert PROFILE.outputs[0].parameter_path == TOTAL_PLASMA_PATH


def test_physiology_target_resolvers_read_from_the_given_profile() -> None:
    declared = PROFILE.physiology_targets[0]
    assert declared.target == RENAL_GLOMERULAR_FILTRATION_RATE

    assert (
        resolve_osp_physiology_column(PROFILE, RENAL_GLOMERULAR_FILTRATION_RATE)
        == declared.parameter_path
    )
    coverage = physiology_coverage_for(PROFILE, RENAL_GLOMERULAR_FILTRATION_RATE)
    assert coverage.modeled == declared.modeled
    assert coverage.unmodeled == declared.unmodeled
    assert coverage.interpretation == declared.interpretation


def test_repeated_dosing_is_declared_as_an_unsupported_capability() -> None:
    capabilities = {item.capability for item in PROFILE.unsupported_capabilities}
    assert "repeated_dosing" in capabilities
