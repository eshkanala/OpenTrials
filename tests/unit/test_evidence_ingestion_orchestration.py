"""Contract tests for the generic fetch -> normalize -> persist orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    DataConnectorRunResult,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.orchestration.evidence_ingestion import ingest_evidence
from opentrials.storage.connector_run import DataConnectorRunArtifactStore
from opentrials.storage.observed import ObservedArtifactStore
from opentrials.storage.raw_snapshot import RawSnapshotArtifactStore
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


class FakeConnector:
    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id="test.ingestion-fake", version="1.0.0")

    def fetch(self) -> RawSnapshot:
        return RawSnapshot(
            content=b'{"rows": []}',
            media_type="application/json",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
        evidence = Evidence(
            id="EV-ingestion-fake-001",
            source_type=EvidenceSourceType.PUBLIC_DATASET,
            source_identifier="ingestion-fake-source",
            license="CC0",
        )
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
        dataset = ObservedDataset(
            dataset_id="OTOBS-ingestion-fake",
            role=DatasetRole.CALIBRATION,
            study=ObservedStudy(
                study_id="ingestion-fake-study",
                title="Ingestion fake study",
                evidence_ids=(evidence.id,),
                population_description="Synthetic",
                intervention=intervention,
            ),
            observations=(
                ObservedPkObservation(
                    observation_id="ingestion-fake-obs-001",
                    subject_or_population_id="fake-subject",
                    time=observed(0, "minute"),
                    value=observed(1.0, "mg/L"),
                    analyte="fake",
                    matrix="plasma",
                    fraction="total",
                    measurement="concentration",
                    evidence_ids=(evidence.id,),
                ),
            ),
            license="CC0",
            source_identifier="ingestion-fake-source",
            provenance_ids=(evidence.id,),
        )
        return DataConnectorRunResult(
            identity=self.identity,
            source=SourceDescriptor(
                accession="ingestion-fake-source", license="CC0", retrieved_at=snapshot.retrieved_at
            ),
            raw_snapshot=snapshot,
            transformation_provenance=(TransformationStep(description="No-op parse."),),
            evidence=EvidenceSet(evidence=(evidence,)),
            dataset=dataset,
        )


def test_ingest_evidence_persists_and_links_all_three_artifacts(tmp_path: Path) -> None:
    manifest = ingest_evidence(
        FakeConnector(),
        raw_snapshot_root=tmp_path / "raw",
        observed_root=tmp_path / "observed",
        connector_run_root=tmp_path / "connector_runs",
    )

    assert manifest.run_id.startswith("OTCONN-")
    assert manifest.observed_dataset_id == "OTOBS-ingestion-fake"
    assert manifest.identity.connector_id == "test.ingestion-fake"

    run_store = DataConnectorRunArtifactStore(tmp_path / "connector_runs")
    verified = run_store.verify_connector_run(
        manifest.run_id,
        raw_snapshot_store=RawSnapshotArtifactStore(tmp_path / "raw"),
        observed_store=ObservedArtifactStore(tmp_path / "observed"),
    )
    assert verified == manifest


def test_ingest_evidence_two_runs_produce_distinct_ids(tmp_path: Path) -> None:
    first = ingest_evidence(
        FakeConnector(),
        raw_snapshot_root=tmp_path / "raw",
        observed_root=tmp_path / "observed-1",
        connector_run_root=tmp_path / "connector_runs",
    )
    second = ingest_evidence(
        FakeConnector(),
        raw_snapshot_root=tmp_path / "raw",
        observed_root=tmp_path / "observed-2",
        connector_run_root=tmp_path / "connector_runs",
    )
    assert first.run_id != second.run_id
