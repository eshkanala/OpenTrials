"""Generic external-evidence connector contract."""

from opentrials.evidence.connector import (
    DataConnector,
    DataConnectorIdentity,
    DataConnectorRunResult,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
    run_connector,
)

__all__ = [
    "DataConnector",
    "DataConnectorIdentity",
    "DataConnectorRunResult",
    "RawSnapshot",
    "SourceDescriptor",
    "TransformationStep",
    "run_connector",
]
