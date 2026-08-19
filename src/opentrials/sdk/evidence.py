"""The default, pre-composed set of evidence connectors this project ships.

Mirrors ``sdk.registry.default_model_registry``'s own composition pattern
exactly: ``evidence.connector.DataConnector`` is deliberately generic and
knows nothing about any specific source (see its own module docstring).
Composing it with the connectors this project actually ships is a top-level
concern, not a core one -- this is that composition, and the one place a
new connector needs to be added to become reachable from the SDK/Studio.
"""

from __future__ import annotations

from opentrials.evidence.connector import DataConnector
from opentrials.evidence.connectors import (
    OspBundledLaskin1982Connector,
    OspBundledPkObservationsConnector,
)


def default_evidence_connectors(*, r_libs_user: str | None = None) -> tuple[DataConnector, ...]:
    """Build every evidence connector this project ships, ready to run."""
    return (
        OspBundledPkObservationsConnector(r_libs_user=r_libs_user),
        OspBundledLaskin1982Connector(r_libs_user=r_libs_user),
    )
