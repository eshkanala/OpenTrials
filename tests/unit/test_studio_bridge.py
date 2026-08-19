"""Contract tests for the strict Studio<->SDK bridge (opentrials.studio.bridge).

These exercise the same functions ``server.py``'s routes call, without
FastAPI in the loop -- the bridge itself is framework-agnostic and every
number it returns must already have come from a real, SDK-validated
``ProjectConfig``, never computed here (see the module's own docstring).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentrials.config.project import load_project
from opentrials.studio import bridge

VALID_PROJECT_YAML = """
schema: opentrials.project
schema_version: 1.0.0
payload:
  model_id: osp.aciclovir.vergin-1995-iv
  trial:
    trial_id: DEMO-TRIAL
    title: Demo trial
    question_of_interest: Does the dose matter?
    population:
      id: demo-population
      size: 10
      seed: 1
      generator_version: "0.1.0"
      age_range:
        minimum: {value: 18, unit: year, value_type: ASSUMED}
        maximum: {value: 65, unit: year, value_type: ASSUMED}
      sexes: [FEMALE]
    arms:
      - arm_id: standard
        name: standard
        allocation: 1.0
        intervention:
          intervention_id: standard-intervention
          compound:
            identity:
              compound_id: aciclovir
              preferred_name: Aciclovir
          regimen:
            regimen_id: standard-regimen
            doses:
              - amount: {value: 250, unit: mg, value_type: ASSUMED}
                route: INTRAVENOUS
                administration_time: {value: 0, unit: minute, value_type: ASSUMED}
                infusion_duration: {value: 10, unit: minute, value_type: ASSUMED}
    randomization: NONE
    endpoints:
      - endpoint_id: plasma-concentration
        endpoint_type: PK
        measurement: plasma aciclovir concentration
        time_window:
          start: {value: 0, unit: hour, value_type: ASSUMED}
          end: {value: 24, unit: hour, value_type: ASSUMED}
        aggregation: RAW
        missingness_rule: REPORT
        analysis_method: PK endpoints
        unit: umol/L
    seed: 1
"""


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    path = tmp_path / "project.yaml"
    path.write_text(VALID_PROJECT_YAML, encoding="utf-8")
    return path


def _arm_json(
    arm_id: str, dose_mg: float, allocation: float, *, infusion: bool = True
) -> dict[str, object]:
    identity = {"compound_id": "aciclovir", "preferred_name": "Aciclovir"}
    dose: dict[str, object] = {
        "amount": {"value": dose_mg, "unit": "mg", "value_type": "ASSUMED"},
        "route": "INTRAVENOUS",
        "administration_time": {"value": 0, "unit": "min", "value_type": "ASSUMED"},
    }
    if infusion:
        dose["infusion_duration"] = {"value": 10, "unit": "min", "value_type": "ASSUMED"}
    return {
        "arm_id": arm_id,
        "name": arm_id,
        "allocation": allocation,
        "intervention": {
            "intervention_id": f"{arm_id}-intervention",
            "compound": {"identity": identity},
            "regimen": {"regimen_id": f"{arm_id}-regimen", "doses": [dose]},
        },
    }


def test_open_project_reports_real_display_fields(project_path: Path) -> None:
    result = bridge.open_project(str(project_path))

    assert result["trial_id"] == "DEMO-TRIAL"
    assert result["model_id"] == "osp.aciclovir.vergin-1995-iv"
    assert result["resolved_model"]["id"] == "osp.aciclovir.vergin-1995-iv"
    assert result["model_error"] is None
    assert result["population"]["size"] == 10
    assert len(result["arms"]) == 1
    assert result["arms"][0]["dose"] == {"value": 250.0, "unit": "mg"}
    assert result["endpoints"][0]["aggregation"] == "RAW"
    assert result["endpoints"][0]["time_window"]["end"] == {"value": 24.0, "unit": "hour"}
    assert result["eligibility"] == {"inclusion": [], "exclusion": [], "narrative": None}
    assert result["evidence_ids"] == []


def test_open_project_wraps_configuration_errors(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("schema: opentrials.trial\nschema_version: 1.0.0\npayload: {}\n")

    with pytest.raises(bridge.StudioError):
        bridge.open_project(str(bad_path))


def test_validate_project_reports_the_same_checks_the_cli_reports(project_path: Path) -> None:
    result = bridge.validate_project(str(project_path))

    assert result["ok"] is True
    labels = [c["label"] for c in result["checks"]]
    assert labels == ["Trial", "Model", "Population", "Trial arms", "Endpoints"]
    assert all(c["status"] == "verified" for c in result["checks"])


def test_list_models_includes_registered_profiles() -> None:
    models = bridge.list_models()
    model_ids = {m["model_id"] for m in models}
    assert "osp.aciclovir.vergin-1995-iv" in model_ids
    assert "osp.midazolam.po-10mg-tablet" in model_ids


def test_save_project_edits_population_and_round_trips(project_path: Path) -> None:
    result = bridge.save_project(
        str(project_path), {"trial": {"population": {"size": 25, "seed": 7}}}
    )

    assert result["population"]["size"] == 25
    assert result["population"]["seed"] == 7

    reloaded = load_project(project_path)
    assert reloaded.trial.population.size == 25
    assert reloaded.trial.population.seed == 7
    # Everything else must be semantically unchanged.
    assert reloaded.trial.trial_id == "DEMO-TRIAL"
    assert len(reloaded.trial.arms) == 1
    assert reloaded.model_id == "osp.aciclovir.vergin-1995-iv"


def test_save_project_rejects_invalid_edit_and_leaves_file_untouched(project_path: Path) -> None:
    original_text = project_path.read_text(encoding="utf-8")

    with pytest.raises(bridge.StudioError):
        bridge.save_project(str(project_path), {"trial": {"population": {"size": 0}}})

    assert project_path.read_text(encoding="utf-8") == original_text


def test_save_project_can_clear_model_id(project_path: Path) -> None:
    result = bridge.save_project(str(project_path), {"model_id": None})

    assert result["model_id"] is None
    reloaded = load_project(project_path)
    assert reloaded.model_id is None


def test_save_project_replaces_the_arms_list_wholesale(project_path: Path) -> None:
    new_arms = [_arm_json("low", 125, 0.5), _arm_json("high", 250, 0.5)]

    result = bridge.save_project(
        str(project_path),
        {"trial": {"randomization": "PARALLEL", "arms": new_arms}},
    )

    assert result["randomization"] == "PARALLEL"
    assert [a["arm_id"] for a in result["arms"]] == ["low", "high"]

    reloaded = load_project(project_path)
    assert len(reloaded.trial.arms) == 2
    assert reloaded.trial.randomization.value == "PARALLEL"


def test_save_project_rejects_arms_that_do_not_match_randomization(project_path: Path) -> None:
    # NONE (the fixture's declared randomization) requires exactly one arm;
    # sending two without also switching randomization must fail loudly,
    # via the real Trial validator, not silently write an invalid protocol.
    new_arms = [_arm_json("a", 125, 0.5, infusion=False), _arm_json("b", 250, 0.5, infusion=False)]

    with pytest.raises(bridge.StudioError):
        bridge.save_project(str(project_path), {"trial": {"arms": new_arms}})


# ================= Run + Results (error paths only -- a real run needs OSP) =================


def test_start_run_raises_for_an_invalid_project(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("schema: opentrials.trial\nschema_version: 1.0.0\npayload: {}\n")

    with pytest.raises(bridge.StudioError):
        bridge.start_run(str(bad_path))


def test_start_run_raises_when_r_libs_user_is_unresolved(
    project_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Isolate from whatever the machine actually running this test has
    # configured (env var or a real config file) so this test's outcome
    # doesn't depend on the developer's own local OSP setup.
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="Run unavailable"):
        bridge.start_run(str(project_path))


def test_get_run_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_run("no-such-run")


def test_get_run_report_html_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_run_report_html("no-such-run")


def test_get_run_provenance_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_run_provenance("no-such-run")


# ================= Model Builder (error paths only -- inspection needs OSP) =================


def test_inspect_pkml_raises_when_r_libs_user_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="unavailable"):
        bridge.inspect_pkml(str(tmp_path / "model.pkml"))


def test_create_model_scaffold_raises_when_r_libs_user_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="unavailable"):
        bridge.create_model_scaffold(str(tmp_path / "model.pkml"), model_id="test-model")


# ================= Evidence Browser =================


def test_list_evidence_connectors_includes_the_registered_connectors() -> None:
    connectors = bridge.list_evidence_connectors()
    connector_ids = {c["connector_id"] for c in connectors}
    assert "osp.bundled.observed-aciclovir-vergin-1995-iv" in connector_ids
    assert "osp.bundled.observed-aciclovir-laskin-1982-group-d" in connector_ids


def test_run_evidence_connector_raises_for_an_unknown_connector_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.run_evidence_connector("no-such-connector")


def test_attach_evidence_to_project_raises_for_an_unknown_connector_id(project_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.attach_evidence_to_project(str(project_path), "no-such-connector")


def test_attach_evidence_to_project_raises_for_an_invalid_project(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("schema: opentrials.trial\nschema_version: 1.0.0\npayload: {}\n")

    with pytest.raises(bridge.StudioError):
        bridge.attach_evidence_to_project(
            str(bad_path), "osp.bundled.observed-aciclovir-vergin-1995-iv"
        )


# ================= Endpoint + eligibility editing =================


def test_save_project_edits_endpoints_and_round_trips(project_path: Path) -> None:
    new_endpoints = [
        {
            "endpoint_id": "cmax",
            "endpoint_type": "PK",
            "measurement": "peak plasma concentration",
            "time_window": {
                "start": {"value": 0, "unit": "hour", "value_type": "ASSUMED"},
                "end": {"value": 12, "unit": "hour", "value_type": "ASSUMED"},
            },
            "aggregation": "MAXIMUM",
            "missingness_rule": "EXCLUDE",
            "analysis_method": "PK endpoints",
            "unit": "umol/L",
        }
    ]

    result = bridge.save_project(str(project_path), {"trial": {"endpoints": new_endpoints}})

    assert result["endpoints"] == [
        {
            "endpoint_id": "cmax",
            "endpoint_type": "PK",
            "measurement": "peak plasma concentration",
            "time_window": {
                "start": {"value": 0.0, "unit": "hour"},
                "end": {"value": 12.0, "unit": "hour"},
            },
            "aggregation": "MAXIMUM",
            "missingness_rule": "EXCLUDE",
            "analysis_method": "PK endpoints",
            "unit": "umol/L",
        }
    ]
    reloaded = load_project(project_path)
    assert reloaded.trial.endpoints[0].endpoint_id == "cmax"
    assert reloaded.trial.endpoints[0].aggregation.value == "MAXIMUM"


def test_save_project_edits_eligibility_and_round_trips(project_path: Path) -> None:
    edits = {
        "trial": {
            "eligibility": {
                "inclusion": [
                    {
                        "criterion_id": "adult",
                        "field_path": "age.value",
                        "operator": "GREATER_THAN_OR_EQUAL",
                        "value": {"value": 18, "unit": "year", "value_type": "ASSUMED"},
                        "description": "Adults only",
                    }
                ],
                "exclusion": [],
            }
        }
    }

    result = bridge.save_project(str(project_path), edits)

    assert len(result["eligibility"]["inclusion"]) == 1
    assert result["eligibility"]["inclusion"][0]["criterion_id"] == "adult"
    assert result["eligibility"]["inclusion"][0]["value_kind"] == "scientific"

    reloaded = load_project(project_path)
    assert len(reloaded.trial.eligibility.inclusion) == 1
    assert reloaded.trial.eligibility.inclusion[0].field_path == "age.value"


def test_save_project_rejects_an_eligibility_criterion_with_a_bad_operator_value_pairing(
    project_path: Path,
) -> None:
    # GREATER_THAN requires a ScientificValue, not a bare list -- the real
    # EligibilityCriterion validator should reject this, not Studio.
    edits = {
        "trial": {
            "eligibility": {
                "inclusion": [
                    {
                        "criterion_id": "bad",
                        "field_path": "age.value",
                        "operator": "GREATER_THAN",
                        "value": ["not", "numeric"],
                        "description": None,
                    }
                ],
                "exclusion": [],
            }
        }
    }

    with pytest.raises(bridge.StudioError):
        bridge.save_project(str(project_path), edits)


# ================= Run history =================


def test_list_runs_returns_empty_for_a_missing_output_root(tmp_path: Path) -> None:
    assert bridge.list_runs(str(tmp_path / "does-not-exist")) == []


def test_list_runs_finds_population_and_trial_run_directories(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    population_run = output_root / "OTR-population-abc123"
    population_run.mkdir(parents=True)
    trial_run = output_root / "OTR-trial-def456"
    (trial_run / "trial_run").mkdir(parents=True)
    (output_root / "populations").mkdir()  # not an OTR-* dir, must be excluded
    (output_root / "not-a-run").mkdir()

    runs = bridge.list_runs(str(output_root))

    run_ids = {r["run_id"] for r in runs}
    assert run_ids == {"OTR-population-abc123", "OTR-trial-def456"}
    by_id = {r["run_id"]: r for r in runs}
    assert by_id["OTR-population-abc123"]["kind"] == "population"
    assert by_id["OTR-trial-def456"]["kind"] == "trial"


def test_get_historical_run_report_html_raises_for_a_missing_run(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_historical_run_report_html(str(tmp_path / "OTR-population-nope"))


def test_get_historical_run_result_data_raises_for_a_missing_run(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_historical_run_result_data(str(tmp_path / "OTR-population-nope"))


def test_get_run_result_data_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_run_result_data("no-such-run")


# ================= Physiology-state trials =================

MIDAZOLAM_PROJECT_YAML = """
schema: opentrials.project
schema_version: 1.0.0
payload:
  model_id: osp.midazolam.po-10mg-tablet
  trial:
    trial_id: MIDAZOLAM-DEMO
    title: Midazolam demo
    question_of_interest: Does the dose matter?
    population:
      id: demo-population
      size: 10
      seed: 1
      generator_version: "0.1.0"
    arms:
      - arm_id: standard
        name: standard
        allocation: 1.0
        intervention:
          intervention_id: standard-intervention
          compound:
            identity:
              compound_id: midazolam
              preferred_name: Midazolam
          regimen:
            regimen_id: standard-regimen
            doses:
              - amount: {value: 10, unit: mg, value_type: ASSUMED}
                route: ORAL
                administration_time: {value: 0, unit: minute, value_type: ASSUMED}
    randomization: NONE
    endpoints:
      - endpoint_id: plasma-concentration
        endpoint_type: PK
        measurement: plasma midazolam concentration
        time_window:
          start: {value: 0, unit: hour, value_type: ASSUMED}
          end: {value: 24, unit: hour, value_type: ASSUMED}
        aggregation: RAW
        missingness_rule: REPORT
        analysis_method: PK endpoints
        unit: umol/L
    seed: 1
"""


@pytest.fixture
def midazolam_project_path(tmp_path: Path) -> Path:
    path = tmp_path / "midazolam_project.yaml"
    path.write_text(MIDAZOLAM_PROJECT_YAML, encoding="utf-8")
    return path


def two_states() -> list[dict[str, object]]:
    return [
        {
            "state_id": "baseline",
            "target": "renal.glomerular_filtration_rate",
            "scale_factor": 1.0,
            "unit": "dimensionless",
            "purpose": "baseline",
        },
        {
            "state_id": "reduced",
            "target": "renal.glomerular_filtration_rate",
            "scale_factor": 0.6,
            "unit": "dimensionless",
            "purpose": "moderate renal impairment lever",
        },
    ]


def test_list_physiology_targets_returns_the_declared_target(project_path: Path) -> None:
    targets = bridge.list_physiology_targets(str(project_path))
    assert [t["target"] for t in targets] == ["renal.glomerular_filtration_rate"]


def test_list_physiology_targets_is_empty_for_a_model_without_any(
    midazolam_project_path: Path,
) -> None:
    assert bridge.list_physiology_targets(str(midazolam_project_path)) == []


def test_start_physiology_run_raises_when_model_has_no_physiology_targets(
    midazolam_project_path: Path,
) -> None:
    with pytest.raises(bridge.StudioError, match="no verified physiology"):
        bridge.start_physiology_run(
            str(midazolam_project_path), states=two_states(), baseline_state_id="baseline"
        )


def test_start_physiology_run_raises_with_fewer_than_two_states(project_path: Path) -> None:
    with pytest.raises(bridge.StudioError, match="at least two"):
        bridge.start_physiology_run(
            str(project_path), states=two_states()[:1], baseline_state_id="baseline"
        )


def test_start_physiology_run_raises_when_r_libs_user_is_unresolved(
    project_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="unavailable"):
        bridge.start_physiology_run(
            str(project_path), states=two_states(), baseline_state_id="baseline"
        )


def test_get_physiology_run_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_physiology_run("no-such-run")


# ================= Cohorts / subgroups =================


def test_list_cohort_fields_returns_the_registered_osp_population_fields() -> None:
    fields = bridge.list_cohort_fields()
    field_ids = {f["field_id"] for f in fields}
    assert "demographics.age" in field_ids
    assert "demographics.sex" in field_ids


def test_define_cohorts_for_run_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError, match="not a completed population"):
        bridge.define_cohorts_for_run("no-such-run", [])


def test_compare_cohorts_for_run_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError, match="not a completed population"):
        bridge.compare_cohorts_for_run(
            "no-such-run",
            group_a_membership_id="OTMEM-a",
            group_b_membership_id="OTMEM-b",
            group_a_label="a",
            group_b_label="b",
        )


# ================= Export =================


def test_export_project_yaml_round_trips_semantically(project_path: Path) -> None:
    exported = bridge.export_project_yaml(str(project_path))

    reopened_path = project_path.parent / "exported.yaml"
    reopened_path.write_text(exported, encoding="utf-8")
    original = load_project(project_path)
    reexported = load_project(reopened_path)

    assert reexported == original


def test_export_project_yaml_raises_for_an_invalid_project(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("schema: opentrials.trial\nschema_version: 1.0.0\npayload: {}\n")

    with pytest.raises(bridge.StudioError):
        bridge.export_project_yaml(str(bad_path))


def test_get_run_report_markdown_raises_for_an_unknown_run_id() -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_run_report_markdown("no-such-run")


def test_get_historical_run_report_markdown_raises_for_a_missing_run(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_historical_run_report_markdown(str(tmp_path / "OTR-population-nope"))


# ================= Registry =================


def test_list_registry_records_is_empty_for_a_fresh_root(tmp_path: Path) -> None:
    assert bridge.list_registry_records(root=str(tmp_path / "registry")) == []


def test_get_registry_record_raises_for_an_unknown_logical_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_registry_record("no-such-thing", root=str(tmp_path / "registry"))


def test_get_registry_matches_for_compound_is_empty_for_a_fresh_root(tmp_path: Path) -> None:
    result = bridge.get_registry_matches_for_compound("aciclovir", root=str(tmp_path / "registry"))
    assert result == {
        "compound_match": None,
        "dataset_matches": [],
        "parameter_evidence_matches": [],
    }


def test_get_registry_matches_for_compound_finds_a_seeded_compound(tmp_path: Path) -> None:
    from opentrials.compound import Compound, CompoundIdentity
    from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistrySource
    from opentrials.registry.schema import RegistryRecordKind

    backend = FilesystemRegistryBackend(tmp_path / "registry")
    backend.put(
        RegistryRecordKind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=RegistrySource(kind="manual_curation", identifier="test"),
    )

    result = bridge.get_registry_matches_for_compound("aciclovir", root=str(tmp_path / "registry"))

    assert result["compound_match"] is not None
    assert result["compound_match"]["compatibility"] == "HIGH"
    assert result["dataset_matches"] == []
    assert result["parameter_evidence_matches"] == []


def test_register_run_as_experiment_raises_for_an_unknown_run_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.register_run_as_experiment(
            "no-such-run", title="x", license="CC-BY-4.0", root=str(tmp_path / "registry")
        )


def test_fork_experiment_raises_for_an_unknown_logical_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.fork_experiment(
            "no-such-experiment",
            output_path=str(tmp_path / "forked.yaml"),
            root=str(tmp_path / "registry"),
        )


def test_fork_experiment_raises_when_the_target_record_is_not_an_experiment(
    tmp_path: Path,
) -> None:
    from opentrials.compound import Compound, CompoundIdentity
    from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistrySource
    from opentrials.registry.schema import RegistryRecordKind as _Kind

    backend = FilesystemRegistryBackend(tmp_path / "registry")
    backend.put(
        _Kind.COMPOUND,
        Compound(identity=CompoundIdentity(compound_id="aciclovir", preferred_name="Aciclovir")),
        logical_id="aciclovir",
        evidence_class=EvidenceClass.CURATED,
        license="CC-BY-4.0",
        source=RegistrySource(kind="manual_curation", identifier="test"),
    )

    with pytest.raises(bridge.StudioError, match="not an experiment record"):
        bridge.fork_experiment(
            "aciclovir",
            output_path=str(tmp_path / "forked.yaml"),
            root=str(tmp_path / "registry"),
        )


# ================= Guided Model Onboarding (Studio v0.4) =================


def test_start_model_draft_raises_when_r_libs_user_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="unavailable"):
        bridge.start_model_draft(str(tmp_path / "model.pkml"), model_id="osp.test.fake")


def test_get_model_draft_raises_for_an_unknown_draft_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_model_draft("no-such-draft", root=str(tmp_path / "onboarding"))


def _start_stub_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, model_id: str = "osp.test.fake"
) -> dict[str, Any]:
    """Create a draft directly through the SDK, bypassing ``bridge.start_model_draft``.

    ``start_model_draft`` requires a resolvable ``r_libs_user`` (real OSP)
    before it will even attempt inspection; the bridge-level behavior
    under test here is everything *after* a draft exists, so the draft is
    seeded the same way ``test_sdk_onboarding.py`` does -- a monkeypatched
    ``inspect_model`` -- without going through the bridge's OSP gate.
    """
    from opentrials.sdk import onboarding as sdk_onboarding
    from opentrials.sdk.model_onboarding import ModelInspectionReport

    def fake_inspect_model(pkml_path: Path, **kwargs: Any) -> ModelInspectionReport:
        return ModelInspectionReport(
            pkml_path=Path(pkml_path),
            pkml_sha256="sha256:" + "a" * 64,
            name="Fake Model",
            molecule_names=("Aciclovir",),
            output_paths=("Organism|VenousBlood|Plasma|Aciclovir|Concentration",),
            mutable_parameter_count=1,
            population_support_detected=True,
            ospsuite_version="12.0.0",
            r_version="4.6.0",
        )

    monkeypatch.setattr(sdk_onboarding, "inspect_model", fake_inspect_model)
    draft = sdk_onboarding.start_draft(
        tmp_path / "fake.pkml", model_id=model_id, root=tmp_path / "onboarding"
    )
    return draft.model_dump(mode="json")


def test_select_model_draft_capability_rejects_an_unknown_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    with pytest.raises(bridge.StudioError, match="Unknown onboarding slot"):
        bridge.select_model_draft_capability(
            draft["draft_id"], slot="not-a-real-slot", value={}, root=str(tmp_path / "onboarding")
        )


def test_select_model_draft_capability_rejects_an_invalid_evidence_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    with pytest.raises(bridge.StudioError):
        bridge.select_model_draft_capability(
            draft["draft_id"],
            slot="compound",
            value={"compound_id": "aciclovir", "engine_molecule_id": "Aciclovir"},
            evidence_class="NOT_A_REAL_EVIDENCE_CLASS",
            root=str(tmp_path / "onboarding"),
        )


def test_get_model_draft_checklist_reports_unmet_requirements_on_a_fresh_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    result = bridge.get_model_draft_checklist(draft["draft_id"], root=str(tmp_path / "onboarding"))
    assert result["ok"] is False
    assert any(c["status"] == "absent" for c in result["checks"])


def test_register_model_from_draft_raises_when_the_checklist_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    with pytest.raises(bridge.StudioError, match="unmet requirement"):
        bridge.register_model_from_draft(
            draft["draft_id"],
            draft_root=str(tmp_path / "onboarding"),
            registry_root=str(tmp_path / "registry"),
        )


def test_register_model_from_draft_writes_real_registry_records_once_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentrials.sdk import onboarding as sdk_onboarding

    onboarding_root = str(tmp_path / "onboarding")
    draft = _start_stub_draft(tmp_path, monkeypatch)
    draft_id = draft["draft_id"]

    bridge.select_model_draft_capability(
        draft_id,
        slot="compound",
        value={"compound_id": "aciclovir", "engine_molecule_id": "Aciclovir"},
        evidence_class="CURATED",
        root=onboarding_root,
    )
    bridge.select_model_draft_capability(
        draft_id,
        slot="administration",
        value={
            "target_id": "iv-target",
            "route": "INTRAVENOUS",
            "administration_container_path": "Events|IV|",
            "dose_parameter_path": "Events|IV|Dose",
            "dose_unit": "mg",
            "administration_time_parameter_path": "Events|IV|Start time",
            "administration_time_unit": "min",
            "supported_doses": [250.0],
            "supported_dose_unit": "mg",
        },
        evidence_class="ASSUMED",
        root=onboarding_root,
    )
    bridge.select_model_draft_capability(
        draft_id,
        slot="output",
        value={
            "output_id": "plasma",
            "parameter_path": "Organism|VenousBlood|Plasma|Aciclovir|Concentration",
            "analyte": "aciclovir",
            "matrix": "plasma",
            "fraction": "total",
            "measurement": "concentration",
            "unit": "mg/l",
            "time_unit": "h",
        },
        evidence_class="ASSUMED",
        root=onboarding_root,
    )
    bridge.select_model_draft_capability(
        draft_id, slot="applicability", value={"species": ["human"]}, evidence_class="ASSUMED",
        root=onboarding_root,
    )
    bridge.set_model_draft_metadata(
        draft_id, model_version="1.0.0", license="CC-BY-4.0", root=onboarding_root
    )
    bridge.set_model_draft_unsupported_capabilities(draft_id, items=[], root=onboarding_root)

    # The live run itself needs real OSP; recording its outcome does not --
    # this calls the same sdk function `record_model_draft_verification`
    # would call after confirming a real completed run.
    sdk_onboarding.record_verification_run(
        draft_id, run_id="OTR-population-fake123", endpoint_types=("AUC",), root=onboarding_root
    )

    result = bridge.register_model_from_draft(
        draft_id, draft_root=onboarding_root, registry_root=str(tmp_path / "registry")
    )

    assert result["model"]["kind"] == "MODEL"
    assert result["verification"]["kind"] == "MODEL_VERIFICATION"


def test_start_model_draft_verification_run_raises_when_not_yet_buildable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    with pytest.raises(bridge.StudioError, match="Cannot start a verification run"):
        bridge.start_model_draft_verification_run(
            draft["draft_id"],
            path=str(tmp_path / "project.yaml"),
            root=str(tmp_path / "onboarding"),
        )


def test_record_model_draft_verification_raises_for_an_unknown_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _start_stub_draft(tmp_path, monkeypatch)
    with pytest.raises(bridge.StudioError, match="has not completed successfully"):
        bridge.record_model_draft_verification(
            draft["draft_id"], run_id="no-such-run", root=str(tmp_path / "onboarding")
        )


# ================= Registry Curation Pipeline =================


def test_run_connector_for_curation_raises_when_r_libs_user_is_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setenv("OPENTRIALS_CONFIG", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(bridge.StudioError, match="unavailable"):
        bridge.run_connector_for_curation("osp.bundled.observed-aciclovir-vergin-1995-iv")


def test_get_curation_candidate_raises_for_an_unknown_candidate_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_curation_candidate("no-such-candidate", root=str(tmp_path / "curation"))


def _make_bridge_curation_candidate(tmp_path: Path) -> dict[str, Any]:
    """Seed a real candidate via the SDK directly, bypassing the OSP-gated bridge entry point."""
    from datetime import UTC, datetime

    from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
    from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
    from opentrials.core.scientific_value import ScientificValue, ValueType
    from opentrials.evidence.connector import (
        DataConnectorIdentity,
        DataConnectorRunResult,
        RawSnapshot,
        SourceDescriptor,
        TransformationStep,
    )
    from opentrials.sdk import curation as sdk_curation
    from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
    from opentrials.validation.study import DatasetRole

    def sv(value: float, unit: str) -> ScientificValue:
        return ScientificValue(value=value, unit=unit, value_type=ValueType.OBSERVED)

    class FakeConnector:
        @property
        def identity(self) -> DataConnectorIdentity:
            return DataConnectorIdentity(connector_id="test.fake-bridge-connector", version="0.0.1")

        def fetch(self) -> RawSnapshot:
            return RawSnapshot(
                content=b"{}",
                media_type="application/json",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

        def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
            evidence = Evidence(
                id="EV-fake-001",
                source_type=EvidenceSourceType.PUBLIC_DATASET,
                source_identifier="fake-source-001",
                license="CC0",
            )
            intervention = Intervention(
                intervention_id="fake-intervention",
                compound=Compound(
                    identity=CompoundIdentity(compound_id="fake", preferred_name="Fake")
                ),
                regimen=Regimen(
                    regimen_id="fake-regimen",
                    doses=(
                        Dose(
                            amount=sv(1, "mg"),
                            route=Route.INTRAVENOUS,
                            administration_time=sv(0, "minute"),
                        ),
                    ),
                ),
            )
            dataset = ObservedDataset(
                dataset_id="OTOBS-fake-bridge-001",
                role=DatasetRole.CALIBRATION,
                study=ObservedStudy(
                    study_id="fake-study",
                    title="Fake study",
                    evidence_ids=(evidence.id,),
                    population_description="Synthetic",
                    intervention=intervention,
                ),
                observations=(
                    ObservedPkObservation(
                        observation_id="fake-obs-001",
                        subject_or_population_id="fake-subject",
                        time=sv(0, "minute"),
                        value=sv(1.0, "mg/L"),
                        analyte="fake",
                        matrix="plasma",
                        fraction="total",
                        measurement="concentration",
                        evidence_ids=(evidence.id,),
                    ),
                ),
                license="CC0",
                source_identifier="fake-source-001",
                provenance_ids=(evidence.id,),
            )
            return DataConnectorRunResult(
                identity=self.identity,
                source=SourceDescriptor(
                    accession="fake-source-001", license="CC0", retrieved_at=snapshot.retrieved_at
                ),
                raw_snapshot=snapshot,
                transformation_provenance=(TransformationStep(description="Parsed fake rows."),),
                evidence=EvidenceSet(evidence=(evidence,)),
                dataset=dataset,
            )

    result = sdk_curation.create_candidate_from_connector(
        FakeConnector(), root=tmp_path / "curation"
    )
    assert isinstance(result, sdk_curation.CurationCandidate)
    return result.model_dump(mode="json")


def test_get_curation_checklist_reports_unmet_requirements_on_a_fresh_candidate(
    tmp_path: Path,
) -> None:
    candidate = _make_bridge_curation_candidate(tmp_path)
    result = bridge.get_curation_checklist(
        candidate["candidate_id"],
        curation_root=str(tmp_path / "curation"),
        registry_root=str(tmp_path / "registry"),
    )
    assert result["ok"] is False


def test_accept_curation_candidate_raises_when_checklist_is_incomplete(tmp_path: Path) -> None:
    candidate = _make_bridge_curation_candidate(tmp_path)
    with pytest.raises(bridge.StudioError, match="unmet requirement"):
        bridge.accept_curation_candidate(
            candidate["candidate_id"],
            curation_root=str(tmp_path / "curation"),
            registry_root=str(tmp_path / "registry"),
        )


def test_full_curation_review_and_accept_via_the_bridge(tmp_path: Path) -> None:
    curation_root = str(tmp_path / "curation")
    registry_root = str(tmp_path / "registry")
    candidate = _make_bridge_curation_candidate(tmp_path)
    candidate_id = candidate["candidate_id"]

    bridge.set_curation_candidate_identity(
        candidate_id, logical_id="fake.dataset", evidence_class="MEASURED", root=curation_root
    )
    bridge.set_curation_candidate_compatibility(
        candidate_id, model_ids=("osp.fake.model",), root=curation_root
    )
    bridge.mark_curation_license_reviewed(candidate_id, root=curation_root)
    bridge.acknowledge_curation_identity(candidate_id, root=curation_root)

    checklist = bridge.get_curation_checklist(
        candidate_id, curation_root=curation_root, registry_root=registry_root
    )
    assert checklist["ok"] is True

    result = bridge.accept_curation_candidate(
        candidate_id, curation_root=curation_root, registry_root=registry_root
    )
    assert result["kind"] == "DATASET"
    assert result["evidence_class"] == "MEASURED"


def test_reject_curation_candidate_records_a_reason(tmp_path: Path) -> None:
    candidate = _make_bridge_curation_candidate(tmp_path)
    result = bridge.reject_curation_candidate(
        candidate["candidate_id"], reason="duplicate", root=str(tmp_path / "curation")
    )
    assert result["outcome"] == "REJECTED"
    assert result["rejection_reason"] == "duplicate"


# ================= Parameter Evidence (Registry v0.2) =================


def test_list_parameter_identities_includes_the_curated_vocabulary() -> None:
    identities = bridge.list_parameter_identities()
    canonical_ids = {i["canonical_id"] for i in identities}
    assert "renal_clearance" in canonical_ids


def test_propose_parameter_evidence_rejects_an_incompatible_unit(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError, match="not dimensionally compatible"):
        bridge.propose_parameter_evidence(
            compound_id="aciclovir",
            canonical_parameter_id="renal_clearance",
            value=1.0,
            unit="L",
            value_type="OBSERVED",
            citation_url="https://example.org/label",
            citation_title="Example label",
            citation_excerpt="Renal clearance was reported as 3.5 L/hour.",
            root=str(tmp_path / "curation"),
        )


def test_propose_parameter_evidence_persists_a_reviewable_candidate(tmp_path: Path) -> None:
    result = bridge.propose_parameter_evidence(
        compound_id="aciclovir",
        canonical_parameter_id="renal_clearance",
        value=3.5,
        unit="L/hour",
        value_type="OBSERVED",
        citation_url="https://example.org/label",
        citation_title="Example label",
        citation_excerpt="Renal clearance was reported as 3.5 L/hour.",
        species="human",
        root=str(tmp_path / "curation"),
    )
    assert result["outcome"] == "PENDING"
    assert result["value"]["value"] == 3.5

    listed = bridge.list_parameter_evidence_candidates(root=str(tmp_path / "curation"))
    assert len(listed) == 1

    fetched = bridge.get_parameter_evidence_candidate(
        result["candidate_id"], root=str(tmp_path / "curation")
    )
    assert fetched["candidate_id"] == result["candidate_id"]


def test_get_parameter_evidence_candidate_raises_for_an_unknown_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_parameter_evidence_candidate(
            "no-such-candidate", root=str(tmp_path / "curation")
        )


def test_full_parameter_evidence_review_and_accept_via_the_bridge(tmp_path: Path) -> None:
    curation_root = str(tmp_path / "curation")
    registry_root = str(tmp_path / "registry")
    candidate = bridge.propose_parameter_evidence(
        compound_id="aciclovir",
        canonical_parameter_id="renal_clearance",
        value=3.5,
        unit="L/hour",
        value_type="OBSERVED",
        citation_url="https://example.org/label",
        citation_title="Example label",
        citation_excerpt="Renal clearance was reported as 3.5 L/hour.",
        species="human",
        root=curation_root,
    )
    candidate_id = candidate["candidate_id"]

    bridge.set_parameter_evidence_identity(
        candidate_id,
        logical_id="aciclovir.renal_clearance.example",
        evidence_class="MEASURED",
        root=curation_root,
    )
    bridge.mark_parameter_evidence_citation_reviewed(candidate_id, root=curation_root)

    checklist = bridge.get_parameter_evidence_checklist(
        candidate_id, curation_root=curation_root, registry_root=registry_root
    )
    assert checklist["ok"] is True

    result = bridge.accept_parameter_evidence_candidate(
        candidate_id, curation_root=curation_root, registry_root=registry_root
    )
    assert result["kind"] == "PARAMETER_EVIDENCE"
    assert result["evidence_class"] == "MEASURED"


def test_reject_parameter_evidence_candidate_records_a_reason(tmp_path: Path) -> None:
    candidate = bridge.propose_parameter_evidence(
        compound_id="aciclovir",
        canonical_parameter_id="renal_clearance",
        value=3.5,
        unit="L/hour",
        value_type="OBSERVED",
        citation_url="https://example.org/label",
        citation_title="Example label",
        citation_excerpt="Renal clearance was reported as 3.5 L/hour.",
        root=str(tmp_path / "curation"),
    )
    result = bridge.reject_parameter_evidence_candidate(
        candidate["candidate_id"], reason="not a primary source", root=str(tmp_path / "curation")
    )
    assert result["outcome"] == "REJECTED"
    assert result["rejection_reason"] == "not a primary source"


# ================= Experiment lineage + reproduction =================


def _put_bridge_experiment(
    tmp_path: Path, *, trial_id: str, logical_id: str, forked_from_record_id: str | None = None
) -> str:
    from opentrials.core.serialization import sha256
    from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistrySource
    from opentrials.registry.schema import ExperimentRecord, RegistryRecordKind

    config = load_project(_write_valid_project(tmp_path, trial_id))
    real_trial = config.trial
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    record = ExperimentRecord(
        trial_id=real_trial.trial_id,
        trial=real_trial,
        trial_sha256=sha256(real_trial),
        model_id=config.model_id or "osp.aciclovir.vergin-1995-iv",
        run_id="OTR-population-abc123",
        title=real_trial.title,
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


def _write_valid_project(tmp_path: Path, trial_id: str) -> Path:
    path = tmp_path / f"{trial_id}.yaml"
    path.write_text(VALID_PROJECT_YAML.replace("DEMO-TRIAL", trial_id), encoding="utf-8")
    return path


def test_get_experiment_ancestry_raises_for_an_unknown_logical_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.get_experiment_ancestry("no-such-experiment", root=str(tmp_path / "registry"))


def test_get_experiment_ancestry_returns_just_self_with_no_parent(tmp_path: Path) -> None:
    _put_bridge_experiment(tmp_path, trial_id="ROOT-TRIAL", logical_id="root")
    ancestry = bridge.get_experiment_ancestry("root", root=str(tmp_path / "registry"))
    assert len(ancestry) == 1
    assert ancestry[0]["logical_id"] == "root"


def test_get_experiment_children_finds_a_direct_fork(tmp_path: Path) -> None:
    root_record_id = _put_bridge_experiment(tmp_path, trial_id="ROOT-TRIAL", logical_id="root")
    _put_bridge_experiment(
        tmp_path, trial_id="CHILD-TRIAL", logical_id="child", forked_from_record_id=root_record_id
    )
    kids = bridge.get_experiment_children("root", root=str(tmp_path / "registry"))
    assert [k["logical_id"] for k in kids] == ["child"]


def test_diff_experiment_against_project_reports_a_changed_population_size(
    tmp_path: Path,
) -> None:
    _put_bridge_experiment(tmp_path, trial_id="ROOT-TRIAL", logical_id="root")
    forked_path = tmp_path / "forked.yaml"
    forked_path.write_text(
        VALID_PROJECT_YAML.replace("DEMO-TRIAL", "ROOT-TRIAL").replace("size: 10", "size: 42"),
        encoding="utf-8",
    )
    changes = bridge.diff_experiment_against_project(
        "root", project_path=str(forked_path), root=str(tmp_path / "registry")
    )
    assert any(c["path"].endswith("population.size") for c in changes)


def test_start_reproduction_run_raises_for_an_unknown_logical_id(tmp_path: Path) -> None:
    with pytest.raises(bridge.StudioError):
        bridge.start_reproduction_run("no-such-experiment", root=str(tmp_path / "registry"))


def test_check_reproduction_raises_for_an_incomplete_run() -> None:
    with pytest.raises(bridge.StudioError, match="has not completed successfully"):
        bridge.check_reproduction("no-such-run", expected_hash="sha256:" + "a" * 64)
