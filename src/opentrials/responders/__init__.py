"""Transparent, deterministic extreme-responder selection over lineage-aware OTPK.

No machine-learning anomaly detection: only declared percentile/rank rules.
Selection describes how a tail was carved out of the ranked population, never
why those subjects responded that way.

This ``__init__`` deliberately re-exports only the dependency-free pieces
(``definitions``, ``selection``). ``opentrials.storage.responder_membership``
depends on those at import time, and it is itself eagerly imported by
``opentrials.storage``'s package init -- so this package must not eagerly
import ``responders.baseline_comparison``/``responders.orchestration`` here,
since both depend on ``opentrials.storage``, which would recreate the same
import-cycle shape fixed for the OTCPK milestone. Import those two directly:
``from opentrials.responders.baseline_comparison import ...`` and
``from opentrials.responders.orchestration import ...``.
"""

from opentrials.responders.definitions import (
    HIGH_DIRECTION_METHODS,
    PERCENTILE_METHODS,
    RESPONDER_DEFINITION_ID_PATTERN,
    RESPONDER_MEMBERSHIP_ID_PATTERN,
    ExtremeResponderDefinition,
    SelectionMethod,
    TiePolicy,
)
from opentrials.responders.selection import (
    RankableSubject,
    RankedSubject,
    SelectionResult,
    select_extreme_responders,
)

__all__ = [
    "HIGH_DIRECTION_METHODS",
    "PERCENTILE_METHODS",
    "RESPONDER_DEFINITION_ID_PATTERN",
    "RESPONDER_MEMBERSHIP_ID_PATTERN",
    "ExtremeResponderDefinition",
    "RankableSubject",
    "RankedSubject",
    "SelectionMethod",
    "SelectionResult",
    "TiePolicy",
    "select_extreme_responders",
]
