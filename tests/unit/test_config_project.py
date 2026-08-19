"""Contract tests for versioned OpenTrials project YAML loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.config.project import ProjectConfigurationError, load_project

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


def test_load_project_parses_a_valid_document(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(VALID_PROJECT_YAML, encoding="utf-8")

    config = load_project(path)

    assert config.model_id == "osp.aciclovir.vergin-1995-iv"
    assert config.trial.trial_id == "DEMO-TRIAL"
    assert len(config.trial.arms) == 1
    assert config.population_generation_id is None


def test_load_project_rejects_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(
        "schema: opentrials.trial\nschema_version: 1.0.0\npayload: {}\n", encoding="utf-8"
    )

    with pytest.raises(ProjectConfigurationError, match="Expected schema"):
        load_project(path)


def test_load_project_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ProjectConfigurationError, match="mapping"):
        load_project(path)


def test_load_project_rejects_invalid_trial_payload(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(
        "schema: opentrials.project\nschema_version: 1.0.0\npayload: {trial: {}}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigurationError, match="Invalid project payload"):
        load_project(path)


def test_load_project_accepts_a_plain_string_path(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(VALID_PROJECT_YAML, encoding="utf-8")

    config = load_project(str(path))

    assert config.trial.trial_id == "DEMO-TRIAL"


def test_load_project_allows_omitted_model_id(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    without_model_id = VALID_PROJECT_YAML.replace(
        "  model_id: osp.aciclovir.vergin-1995-iv\n", ""
    )
    path.write_text(without_model_id, encoding="utf-8")

    config = load_project(path)

    assert config.model_id is None
