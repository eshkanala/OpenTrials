from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opentrials.core.distributions import Distribution, DistributionType
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType


def test_evidence_links_result_and_uncertainty() -> None:
    value = ScientificValue(value=3.2, unit="L/h", value_type=ValueType.OBSERVED)
    uncertainty = Distribution(
        distribution_type=DistributionType.NORMAL,
        unit="L/h",
        parameters={"mean": 3.2, "standard_deviation": 0.4},
    )
    evidence = Evidence(
        id="evidence-001",
        source_type=EvidenceSourceType.PEER_REVIEWED_ARTICLE,
        source_identifier="doi:10.0000/example",
        result=value,
        uncertainty=uncertainty,
        retrieved_at=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert evidence.result == value
    assert evidence.uncertainty == uncertainty
    assert '"source_identifier":"doi:10.0000/example"' in evidence.canonical_json()


def test_evidence_rejects_uncertainty_in_another_unit() -> None:
    with pytest.raises(ValidationError, match="same unit"):
        Evidence(
            id="evidence-001",
            source_type=EvidenceSourceType.ASSAY_DATABASE,
            source_identifier="assay:001",
            result=ScientificValue(value=3.2, unit="L/h", value_type=ValueType.OBSERVED),
            uncertainty=Distribution(
                distribution_type=DistributionType.NORMAL,
                unit="mg",
                parameters={"mean": 3.2, "standard_deviation": 0.4},
            ),
        )


def test_evidence_set_rejects_duplicate_ids() -> None:
    record = Evidence(
        id="evidence-001",
        source_type=EvidenceSourceType.EXPERT_ASSUMPTION,
        source_identifier="assumption:001",
    )

    with pytest.raises(ValidationError, match="duplicate"):
        EvidenceSet(evidence=(record, record))
