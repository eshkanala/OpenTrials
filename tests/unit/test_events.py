"""Contract tests for the structured event adapter between orchestration and the SDK."""

from __future__ import annotations

from opentrials.events import Event, EventStatus, emit_failed, stage_progress_adapter


def test_stage_progress_adapter_emits_one_completed_event_per_stage_name() -> None:
    events: list[Event] = []
    callback = stage_progress_adapter(events.append)

    callback("verifying_population")
    callback("executing_population")

    assert [event.stage for event in events] == ["verifying_population", "executing_population"]
    assert all(event.status is EventStatus.COMPLETED for event in events)


def test_stage_progress_adapter_tolerates_no_sink() -> None:
    callback = stage_progress_adapter(None)
    callback("some_stage")  # must not raise


def test_emit_failed_carries_detail() -> None:
    events: list[Event] = []
    emit_failed(events.append, "executing_population", {"error": "boom"})

    assert len(events) == 1
    assert events[0].status is EventStatus.FAILED
    assert events[0].detail == {"error": "boom"}


def test_emit_failed_tolerates_no_sink() -> None:
    emit_failed(None, "some_stage", {})  # must not raise
