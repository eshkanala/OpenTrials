"""Contract tests for the strict Studio<->SDK bridge (opentrials.studio.bridge).

These exercise the same functions ``server.py``'s routes call, without
FastAPI in the loop -- the bridge itself is framework-agnostic and every
number it returns must already have come from a real, SDK-validated
``ProjectConfig``, never computed here (see the module's own docstring).
"""

from __future__ import annotations

from pathlib import Path

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
