from pathlib import Path

import pytest

from opentrials.config import TrialConfigurationError, load_trial
from opentrials.core.serialization import document
from opentrials.storage import RunArtifactStore


def test_loads_versioned_aciclovir_trial_configuration() -> None:
    trial = load_trial(Path("examples/aciclovir/trial.yaml"))

    assert trial.trial_id == "ACICLOVIR-DEMO"
    assert trial.arms[0].intervention.compound.identity.compound_id == "aciclovir"


def test_rejects_unknown_trial_schema(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schema: opentrials.population\nschema_version: 1.0.0\npayload: {}\n")

    with pytest.raises(TrialConfigurationError, match="Expected schema"):
        load_trial(path)


def test_run_artifacts_are_immutable_and_checksums_are_written(tmp_path: Path) -> None:
    store = RunArtifactStore(tmp_path / "runs")
    store.create_run("OTR-demo-001")
    trial_document = document("opentrials.trial", {"trial_id": "demo"})
    path = store.write_document("OTR-demo-001", "trial", trial_document)
    checksums = store.write_checksums("OTR-demo-001")

    assert '"schema":"opentrials.trial"' in path.read_text()
    assert "trial.json" in checksums.read_text()
    with pytest.raises(FileExistsError):
        store.write_document("OTR-demo-001", "trial", trial_document)
