"""Contract tests for sdk.experiment_lineage -- find, reproduce, fork, trace."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.compound import Compound, CompoundIdentity, Intervention, Regimen, Route
from opentrials.compound.intervention import Dose
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import sha256
from opentrials.patient import PopulationSpec
from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistrySource
from opentrials.registry.schema import ExperimentRecord, RegistryRecordKind
from opentrials.sdk.experiment_lineage import (
    ancestry,
    children,
    diff_trials,
    endpoint_summary_sha256,
    resolve_forked_from,
)
from opentrials.sdk.run import EndpointRecord
from opentrials.trials import (
    Endpoint,
    EndpointAggregation,
    EndpointType,
    MissingnessRule,
    TimeWindow,
    Trial,
    TrialArm,
)
from opentrials.trials.trial import RandomizationType


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def demo_trial(trial_id: str = "ACICLOVIR-DEMO", dose_mg: float = 250) -> Trial:
    intervention = Intervention(
        intervention_id="aciclovir-demo-intervention",
        compound=Compound(
            identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")
        ),
        regimen=Regimen(
            regimen_id="aciclovir-demo-regimen",
            doses=(
                Dose(
                    amount=assumed(dose_mg, "mg"),
                    route=Route.INTRAVENOUS,
                    administration_time=assumed(0, "min"),
                ),
            ),
        ),
    )
    return Trial(
        trial_id=trial_id,
        title="Aciclovir demo trial",
        question_of_interest="What plasma concentration does this dose produce?",
        population=PopulationSpec(
            id="aciclovir-demo-population", size=10, seed=1, generator_version="0.1.0"
        ),
        arms=(
            TrialArm(
                arm_id="standard", name="standard", intervention=intervention, allocation=1.0
            ),
        ),
        randomization=RandomizationType.NONE,
        endpoints=(
            Endpoint(
                endpoint_id="plasma-concentration",
                endpoint_type=EndpointType.PK,
                measurement="plasma aciclovir concentration",
                time_window=TimeWindow(start=assumed(0, "hour"), end=assumed(24, "hour")),
                aggregation=EndpointAggregation.RAW,
                missingness_rule=MissingnessRule.REPORT,
                analysis_method="PK endpoints",
                unit="umol/L",
            ),
        ),
        seed=1,
    )


def endpoints(*values: float) -> tuple[EndpointRecord, ...]:
    return tuple(
        EndpointRecord(
            arm_id="standard", subject_id=f"subj-{i}", endpoint_type="AUC", value=v, unit="mg*h/l"
        )
        for i, v in enumerate(values)
    )


@pytest.fixture
def backend(tmp_path: Path) -> FilesystemRegistryBackend:
    return FilesystemRegistryBackend(tmp_path / "registry")


def manual_source() -> RegistrySource:
    return RegistrySource(kind="manual_curation", identifier="test")


def put_experiment(
    backend: FilesystemRegistryBackend,
    trial: Trial,
    *,
    logical_id: str,
    forked_from_record_id: str | None = None,
) -> str:
    record = ExperimentRecord(
        trial_id=trial.trial_id,
        trial=trial,
        trial_sha256=sha256(trial),
        model_id="osp.aciclovir.vergin-1995-iv",
        run_id="OTR-population-abc123",
        title=trial.title,
        forked_from_record_id=forked_from_record_id,
    )
    manifest = backend.put(
        RegistryRecordKind.EXPERIMENT,
        record,
        logical_id=logical_id,
        evidence_class=EvidenceClass.SIMULATED,
        license="CC-BY-4.0",
        source=RegistrySource(kind="experiment_run", identifier="OTR-population-abc123"),
    )
    return manifest.record_id


def test_endpoint_summary_sha256_is_deterministic_and_order_independent() -> None:
    a = endpoints(1.0, 2.0, 3.0)
    b = tuple(reversed(a))
    assert endpoint_summary_sha256(a) == endpoint_summary_sha256(b)


def test_endpoint_summary_sha256_differs_for_a_different_value() -> None:
    a = endpoint_summary_sha256(endpoints(1.0, 2.0))
    b = endpoint_summary_sha256(endpoints(1.0, 2.5))
    assert a != b


def test_resolve_forked_from_returns_none_with_no_provenance(
    backend: FilesystemRegistryBackend,
) -> None:
    trial = demo_trial()
    assert resolve_forked_from(trial, backend=backend) is None


def test_resolve_forked_from_ignores_a_fake_provenance_string(
    backend: FilesystemRegistryBackend,
) -> None:
    trial = demo_trial().model_copy(
        update={"provenance_ids": ("OTREG-EXPERIMENT-not-a-real-record",)}
    )
    assert resolve_forked_from(trial, backend=backend) is None


def test_resolve_forked_from_finds_a_real_registered_parent(
    backend: FilesystemRegistryBackend,
) -> None:
    parent_record_id = put_experiment(backend, demo_trial(), logical_id="parent")
    forked_trial = demo_trial(trial_id="ACICLOVIR-FORK").model_copy(
        update={"provenance_ids": (parent_record_id,)}
    )
    assert resolve_forked_from(forked_trial, backend=backend) == parent_record_id


def test_ancestry_walks_the_fork_chain_self_first_root_last(
    backend: FilesystemRegistryBackend,
) -> None:
    root_id = put_experiment(backend, demo_trial(trial_id="ROOT"), logical_id="root")
    mid_id = put_experiment(
        backend, demo_trial(trial_id="MID"), logical_id="mid", forked_from_record_id=root_id
    )
    leaf_id = put_experiment(
        backend, demo_trial(trial_id="LEAF"), logical_id="leaf", forked_from_record_id=mid_id
    )

    chain = ancestry(leaf_id, backend=backend)
    assert [m.record_id for m in chain] == [leaf_id, mid_id, root_id]


def test_children_finds_only_direct_forks(backend: FilesystemRegistryBackend) -> None:
    root_id = put_experiment(backend, demo_trial(trial_id="ROOT"), logical_id="root")
    child_id = put_experiment(
        backend, demo_trial(trial_id="CHILD"), logical_id="child", forked_from_record_id=root_id
    )
    put_experiment(
        backend, demo_trial(trial_id="GRANDCHILD"), logical_id="grandchild",
        forked_from_record_id=child_id,
    )

    direct_children = children(root_id, backend=backend)
    assert [m.record_id for m in direct_children] == [child_id]


def test_diff_trials_reports_no_changes_for_identical_trials() -> None:
    trial = demo_trial()
    assert diff_trials(trial, trial) == []


def test_diff_trials_reports_a_changed_leaf_value() -> None:
    original = demo_trial(dose_mg=250)
    forked = demo_trial(dose_mg=125)

    changes = diff_trials(original, forked)

    dose_change = next(c for c in changes if c["path"].endswith("amount.value"))
    assert dose_change["change"] == "changed"
    assert dose_change["before"] == 250
    assert dose_change["after"] == 125


def test_diff_trials_reports_an_added_arm() -> None:
    original = demo_trial()
    extra_arm = original.arms[0].model_copy(update={"arm_id": "extra"})
    forked = original.model_copy(update={"arms": (*original.arms, extra_arm)})

    changes = diff_trials(original, forked)

    assert any(c["path"] == "arms[1]" and c["change"] == "added" for c in changes)
