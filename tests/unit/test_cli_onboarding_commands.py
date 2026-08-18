"""Contract tests for `opentrials init`, `models list/show`, and `model inspect/init`.

`model inspect`/`model init` are tested here with a monkeypatched
``inspect_model`` (no OSP needed) since they're thin CLI plumbing around
it; the real discovery pass against real OSP is proven live in
``tests/integration/test_model_onboarding_live.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentrials.cli.main import main
from opentrials.sdk.model_onboarding import AdministrationDiscovery, ModelInspectionReport


def _fake_report(pkml_path: Path) -> ModelInspectionReport:
    return ModelInspectionReport(
        pkml_path=pkml_path,
        pkml_sha256="sha256:" + "a" * 64,
        name="Fake Model",
        molecule_names=("FakeDrug",),
        administrations=(
            AdministrationDiscovery(
                container="Events|Fake Route|",
                parameter_paths=("Events|Fake Route|Application_1|ProtocolSchemaItem|Dose",),
                roles={"dose": "Events|Fake Route|Application_1|ProtocolSchemaItem|Dose"},
            ),
        ),
        output_paths=("Organism|FakeOutput",),
        mutable_parameter_count=42,
        population_support_detected=True,
        ospsuite_version="12.4.4",
        r_version="R version 4.6.1",
    )


def test_init_creates_a_working_project_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "project.yaml"
    monkeypatch.setattr("sys.argv", ["opentrials", "init", "--output", str(output_path)])

    exit_code = main()

    assert exit_code == 0
    assert output_path.is_file()
    assert "Project created" in capsys.readouterr().out


def test_init_refuses_to_overwrite_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "project.yaml"
    output_path.write_text("existing content", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["opentrials", "init", "--output", str(output_path)])

    exit_code = main()

    assert exit_code == 1
    assert "Refusing to overwrite" in capsys.readouterr().out
    assert output_path.read_text(encoding="utf-8") == "existing content"


def test_models_list_shows_the_registered_aciclovir_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["opentrials", "models", "list"])

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "osp.aciclovir.vergin-1995-iv" in output


def test_models_show_prints_full_capability_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["opentrials", "models", "show", "osp.aciclovir.vergin-1995-iv"]
    )

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "aciclovir" in output
    assert "INTRAVENOUS" in output
    assert "repeated_dosing" in output


def test_models_show_reports_unknown_model_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["opentrials", "models", "show", "does.not.exist"])

    exit_code = main()

    assert exit_code == 1
    assert "Unknown model" in capsys.readouterr().out


def test_model_inspect_prints_the_discovery_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pkml_path = tmp_path / "fake.pkml"
    pkml_path.write_text("not a real pkml", encoding="utf-8")
    monkeypatch.setattr(
        "opentrials.cli.model_commands.inspect_model",
        lambda path, r_libs_user, rscript_path, dotnet_root: _fake_report(path),
    )
    monkeypatch.setattr("sys.argv", ["opentrials", "model", "inspect", str(pkml_path)])

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "FakeDrug" in output
    assert "does not imply OpenTrials capability verification" in output


def test_model_init_writes_a_reviewable_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pkml_path = tmp_path / "fake.pkml"
    pkml_path.write_text("not a real pkml", encoding="utf-8")
    output_path = tmp_path / "scaffold.py"
    monkeypatch.setattr(
        "opentrials.cli.model_commands.inspect_model",
        lambda path, r_libs_user, rscript_path, dotnet_root: _fake_report(path),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "opentrials", "model", "init", str(pkml_path),
            "--model-id", "test.fake", "--output", str(output_path),
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert output_path.is_file()
    content = output_path.read_text(encoding="utf-8")
    assert "NotImplementedError" in content
    assert "REQUIRED REVIEW" in content
