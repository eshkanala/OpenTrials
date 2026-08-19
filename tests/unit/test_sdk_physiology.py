"""Contract tests for sdk.physiology's thin wrappers.

``run_physiology_trial_execution`` and ``PhysiologyTrialArtifactStore.verify_physiology_trial``
already have their own coverage (v0.6-B). These tests only prove the thin
SDK-layer wrapping this module adds: event adaptation, argument pass-through,
and endpoint-store reconstruction from a manifest's own recorded
``executed_run_id`` values -- so real orchestration/storage logic is
stubbed out rather than re-proven here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentrials.events import Event, EventStatus
from opentrials.orchestration.physiology_trial_execution import (
    PhysiologyStateDeclaration,
    PhysiologyTrialExecutionRun,
)
from opentrials.physiology.overrides import PhysiologicalStateOverride
from opentrials.sdk import physiology as sdk_physiology


def make_states() -> tuple[PhysiologyStateDeclaration, ...]:
    return (
        PhysiologyStateDeclaration(
            state_id="baseline",
            override=PhysiologicalStateOverride(
                target="renal.glomerular_filtration_rate",
                scale_factor=1.0,
                unit="dimensionless",
                purpose="baseline",
            ),
        ),
        PhysiologyStateDeclaration(
            state_id="reduced",
            override=PhysiologicalStateOverride(
                target="renal.glomerular_filtration_rate",
                scale_factor=0.6,
                unit="dimensionless",
                purpose="moderate renal impairment lever",
            ),
        ),
    )


def test_run_trial_physiology_states_adapts_events_and_passes_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_physiology_trial_execution(**kwargs: Any) -> PhysiologyTrialExecutionRun:
        captured.update(kwargs)
        progress = kwargs["progress"]
        if progress is not None:
            progress("verifying_source_population")
            progress("completed")
        return PhysiologyTrialExecutionRun(
            run_id="OTR-physiology-trial-abc",
            run_directory=tmp_path / "OTR-physiology-trial-abc",
            trial_run_id="OTPHYTRIAL-abc",
            comparison_id="OTPHYCMP-abc",
            source_generation_id="OTPGEN-demo",
            baseline_state_id="baseline",
            state_ids=("baseline", "reduced"),
        )

    monkeypatch.setattr(
        "opentrials.sdk.physiology.run_physiology_trial_execution",
        fake_run_physiology_trial_execution,
    )

    events: list[Event] = []
    result = sdk_physiology.run_trial_physiology_states(
        model_capability_profile="fake-profile",  # type: ignore[arg-type]
        population_generation_id="OTPGEN-demo",
        population_root=tmp_path / "populations",
        physiology_root=tmp_path / "physiology",
        states=make_states(),
        baseline_state_id="baseline",
        dose_mg=250.0,
        output_root=tmp_path / "runs",
        r_libs_user="/fake/r/libs",
        events=events.append,
    )

    assert isinstance(result, PhysiologyTrialExecutionRun)
    assert result.trial_run_id == "OTPHYTRIAL-abc"
    # Pure path pass-through, coerced from str|Path to Path.
    assert captured["population_root"] == tmp_path / "populations"
    assert captured["physiology_root"] == tmp_path / "physiology"
    assert captured["dose_mg"] == 250.0
    assert captured["baseline_state_id"] == "baseline"
    # The bare stage-name callback was adapted into real typed Events.
    assert [e.stage for e in events] == ["verifying_source_population", "completed"]
    assert all(e.status is EventStatus.COMPLETED for e in events)


def test_verify_physiology_states_reconstructs_endpoint_stores_from_the_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = PhysiologyTrialExecutionRun(
        run_id="OTR-physiology-trial-xyz",
        run_directory=tmp_path / "OTR-physiology-trial-xyz",
        trial_run_id="OTPHYTRIAL-xyz",
        comparison_id="OTPHYCMP-xyz",
        source_generation_id="OTPGEN-demo",
        baseline_state_id="baseline",
        state_ids=("baseline", "reduced"),
    )

    class FakeState:
        def __init__(self, state_id: str, executed_run_id: str) -> None:
            self.state_id = state_id
            self.executed_run_id = executed_run_id

    class FakeManifest:
        states = (
            FakeState("baseline", "OTR-physiology-population-1"),
            FakeState("reduced", "OTR-physiology-population-2"),
        )

    captured_endpoint_stores: dict[str, Any] = {}

    class FakeTrialRunStore:
        def __init__(self, root: Path) -> None:
            self.root = root

        def read_manifest(self, trial_run_id: str) -> FakeManifest:
            return FakeManifest()

        def verify_physiology_trial(self, trial_run_id: str, **kwargs: Any) -> str:
            captured_endpoint_stores.update(kwargs["endpoint_stores"])
            return "verified-manifest"

    monkeypatch.setattr(
        "opentrials.sdk.physiology.PhysiologyTrialArtifactStore", FakeTrialRunStore
    )

    result = sdk_physiology.verify_physiology_states(
        run, population_root=tmp_path / "populations", physiology_root=tmp_path / "physiology"
    )

    assert result == "verified-manifest"
    assert set(captured_endpoint_stores) == {"baseline", "reduced"}
    baseline_store = captured_endpoint_stores["baseline"]
    assert baseline_store.root == (
        run.run_directory / "states" / "OTR-physiology-population-1" / "endpoints"
    )
