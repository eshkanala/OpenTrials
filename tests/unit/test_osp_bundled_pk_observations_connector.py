"""Contract tests for the reference OspBundledPkObservationsConnector.normalize().

Exercises the connector's ``normalize()`` step against a fixed, real (though
truncated) payload previously captured from the real OSP worker reading the
bundled ``ObsDataAciclovir_1.pkml`` -- no OSP/R invocation needed here, since
``normalize()`` must be pure with respect to the raw bytes it is given. The
live ``fetch()`` path is proven separately in
``tests/integration/test_osp_bundled_pk_observations_live.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from opentrials.evidence.connector import RawSnapshot
from opentrials.evidence.connectors.osp_bundled_pk_observations import (
    OspBundledPkObservationsConnector,
)
from opentrials.validation.study import DatasetRole

# A real (truncated to 3 points), previously-captured response from
# adapters/osp/read_observed_dataset.R reading the actual bundled
# ObsDataAciclovir_1.pkml -- every field here is a real value read from OSP,
# not invented.
REAL_PAYLOAD = {
    "status": "SUCCEEDED",
    "generated_at": "2026-08-18T15:53:33Z",
    "r_version": "R version 4.6.1 (2026-06-24)",
    "ospsuite_version": "12.4.4",
    "name": "Vergin 1995.Iv",
    "x_unit": "h",
    "y_unit": "mg/l",
    "x_dimension": "Time",
    "y_dimension": "Concentration (mass)",
    "y_error_unit": "mg/l",
    "y_error_type": "ArithmeticStdDev",
    "mol_weight": 225.21,
    "metadata": {
        "Source": "X:\\Orga\\BTS-TD\\ET\\TP CSB\\Projects\\Internal Projects\\MagenDarm\\"
        "TestSubstanzen\\Acyclovir\\Rohdaten_Acyclovir.xls.Vergin 1995 250 mg iv",
        "File": "Rohdaten_Acyclovir",
        "Sheet": "Vergin 1995 250 mg iv",
        "Molecule": "Aciclovir",
        "Species": "Human",
        "Organ": "Peripheral Venous Blood",
        "Compartment": "Plasma",
        "Study Id": "Vergin 1995",
        "Gender": "Undefined",
        "Dose": "250 mg",
        "Route": "IV",
        "Patient Id": "Iv",
    },
    "x_values": [0.22360250155131, 0.484471988677979, 0.745341618855794],
    "y_values": [7.89215664553922, 4.50980405730661, 3.18627394335635],
    "y_error_values": [1.49509799030056, 0.857843019730353, 0.63725502741363],
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


def test_normalize_produces_one_observation_per_source_point() -> None:
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    assert len(result.dataset.observations) == 3
    assert len(result.evidence.evidence) == 1 + 3  # one study-level + one per observation


def test_normalize_preserves_real_time_and_concentration_values() -> None:
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    first = result.dataset.observations[0]
    assert first.time.value == 0.22360250155131
    assert first.time.unit == "h"
    assert first.value.value == 7.89215664553922
    assert first.value.unit == "mg/l"
    assert first.analyte == "aciclovir"
    assert first.matrix == "peripheral venous plasma"


def test_normalize_carries_measurement_uncertainty_as_a_normal_distribution() -> None:
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    first_observation_evidence = next(
        evidence
        for evidence in result.evidence.evidence
        if evidence.id == "EV-vergin-1995-iv-obs-00"
    )
    assert first_observation_evidence.uncertainty is not None
    assert first_observation_evidence.uncertainty.parameters == {
        "mean": 7.89215664553922,
        "standard_deviation": 1.49509799030056,
    }
    assert first_observation_evidence.result is not None
    assert first_observation_evidence.result.value == 7.89215664553922


def test_normalize_parses_the_observed_dose_from_source_metadata() -> None:
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    dose = result.dataset.study.intervention.regimen.doses[0]
    assert dose.amount.value == 250.0
    assert dose.amount.unit == "mg"
    assert dose.infusion_duration is None  # not stated in the observed metadata


def test_normalize_registers_calibration_role_not_validation() -> None:
    """This is the same reference dataset the bundled model was built from -- must not be
    registered as if it were independent validation evidence (would be circular)."""
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    assert result.dataset.role is DatasetRole.CALIBRATION
    assert "circular" in (result.dataset.study.study_limitations or "").lower()


def test_normalize_source_locator_matches_dataset_source_identifier() -> None:
    connector = OspBundledPkObservationsConnector()
    result = connector.normalize(_snapshot())

    assert result.source.accession == result.dataset.source_identifier == "Vergin 1995"


def test_normalize_is_deterministic_given_the_same_snapshot() -> None:
    connector = OspBundledPkObservationsConnector()
    snapshot = _snapshot()

    first = connector.normalize(snapshot)
    second = connector.normalize(snapshot)

    assert first.dataset == second.dataset
    assert first.evidence == second.evidence
