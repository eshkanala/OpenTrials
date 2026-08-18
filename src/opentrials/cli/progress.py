"""Renders structured ``Event`` objects as terminal output.

Deliberately honest rather than decorative: orchestration reports progress
per *stage* (see ``events.stage_progress_adapter``), not per row or percent
complete within a stage, so this renderer never fabricates a percentage or
a spinner that isn't backed by a real signal. What it does show --
per-stage completion with elapsed time, and in ``--verbose`` mode every
concrete fact already available in an event's ``detail`` -- is exactly what
orchestration actually reports, no more and no less.
"""

from __future__ import annotations

import time

from opentrials.events import Event, EventStatus

_STAGE_LABELS = {
    "verifying_population": "Verifying population",
    "verifying_physiology_population": "Verifying physiology population",
    "verifying_source_population": "Verifying source population",
    "translating_intervention": "Translating intervention",
    "translating_population_specification": "Translating population specification",
    "generating_population": "Generating population",
    "persisting_population": "Persisting population",
    "executing_population": "Executing population",
    "persisting_raw": "Persisting raw results",
    "normalizing_results": "Normalizing results",
    "resolving_lineage": "Resolving lineage",
    "calculating_endpoints": "Calculating endpoints",
    "writing_manifest": "Writing manifest",
    "validating_trial": "Validating trial",
    "allocating_arms": "Allocating arms",
    "comparing_arms": "Comparing arms",
    "writing_trial_record": "Writing trial record",
    "completed": "Completed",
}


def _label(stage: str) -> str:
    if stage in _STAGE_LABELS:
        return _STAGE_LABELS[stage]
    if stage.startswith("executing_arm:"):
        return f"Executing arm {stage.removeprefix('executing_arm:')}"
    return stage.replace("_", " ").capitalize()


class ProgressRenderer:
    """Renders one run's events to stdout as it happens."""

    def __init__(self, *, title: str, trial_id: str, verbose: bool, is_tty: bool) -> None:
        self._title = title
        self._trial_id = trial_id
        self._verbose = verbose
        self._is_tty = is_tty
        self._started = time.monotonic()

    def start(self, *, model_id: str) -> None:
        print("OpenTrials -- Virtual Trial\n")
        print(f"Trial        {self._title} ({self._trial_id})")
        print(f"Model        {model_id}")
        print()

    def on_event(self, event: Event) -> None:
        elapsed = time.monotonic() - self._started
        if event.status is EventStatus.COMPLETED:
            print(f"[✓] {_label(event.stage):<32} ({elapsed:5.1f}s)")
        elif event.status is EventStatus.FAILED:
            print(f"[✗] {_label(event.stage):<32} ({elapsed:5.1f}s)")
        if self._verbose and event.detail:
            timestamp = event.timestamp.strftime("%H:%M:%S")
            for key, value in event.detail.items():
                print(f"    [{timestamp}] {key}: {value}")

    def finish(self, *, failed: bool) -> None:
        elapsed = time.monotonic() - self._started
        status = "failed" if failed else "completed"
        print(f"\nRun {status} in {elapsed:.1f}s")
