"""Opt-in inspection of the bundled aciclovir PKML administration structure."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT

pytestmark = pytest.mark.osp_integration


def test_bundled_aciclovir_model_has_only_an_iv_administration_event() -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to inspect local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")
    expression = (
        "suppressPackageStartupMessages(library(ospsuite)); "
        'path <- system.file("extdata", "Aciclovir.pkml", package = "ospsuite"); '
        "simulation <- loadSimulation(path); "
        'events <- Filter(function(path) startsWith(path, "Events|"), '
        "getAllParameterPathsIn(simulation)); "
        "cat(jsonlite::toJSON(list(name = simulation$name, "
        "event_paths = events), auto_unbox = TRUE))"
    )
    environment = os.environ.copy()
    environment["DOTNET_ROOT"] = DEFAULT_DOTNET_ROOT
    environment["R_LIBS_USER"] = r_libs_user
    completed = subprocess.run(
        [str(DEFAULT_FRAMEWORK_RSCRIPT), "-e", expression],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    inspection = json.loads(completed.stdout)
    event_paths = inspection["event_paths"]
    assert inspection["name"] == "Vergin 1995 IV"
    assert event_paths
    assert all(path.startswith("Events|IV 250mg 10min|") for path in event_paths)
    assert not any("oral" in path.lower() for path in event_paths)
