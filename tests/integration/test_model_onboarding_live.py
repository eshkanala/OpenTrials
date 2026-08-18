"""Opt-in live proof: model discovery against the real bundled Aciclovir PKML.

Confirms `inspect_model()` finds real, correct facts by cross-checking
them against the already hand-verified constants in
``models/profiles/aciclovir_iv.py`` -- discovery should reproduce exactly
what was manually verified there, not merely produce plausible-looking
output.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.sdk.model_onboarding import generate_profile_scaffold, inspect_model

pytestmark = pytest.mark.osp_integration


def test_inspect_model_rediscovers_the_already_verified_aciclovir_paths() -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    parsed = urlparse(ACICLOVIR_IV_CAPABILITY_PROFILE.package.artifact_uri)
    pkml_path = Path(unquote(parsed.path))
    administration = ACICLOVIR_IV_CAPABILITY_PROFILE.administrations[0]
    output = ACICLOVIR_IV_CAPABILITY_PROFILE.outputs[0]

    report = inspect_model(pkml_path, r_libs_user=r_libs_user)

    assert report.pkml_sha256 == ACICLOVIR_IV_CAPABILITY_PROFILE.package.artifact_hash
    assert "Aciclovir" in report.molecule_names
    assert len(report.administrations) == 1
    discovered = report.administrations[0]
    assert discovered.container == administration.administration_container_path
    assert discovered.roles["dose"] == administration.dose_parameter_path
    assert discovered.roles["start_time"] == administration.administration_time_parameter_path
    assert (
        discovered.roles["infusion_duration"]
        == administration.infusion_duration_parameter_path
    )
    assert output.parameter_path in report.output_paths
    assert report.population_support_detected is True
    assert report.mutable_parameter_count > 0

    scaffold = generate_profile_scaffold(report, model_id="live-test.scaffold")
    assert administration.dose_parameter_path in scaffold
    assert report.pkml_sha256 in scaffold
