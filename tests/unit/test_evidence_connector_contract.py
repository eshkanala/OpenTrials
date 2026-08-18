"""Contract tests for the generic v0.8-A DataConnector interface.

Uses a minimal fake connector with no external dependency (no OSP, no
network) to prove the contract itself -- fetch/normalize separation,
run_connector() orchestration -- is genuinely generic, independent of any
one source's implementation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    DataConnectorRunResult,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
    run_connector,
)
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole


def observed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)


class FakeConnector:
    """A minimal, fully synthetic connector proving the contract's shape."""

    def __init__(self, *, source_bytes: bytes = b'{"rows": [1, 2, 3]}') -> None:
        self._source_bytes = source_bytes
        self.fetch_calls = 0
        self.normalize_calls = 0

    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id="test.fake-connector", version="0.0.1")

    def fetch(self) -> RawSnapshot:
        self.fetch_calls += 1
        return RawSnapshot(
            content=self._source_bytes,
            media_type="application/json",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
        self.normalize_calls += 1
        evidence = Evidence(
            id="EV-fake-001",
            source_type=EvidenceSourceType.PUBLIC_DATASET,
            source_identifier="fake-source-001",
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
            dataset_id="OTOBS-fake-001",
            role=DatasetRole.CALIBRATION,
            study=ObservedStudy(
                study_id="fake-study",
                title="Fake study",
                evidence_ids=(evidence.id,),
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
                    evidence_ids=(evidence.id,),
                ),
            ),
            license="CC0",
            source_identifier="fake-source-001",
            provenance_ids=(evidence.id,),
        )
        return DataConnectorRunResult(
            identity=self.identity,
            source=SourceDescriptor(
                accession="fake-source-001",
                license="CC0",
                retrieved_at=snapshot.retrieved_at,
            ),
            raw_snapshot=snapshot,
            transformation_provenance=(TransformationStep(description="Parsed fake JSON rows."),),
            evidence=EvidenceSet(evidence=(evidence,)),
            dataset=dataset,
        )


def test_run_connector_calls_fetch_then_normalize_exactly_once() -> None:
    connector = FakeConnector()
    result = run_connector(connector)

    assert connector.fetch_calls == 1
    assert connector.normalize_calls == 1
    assert result.dataset.dataset_id == "OTOBS-fake-001"
    assert result.raw_snapshot.content_sha256() == (
        "sha256:" + hashlib.sha256(b'{"rows": [1, 2, 3]}').hexdigest()
    )


def test_normalize_is_pure_with_respect_to_the_snapshot_it_is_given() -> None:
    """The same RawSnapshot passed twice produces the same normalized result."""
    connector = FakeConnector()
    snapshot = connector.fetch()

    first = connector.normalize(snapshot)
    second = connector.normalize(snapshot)

    assert first.dataset == second.dataset
    assert first.evidence == second.evidence


def test_source_descriptor_requires_at_least_one_locator() -> None:
    with pytest.raises(ValueError, match="at least one"):
        SourceDescriptor(license="CC0", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_source_descriptor_accepts_a_bare_url() -> None:
    source = SourceDescriptor(
        source_url="https://example.org/dataset.csv",
        license="CC0",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert source.source_url == "https://example.org/dataset.csv"
