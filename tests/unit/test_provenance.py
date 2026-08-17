from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opentrials.core.provenance import ProvenanceActivityType, ProvenanceRecord


def test_provenance_record_represents_a_directed_transformation() -> None:
    record = ProvenanceRecord(
        id="provenance-001",
        activity_type=ProvenanceActivityType.TRANSFORMATION,
        input_ids=("source-value-001",),
        output_id="derived-parameter-001",
        method="allometric scaling",
        performed_at=datetime(2026, 8, 16, tzinfo=UTC),
        evidence_ids=("evidence-001",),
    )

    assert record.output_id == "derived-parameter-001"
    assert '"activity_type":"TRANSFORMATION"' in record.canonical_json()


def test_provenance_rejects_cyclic_single_edge() -> None:
    with pytest.raises(ValidationError, match="cannot also be one of its inputs"):
        ProvenanceRecord(
            id="provenance-001",
            activity_type=ProvenanceActivityType.IMPORT,
            input_ids=("artifact-001",),
            output_id="artifact-001",
            method="import",
            performed_at=datetime(2026, 8, 16, tzinfo=UTC),
        )


def test_provenance_rejects_duplicate_inputs() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        ProvenanceRecord(
            id="provenance-001",
            activity_type=ProvenanceActivityType.SUMMARIZATION,
            input_ids=("result-001", "result-001"),
            output_id="endpoint-001",
            method="AUC summary",
            performed_at=datetime(2026, 8, 16, tzinfo=UTC),
        )
