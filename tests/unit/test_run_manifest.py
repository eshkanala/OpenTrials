from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from opentrials.simulation import ModelRunReference, RunManifest, RunStatus

HASH = "sha256:" + "b" * 64
STARTED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


def make_run_manifest(**changes: object) -> RunManifest:
    values: dict[str, object] = {
        "run_id": "OTR-aciclovir-demo-001",
        "status": RunStatus.RUNNING,
        "trial_spec_hash": HASH,
        "population_hash": HASH,
        "models": (
            ModelRunReference(
                model_id="org.example.aciclovir-pbpk",
                model_version="1.0.0",
                package_hash=HASH,
            ),
        ),
        "software_versions": {"opentrials": "0.0.0", "osp-adapter": "0.1.0"},
        "seed": 42,
        "solver_configuration": {"relative_tolerance": 1e-6},
        "code_revision": "abc1234",
        "operating_environment": {"python": "3.12.13", "platform": "macos-arm64"},
        "started_at": STARTED_AT,
    }
    values.update(changes)
    return RunManifest(**values)


def test_running_manifest_captures_reproducibility_inputs() -> None:
    manifest = make_run_manifest()

    assert manifest.seed == 42
    assert manifest.models[0].model_id == "org.example.aciclovir-pbpk"
    assert '"trial_spec_hash":"' in manifest.canonical_json()


def test_successful_run_requires_completion_and_output_hashes() -> None:
    completed_at = STARTED_AT + timedelta(minutes=1)
    manifest = make_run_manifest(
        status=RunStatus.SUCCEEDED,
        completed_at=completed_at,
        output_hashes={"results.parquet": HASH},
    )

    assert manifest.completed_at == completed_at
    assert manifest.output_hashes["results.parquet"] == HASH


def test_terminal_run_requires_completion_time() -> None:
    with pytest.raises(ValidationError, match="completion time"):
        make_run_manifest(status=RunStatus.FAILED)


def test_successful_run_requires_output_hashes() -> None:
    with pytest.raises(ValidationError, match="output hashes"):
        make_run_manifest(status=RunStatus.SUCCEEDED, completed_at=STARTED_AT)


def test_run_rejects_duplicate_model_ids() -> None:
    duplicate = ModelRunReference(
        model_id="org.example.aciclovir-pbpk",
        model_version="2.0.0",
        package_hash=HASH,
    )

    with pytest.raises(ValidationError, match="more than once"):
        make_run_manifest(models=(make_run_manifest().models[0], duplicate))


def test_run_rejects_completion_before_start() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        make_run_manifest(status=RunStatus.FAILED, completed_at=STARTED_AT - timedelta(seconds=1))
