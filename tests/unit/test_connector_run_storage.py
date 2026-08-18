"""Contract tests for the immutable OTCONN connector-run provenance record."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.storage.connector_run import DataConnectorRunArtifactStore
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole

RETRIEVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


def _dataset() -> ObservedDataset:
    intervention = Intervention(
        intervention_id="fake-intervention",
        compound=Compound(identity=CompoundIdentity(compound_id="fake", preferred_name="Fake")),
        regimen=Regimen(
            regimen_id="fake-regimen",
            doses=(
                Dose(
                    amount=observed(1, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=observed(0, "minute"),
                ),
            ),
        ),
    )
    return ObservedDataset(
        dataset_id="OTOBS-conn-test",
        role=DatasetRole.CALIBRATION,
        study=ObservedStudy(
            study_id="fake-study",
            title="Fake study",
            evidence_ids=("EV-1",),
            population_description="Synthetic",
            intervention=intervention,
        ),
        observations=(
            ObservedPkObservation(
                observation_id="fake-obs-001",
                subject_or_population_id="fake-subject",
                time=observed(0, "minute"),
                value=observed(1.0, "mg/L"),
                analyte="fake",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
                evidence_ids=("EV-1",),
            ),
        ),
        license="CC0",
        source_identifier="fake-source-001",
        provenance_ids=("EV-1",),
    )


def _write_supporting_artifacts(
    tmp_path: Path,
) -> tuple[RawSnapshotArtifactStore, ObservedArtifactStore, str, str, str]:
    raw_store = RawSnapshotArtifactStore(tmp_path / "raw")
    raw_store.create_raw_snapshot("OTRAW-conn-test")
    raw_manifest = raw_store.write_raw_snapshot(
        "OTRAW-conn-test",
        RawSnapshot(content=b"raw bytes", media_type="text/plain", retrieved_at=RETRIEVED_AT),
    )
    observed_store = ObservedArtifactStore(tmp_path / "observed")
    observed_store.create_observed_dataset("OTOBS-conn-test")
    observed_manifest = observed_store.write_observed_dataset(_dataset())
    return (
        raw_store,
        observed_store,
        raw_manifest.content_sha256,
        "OTOBS-conn-test",
        observed_manifest.dataset_canonical_sha256,
    )


def _source(accession: str) -> SourceDescriptor:
    return SourceDescriptor(accession=accession, license="CC0", retrieved_at=RETRIEVED_AT)


def test_connector_run_round_trips_and_verifies(tmp_path: Path) -> None:
    raw_store, observed_store, raw_hash, dataset_id, dataset_hash = _write_supporting_artifacts(
        tmp_path
    )

    run_store = DataConnectorRunArtifactStore(tmp_path / "connector_runs")
    run_store.create_connector_run("OTCONN-001")
    manifest = run_store.write_connector_run(
        "OTCONN-001",
        identity=DataConnectorIdentity(connector_id="test.connector", version="1.0.0"),
        source=_source("fake-source-001"),
        raw_snapshot_id="OTRAW-conn-test",
        raw_snapshot_content_sha256=raw_hash,
        observed_dataset_id=dataset_id,
        observed_dataset_canonical_sha256=dataset_hash,
        transformation_provenance=(TransformationStep(description="Parsed raw bytes."),),
        created_at=RETRIEVED_AT,
    )

    verified = run_store.verify_connector_run(
        "OTCONN-001", raw_snapshot_store=raw_store, observed_store=observed_store
    )
    assert verified == manifest


def test_verify_rejects_mismatched_raw_snapshot_hash(tmp_path: Path) -> None:
    raw_store, observed_store, _raw_hash, dataset_id, dataset_hash = _write_supporting_artifacts(
        tmp_path
    )

    run_store = DataConnectorRunArtifactStore(tmp_path / "connector_runs")
    run_store.create_connector_run("OTCONN-002")
    run_store.write_connector_run(
        "OTCONN-002",
        identity=DataConnectorIdentity(connector_id="test.connector", version="1.0.0"),
        source=_source("fake-source-001"),
        raw_snapshot_id="OTRAW-conn-test",
        raw_snapshot_content_sha256="sha256:" + "0" * 64,
        observed_dataset_id=dataset_id,
        observed_dataset_canonical_sha256=dataset_hash,
        transformation_provenance=(TransformationStep(description="Parsed raw bytes."),),
        created_at=RETRIEVED_AT,
    )

    with pytest.raises(ValueError, match="raw snapshot hash"):
        run_store.verify_connector_run(
            "OTCONN-002", raw_snapshot_store=raw_store, observed_store=observed_store
        )


def test_verify_rejects_mismatched_source_locator(tmp_path: Path) -> None:
    raw_store, observed_store, raw_hash, dataset_id, dataset_hash = _write_supporting_artifacts(
        tmp_path
    )

    run_store = DataConnectorRunArtifactStore(tmp_path / "connector_runs")
    run_store.create_connector_run("OTCONN-003")
    run_store.write_connector_run(
        "OTCONN-003",
        identity=DataConnectorIdentity(connector_id="test.connector", version="1.0.0"),
        source=_source("a-different-source"),
        raw_snapshot_id="OTRAW-conn-test",
        raw_snapshot_content_sha256=raw_hash,
        observed_dataset_id=dataset_id,
        observed_dataset_canonical_sha256=dataset_hash,
        transformation_provenance=(TransformationStep(description="Parsed raw bytes."),),
        created_at=RETRIEVED_AT,
    )

    with pytest.raises(ValueError, match="source locator"):
        run_store.verify_connector_run(
            "OTCONN-003", raw_snapshot_store=raw_store, observed_store=observed_store
        )
