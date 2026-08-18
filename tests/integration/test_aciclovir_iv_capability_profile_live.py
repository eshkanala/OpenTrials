"""Opt-in live proof: the registered profile's hash matches the real bundled PKML.

Doesn't need R itself -- just the local file this project's one verified
macOS OSP environment installs it to -- but gated behind the same
``OPENTRIALS_RUN_OSP_INTEGRATION``/``OPENTRIALS_OSP_R_LIBS_USER`` switches as
every other test that depends on that specific local layout, for
consistency.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE

pytestmark = pytest.mark.osp_integration


def test_registered_hash_matches_the_actual_bundled_pkml_bytes() -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    if os.environ.get("OPENTRIALS_OSP_R_LIBS_USER") is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    parsed = urlparse(ACICLOVIR_IV_CAPABILITY_PROFILE.package.artifact_uri)
    pkml_path = Path(unquote(parsed.path))
    assert pkml_path.is_file(), f"Registered artifact_uri does not exist on disk: {pkml_path}"

    actual_hash = "sha256:" + hashlib.sha256(pkml_path.read_bytes()).hexdigest()
    assert actual_hash == ACICLOVIR_IV_CAPABILITY_PROFILE.package.artifact_hash
