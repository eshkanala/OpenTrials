"""Structured execution events: the shared vocabulary between the SDK, CLI, and future GUI.

Every orchestration module already reports progress through a plain
``Callable[[str], None]`` stage-name callback (see e.g.
``orchestration.trial_execution.ProgressCallback``) -- deliberately left
unchanged here, since dozens of tests already depend on that exact,
verified signature. This module is the SDK-layer adapter: it turns that
existing stream of bare stage names into a stream of typed ``Event``
objects a CLI renderer or a future GUI can consume without needing to know
which specific orchestration function produced them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventStatus(StrEnum):
    """The lifecycle state one workflow stage has just entered."""

    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Event(BaseModel):
    """One structured, timestamped fact about a running workflow.

    ``detail`` carries whatever concrete evidence is already available at
    that point (a verified hash, a read-back dose, a participant count) --
    it is additive, never required, since not every stage has something
    beyond its own name and status to report.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(min_length=1)
    status: EventStatus
    timestamp: datetime
    detail: Mapping[str, Any] = Field(default_factory=dict)


EventSink = Callable[[Event], None]
"""What a caller supplies to receive events: one function, one Event at a time."""


def stage_progress_adapter(sink: EventSink | None) -> Callable[[str], None]:
    """Adapt an ``EventSink`` into the plain stage-name callback orchestration expects.

    Every orchestration module calls its progress callback with just a bare
    stage name once, when that stage completes (see e.g.
    ``orchestration.population_execution.run_population_execution``'s own
    stage list) -- there is no separate "started" signal from the
    orchestration layer itself. This adapter therefore emits one
    ``COMPLETED`` event per callback invocation; the previous stage's
    completion doubles as the next stage's implicit start, which is
    accurate to what orchestration actually reports and avoids inventing a
    START event orchestration never signaled.
    """
    if sink is None:
        return lambda _stage: None

    def _callback(stage: str) -> None:
        sink(Event(stage=stage, status=EventStatus.COMPLETED, timestamp=datetime.now(UTC)))

    return _callback


def emit_failed(sink: EventSink | None, stage: str, detail: Mapping[str, Any]) -> None:
    """Emit one FAILED event, used by the SDK layer when a workflow raises."""
    if sink is None:
        return
    sink(
        Event(
            stage=stage,
            status=EventStatus.FAILED,
            timestamp=datetime.now(UTC),
            detail=detail,
        )
    )
