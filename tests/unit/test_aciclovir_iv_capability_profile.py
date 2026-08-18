"""Drift guard: the registered aciclovir profile must match orchestration's own constants.

Until v0.7-B has orchestration read from the registered profile instead of
its own hard-coded constants, these two representations exist in parallel.
This test is what keeps them honest in the meantime -- if either changes
without the other, this fails immediately, the same discipline this project
already applies to every other duplicated-by-necessity value.
"""

from __future__ import annotations

from opentrials.adapters.osp.physiology_targets import (
    OSP_PHYSIOLOGY_TARGET_COLUMNS,
    RENAL_GLOMERULAR_FILTRATION_RATE,
    physiology_coverage_for,
)
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.orchestration.aciclovir_iv_population import (
    IV_CONTAINER,
    PKML_PATH,
    PKML_SHA256,
    SUPPORTED_DOSES_MG,
    TOTAL_PLASMA_PATH,
    _intervention_profile,
    _model_package,
)


def test_package_identity_matches_the_live_orchestration_constants() -> None:
    orchestration_package = _model_package()
    profile_package = ACICLOVIR_IV_CAPABILITY_PROFILE.package

    assert profile_package.artifact_hash == f"sha256:{PKML_SHA256}"
    assert profile_package.artifact_uri == PKML_PATH.as_uri()
    assert profile_package.manifest.id == orchestration_package.manifest.id
    assert profile_package.manifest.version == orchestration_package.manifest.version
    assert profile_package.manifest.engine == orchestration_package.manifest.engine
    assert profile_package.manifest.units == orchestration_package.manifest.units
    assert (
        profile_package.manifest.applicability.species
        == orchestration_package.manifest.applicability.species
    )


def test_administration_matches_the_live_intervention_profile() -> None:
    orchestration_target = _intervention_profile().administration_targets[0]
    profile_administration = ACICLOVIR_IV_CAPABILITY_PROFILE.administrations[0]

    assert profile_administration.target_id == orchestration_target.target_id
    assert profile_administration.route == orchestration_target.route
    assert profile_administration.administration_container_path == IV_CONTAINER
    assert profile_administration.dose_parameter_path == orchestration_target.dose_parameter_path
    assert profile_administration.dose_unit == orchestration_target.dose_unit
    assert (
        profile_administration.administration_time_parameter_path
        == orchestration_target.administration_time_parameter_path
    )
    assert (
        profile_administration.administration_time_unit
        == orchestration_target.administration_time_unit
    )
    assert (
        profile_administration.infusion_duration_parameter_path
        == orchestration_target.infusion_duration_parameter_path
    )
    assert (
        profile_administration.infusion_duration_unit
        == orchestration_target.infusion_duration_unit
    )
    assert profile_administration.supported_doses == SUPPORTED_DOSES_MG
    assert profile_administration.supported_dose_unit == "mg"


def test_compound_mapping_matches_the_live_intervention_profile() -> None:
    orchestration_mapping = _intervention_profile().compound_mappings[0]
    profile_compound = ACICLOVIR_IV_CAPABILITY_PROFILE.compounds[0]

    assert profile_compound.compound_id == orchestration_mapping.opentrials_compound_id
    assert profile_compound.engine_molecule_id == orchestration_mapping.osp_molecule_id


def test_output_matches_the_live_result_selection_path() -> None:
    profile_output = ACICLOVIR_IV_CAPABILITY_PROFILE.outputs[0]
    assert profile_output.parameter_path == TOTAL_PLASMA_PATH


def test_physiology_target_matches_the_live_registered_osp_mapping() -> None:
    profile_target = ACICLOVIR_IV_CAPABILITY_PROFILE.physiology_targets[0]
    coverage = physiology_coverage_for(RENAL_GLOMERULAR_FILTRATION_RATE)

    assert profile_target.target == RENAL_GLOMERULAR_FILTRATION_RATE
    assert (
        profile_target.parameter_path
        == OSP_PHYSIOLOGY_TARGET_COLUMNS[RENAL_GLOMERULAR_FILTRATION_RATE]
    )
    assert profile_target.modeled == coverage.modeled
    assert profile_target.unmodeled == coverage.unmodeled
    assert profile_target.interpretation == coverage.interpretation


def test_repeated_dosing_is_declared_as_an_unsupported_capability() -> None:
    capabilities = {
        item.capability for item in ACICLOVIR_IV_CAPABILITY_PROFILE.unsupported_capabilities
    }
    assert "repeated_dosing" in capabilities
