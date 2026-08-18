"""Opt-in live proof: the v0.8-B/C Laskin 1982 ineligibility finding, against real OSP.

Confirms the finding holds against the actual bundled file read live through
OSP, not just a previously-captured fixture: the second, genuinely
independent observed dataset's weight-normalized dose cannot be represented
as an OpenTrials Intervention, so this candidate is correctly refused before
ever reaching the compatibility gate.
"""

from __future__ import annotations

import os

import pytest

from opentrials.evidence.connector import IneligibleEvidenceCandidateError, run_connector
from opentrials.evidence.connectors.osp_bundled_laskin_1982 import OspBundledLaskin1982Connector

pytestmark = pytest.mark.osp_integration


def test_laskin_1982_is_ineligible_when_read_live_from_the_bundled_pkml() -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    connector = OspBundledLaskin1982Connector(r_libs_user=r_libs_user)
    with pytest.raises(IneligibleEvidenceCandidateError, match="mg/kg"):
        run_connector(connector)
