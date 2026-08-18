"""Contract tests for the thin CLI: argument parsing, schema routing, rendering.

Deliberately does not exercise a real ``run`` against OSP -- that is what
the SDK's own tests and the live integration suite are for. This file only
proves the CLI dispatches correctly and renders what the SDK gives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.cli.main import _sniff_schema, main

PROJECT_YAML = """
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
            identity: {compound_id: aciclovir, preferred_name: Aciclovir}
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


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_sniff_schema_reads_the_schema_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "project.yaml", PROJECT_YAML)
    assert _sniff_schema(path) == "opentrials.project"


def test_sniff_schema_returns_none_for_invalid_yaml(tmp_path: Path) -> None:
    path = _write(tmp_path, "broken.yaml", "not: valid: yaml: [")
    assert _sniff_schema(path) is None


def test_sniff_schema_returns_none_for_non_mapping_yaml(tmp_path: Path) -> None:
    path = _write(tmp_path, "list.yaml", "- a\n- b\n")
    assert _sniff_schema(path) is None


def test_sniff_schema_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    assert _sniff_schema(tmp_path / "does-not-exist.yaml") is None


def test_validate_project_yaml_prints_a_pass_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "project.yaml", PROJECT_YAML)
    monkeypatch.setattr("sys.argv", ["opentrials", "validate", str(path)])

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "DEMO-TRIAL" in output
    assert "osp.aciclovir.vergin-1995-iv" in output
    assert "Configuration valid" in output


def test_validate_rejects_an_invalid_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(
        tmp_path,
        "project.yaml",
        "schema: opentrials.project\nschema_version: 1.0.0\npayload: {trial: {}}\n",
    )
    monkeypatch.setattr("sys.argv", ["opentrials", "validate", str(path)])

    exit_code = main()

    assert exit_code == 1
    assert "Configuration invalid" in capsys.readouterr().out


def test_run_without_r_libs_user_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "project.yaml", PROJECT_YAML)
    monkeypatch.delenv("R_LIBS_USER", raising=False)
    monkeypatch.setattr("sys.argv", ["opentrials", "run", str(path)])

    exit_code = main()

    assert exit_code == 2
    assert "r-libs-user" in capsys.readouterr().out.lower()
