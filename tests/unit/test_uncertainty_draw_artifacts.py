from pathlib import Path

import pytest

from opentrials.core import Distribution, DistributionPurpose, DistributionType
from opentrials.storage.uncertainty_draws import UncertaintyDrawArtifactStore
from opentrials.uncertainty import (
    SamplingMethod,
    UncertainParameter,
    UncertaintySamplingPlan,
    UncertaintyScenario,
    materialize_uncertainty_draws,
)


def draws():
    scenario = UncertaintyScenario(
        scenario_id="OTUSC-dose-artifact-001",
        target_model_sha256="sha256:" + "a" * 64,
        parameters=(
            UncertainParameter(
                parameter_id="dose",
                target="intervention.aciclovir_iv.dose",
                distribution=Distribution(
                    distribution_type=DistributionType.EMPIRICAL,
                    purpose=DistributionPurpose.PARAMETER_UNCERTAINTY,
                    unit="mg",
                    values=(125.0, 250.0),
                ),
                evidence_ids=("evidence-dose",),
                provenance_ids=("provenance-dose",),
            ),
        ),
        sampling=UncertaintySamplingPlan(
            method=SamplingMethod.MONTE_CARLO, requested_draw_count=4, requested_seed=42
        ),
        evidence_ids=("evidence-scenario",),
        provenance_ids=("provenance-scenario",),
    )
    return materialize_uncertainty_draws(scenario)


def test_draw_artifact_is_immutable_and_hash_verified(tmp_path: Path) -> None:
    store = UncertaintyDrawArtifactStore(tmp_path / "draws")
    directory = store.create_draw_artifact("OTUDR-dose-001")
    manifest = store.write_draws("OTUDR-dose-001", draws())

    assert store.verify_draw_artifact("OTUDR-dose-001") == manifest
    assert manifest.table.rows == 4
    assert manifest.table.columns == 6
    assert (directory / "draws.parquet").is_file()
    with pytest.raises(FileExistsError, match="already exists"):
        store.write_draws("OTUDR-dose-001", draws())


def test_draw_artifact_rejects_unknown_id_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OTUDR"):
        UncertaintyDrawArtifactStore(tmp_path).create_draw_artifact("bad")
