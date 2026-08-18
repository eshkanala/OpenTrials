"""Opt-in live proof: the v0.8-A evidence connector against real local OSP.

Runs the full fetch -> normalize -> persist -> verify chain against the
real, bundled ``ObsDataAciclovir_1.pkml``, proving the generic
``DataConnector`` contract against one real source end to end, not just
against synthetic fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentrials.evidence.connectors.osp_bundled_pk_observations import (
    OspBundledPkObservationsConnector,
)
from opentrials.orchestration.evidence_ingestion import ingest_evidence
from opentrials.storage.connector_run import DataConnectorRunArtifactStore
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore
from opentrials.validation.study import DatasetRole

pytestmark = pytest.mark.osp_integration


def test_bundled_observed_data_ingests_and_verifies_end_to_end(tmp_path: Path) -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    connector = OspBundledPkObservationsConnector(r_libs_user=r_libs_user)
    manifest = ingest_evidence(
        connector,
        raw_snapshot_root=tmp_path / "raw",
        observed_root=tmp_path / "observed",
        connector_run_root=tmp_path / "connector_runs",
    )

    assert manifest.identity.connector_id == connector.identity.connector_id
    assert manifest.observed_dataset_id == "OTOBS-vergin-1995-iv"
    assert manifest.source.accession == "Vergin 1995"
    assert manifest.source.license == "Bundled ospsuite example; redistribution not asserted."
    assert len(manifest.transformation_provenance) >= 1

    # Full independent re-verification, from each sub-artifact's own store --
    # the same discipline as every other multi-artifact chain in this project.
    run_store = DataConnectorRunArtifactStore(tmp_path / "connector_runs")
    verified = run_store.verify_connector_run(
        manifest.run_id,
        raw_snapshot_store=RawSnapshotArtifactStore(tmp_path / "raw"),
        observed_store=ObservedArtifactStore(tmp_path / "observed"),
    )
    assert verified == manifest

    observed_manifest = ObservedArtifactStore(tmp_path / "observed").verify_observed_dataset(
        manifest.observed_dataset_id
    )
    assert observed_manifest.role is DatasetRole.CALIBRATION
    assert observed_manifest.observations.rows == 13
    assert observed_manifest.dataset.study.intervention.regimen.doses[0].amount.value == 250.0

    print(
        "\nLive v0.8-A proof -- ingested",
        observed_manifest.observations.rows,
        "real observed PK points from the bundled Vergin 1995 IV aciclovir dataset, "
        "connector run",
        manifest.run_id,
    )
