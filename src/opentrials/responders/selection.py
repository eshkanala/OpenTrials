"""Pure, deterministic ranking and extreme-tail selection over PK endpoint values.

Never fits a model, never scores anomalies -- purely a rank/percentile cutoff
over already-computed, already-verified endpoint values. Ranking always uses
an explicit deterministic secondary key (``source_row_index``) so identical
inputs produce identical output regardless of input order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from opentrials.analysis.descriptive import percentile as interpolated_percentile
from opentrials.responders.definitions import (
    HIGH_DIRECTION_METHODS,
    ExtremeResponderDefinition,
    SelectionMethod,
    TiePolicy,
)

_PERCENTILE_COUNT_METHODS = (SelectionMethod.TOP_PERCENTILE, SelectionMethod.BOTTOM_PERCENTILE)
_COUNT_METHODS = (SelectionMethod.TOP_N, SelectionMethod.BOTTOM_N)


@dataclass(frozen=True)
class RankableSubject:
    """One subject's endpoint value with its verified population-row identity."""

    subject_id: str
    source_row_index: int
    source_row_sha256: str
    value: float


@dataclass(frozen=True)
class RankedSubject:
    """One subject after ranking. Rank 1 is always the most extreme."""

    subject_id: str
    source_row_index: int
    source_row_sha256: str
    value: float
    rank: int


@dataclass(frozen=True)
class SelectionResult:
    """The complete deterministic outcome of one extreme-responder selection."""

    definition: ExtremeResponderDefinition
    total_population: int
    threshold_value: float
    extreme: tuple[RankedSubject, ...]
    reference: tuple[RankedSubject, ...]


def select_extreme_responders(
    subjects: Sequence[RankableSubject], definition: ExtremeResponderDefinition
) -> SelectionResult:
    """Rank and select an extreme tail deterministically from one endpoint."""
    if not subjects:
        raise ValueError("At least one subject is required for extreme-responder selection.")
    total = len(subjects)
    high_direction = definition.method in HIGH_DIRECTION_METHODS

    ordered = sorted(
        subjects,
        key=lambda subject: (
            -subject.value if high_direction else subject.value,
            subject.source_row_index,
        ),
    )
    ranked_all = tuple(
        RankedSubject(
            subject_id=subject.subject_id,
            source_row_index=subject.source_row_index,
            source_row_sha256=subject.source_row_sha256,
            value=subject.value,
            rank=index + 1,
        )
        for index, subject in enumerate(ordered)
    )

    if definition.method in _PERCENTILE_COUNT_METHODS:
        assert definition.percentile is not None
        requested_count = min(max(1, math.ceil(total * definition.percentile / 100.0)), total)
        selected, threshold_value = _select_by_count(
            ranked_all, requested_count, definition.tie_policy, high_direction
        )
    elif definition.method in _COUNT_METHODS:
        assert definition.count is not None
        if definition.count > total:
            raise ValueError(
                f"Requested count {definition.count} exceeds the total population {total}."
            )
        selected, threshold_value = _select_by_count(
            ranked_all, definition.count, definition.tie_policy, high_direction
        )
    else:
        assert definition.percentile is not None
        values_ascending = sorted(subject.value for subject in subjects)
        cutoff = interpolated_percentile(values_ascending, definition.percentile / 100.0)
        threshold_value = cutoff
        include_ties = definition.tie_policy is TiePolicy.INCLUDE_ALL_TIES
        if definition.method is SelectionMethod.ABOVE_PERCENTILE:
            selected = tuple(
                subject
                for subject in ranked_all
                if subject.value > cutoff or (include_ties and subject.value == cutoff)
            )
        else:
            selected = tuple(
                subject
                for subject in ranked_all
                if subject.value < cutoff or (include_ties and subject.value == cutoff)
            )

    selected_keys = {(subject.source_row_index, subject.source_row_sha256) for subject in selected}
    reference = tuple(
        subject
        for subject in ranked_all
        if (subject.source_row_index, subject.source_row_sha256) not in selected_keys
    )

    return SelectionResult(
        definition=definition,
        total_population=total,
        threshold_value=threshold_value,
        extreme=selected,
        reference=reference,
    )


def _select_by_count(
    ranked_all: Sequence[RankedSubject],
    requested_count: int,
    tie_policy: TiePolicy,
    high_direction: bool,
) -> tuple[tuple[RankedSubject, ...], float]:
    """Select the ``requested_count`` most extreme already-ordered subjects."""
    boundary_value = ranked_all[requested_count - 1].value
    if tie_policy is TiePolicy.STRICT_COUNT:
        return tuple(ranked_all[:requested_count]), boundary_value
    if high_direction:
        selected = tuple(subject for subject in ranked_all if subject.value >= boundary_value)
    else:
        selected = tuple(subject for subject in ranked_all if subject.value <= boundary_value)
    return selected, boundary_value
