"""Generic external-evidence connector contract."""

from opentrials.evidence.connector import (
    DataConnector,
    DataConnectorIdentity,
    DataConnectorRunResult,
    IneligibleEvidenceCandidateError,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
    run_connector,
)

__all__ = [
    "DataConnector",
    "DataConnectorIdentity",
    "DataConnectorRunResult",
    "IneligibleEvidenceCandidateError",
    "RawSnapshot",
    "SourceDescriptor",
    "TransformationStep",
    "run_connector",
]
