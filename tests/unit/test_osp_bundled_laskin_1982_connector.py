"""Contract test proving Laskin 1982's weight-based dose is genuinely ineligible.

This is the v0.8-B/C evidence-acquisition finding, made concrete and
reproducible: a second, genuinely independent bundled observed dataset
(Laskin et al. 1982 -- confirmed absent from the pinned Aciclovir model's
own PKML, unlike Vergin 1995) cannot be represented as an OpenTrials
``Intervention`` at all, because its dose is reported per body weight
(mg/kg) with no subject weight available anywhere accessible to convert it
to an absolute mass. ``compound.intervention.Dose`` correctly refuses a
non-mass amount; this connector surfaces that as a clear
``IneligibleEvidenceCandidateError`` rather than inventing a body weight.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from opentrials.evidence.connector import IneligibleEvidenceCandidateError, RawSnapshot
from opentrials.evidence.connectors.osp_bundled_laskin_1982 import OspBundledLaskin1982Connector

# A real, previously-captured response from adapters/osp/read_observed_dataset.R
# reading the actual bundled ObsDataAciclovir_2.pkml (Laskin 1982, Group D) --
# every field here is a real value read from OSP, not invented.
REAL_PAYLOAD = {
    "status": "SUCCEEDED",
    "generated_at": "2026-08-18T16:17:43Z",
    "r_version": "R version 4.6.1 (2026-06-24)",
    "ospsuite_version": "12.4.4",
    "name": "Laskin 1982.Group D",
    "x_unit": "h",
    "y_unit": "mg/l",
    "x_dimension": "Time",
    "y_dimension": "Concentration (mass)",
    "y_error_unit": "",
    "y_error_type": "GeometricStdDev",
    "mol_weight": 225.21,
    "metadata": {
        "Source": "X:\\Orga\\BTS-TD\\ET\\TP CSB\\Projects\\Internal Projects\\MagenDarm\\"
        "TestSubstanzen\\Acyclovir\\Rohdaten_Acyclovir.xls.Laskin 1982 15.0 mg per kg",
        "File": "Rohdaten_Acyclovir",
        "Sheet": "Laskin 1982 15.0 mg per kg",
        "Molecule": "Aciclovir",
        "Species": "Human",
        "Organ": "Peripheral Venous Blood",
        "Compartment": "Plasma",
        "Study Id": "Laskin 1982",
        "Gender": "Undefined",
        "Dose": "15 mg/kg",
        "Route": "IV",
        "Patient Id": "Group D",
    },
    "x_values": [0.239657592773438, 0.53922971089681, 0.808844502766927],
    "y_values": [14.29551957699, 14.0864003697061, 21.9179491978139],
}


def _snapshot() -> RawSnapshot:
    content = json.dumps(
        REAL_PAYLOAD, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return RawSnapshot(
        content=content,
        media_type="application/json",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_normalize_refuses_a_weight_normalized_dose_rather_than_inventing_a_body_weight() -> None:
    connector = OspBundledLaskin1982Connector()

    with pytest.raises(IneligibleEvidenceCandidateError, match="mg/kg"):
        connector.normalize(_snapshot())


def test_normalize_error_names_the_specific_missing_information() -> None:
    connector = OspBundledLaskin1982Connector()

    with pytest.raises(IneligibleEvidenceCandidateError, match="body weight"):
        connector.normalize(_snapshot())
