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
