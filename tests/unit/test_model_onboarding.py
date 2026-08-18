"""Contract tests for scaffold generation from a model discovery report.

Uses a hand-built ``ModelInspectionReport`` (the real discovery pass is
proven live in ``tests/integration/test_model_onboarding_live.py``) --
these tests are about what the scaffold does with a discovery, not about
discovery itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from opentrials.sdk.model_onboarding import (
    AdministrationDiscovery,
    ModelInspectionReport,
    generate_profile_scaffold,
)


def _report(**overrides: object) -> ModelInspectionReport:
    defaults: dict[str, object] = dict(
        pkml_path=Path("/fake/Example.pkml"),
        pkml_sha256="sha256:" + "a" * 64,
        name="Example Model",
        molecule_names=("ExampleDrug", "CYP3A4"),
        administrations=(
            AdministrationDiscovery(
                container="Events|Example Route|",
                parameter_paths=(
                    "Events|Example Route|Application_1|ProtocolSchemaItem|Dose",
                    "Events|Example Route|Application_1|ProtocolSchemaItem|Start time",
                ),
                roles={
                    "dose": "Events|Example Route|Application_1|ProtocolSchemaItem|Dose",
                    "start_time": (
                        "Events|Example Route|Application_1|ProtocolSchemaItem|Start time"
                    ),
                },
            ),
        ),
        output_paths=tuple(f"Organism|Path{i}" for i in range(20)),
        mutable_parameter_count=1234,
        population_support_detected=True,
        ospsuite_version="12.4.4",
        r_version="R version 4.6.1",
    )
    defaults.update(overrides)
    return ModelInspectionReport.model_validate(defaults)


def test_scaffold_is_syntactically_valid_python(tmp_path: Path) -> None:
    scaffold = generate_profile_scaffold(_report(), model_id="test.example")
    path = tmp_path / "scaffold.py"
    path.write_text(scaffold, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


def test_scaffold_refuses_to_import_until_reviewed(tmp_path: Path) -> None:
    scaffold = generate_profile_scaffold(_report(), model_id="test.example")
    path = tmp_path / "scaffold_guard.py"
    path.write_text(scaffold, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True
    )
    # Running the module body directly should raise NotImplementedError.
    assert completed.returncode != 0
    assert "NotImplementedError" in completed.stderr


def test_scaffold_prefills_discovered_administration_paths() -> None:
    scaffold = generate_profile_scaffold(_report(), model_id="test.example")

    assert "Events|Example Route|Application_1|ProtocolSchemaItem|Dose" in scaffold
    assert "Events|Example Route|Application_1|ProtocolSchemaItem|Start time" in scaffold


def test_scaffold_marks_unfound_roles_as_todo() -> None:
    report = _report(
        administrations=(
            AdministrationDiscovery(
                container="Events|No Roles Found|",
                parameter_paths=("Events|No Roles Found|Application_1|SomethingElse",),
                roles={},
            ),
        )
    )
    scaffold = generate_profile_scaffold(report, model_id="test.example")

    assert "TODO_dose_parameter_path" in scaffold
    assert "TODO_administration_time_parameter_path" in scaffold


def test_scaffold_lists_discovered_output_candidates_capped_at_fifteen() -> None:
    scaffold = generate_profile_scaffold(_report(), model_id="test.example")

    assert "Organism|Path0" in scaffold
    assert "Organism|Path14" in scaffold
    # Only 20 discovered in the fixture -- all fit under the cap of 15 shown
    # plus a "N more" line only when there truly are more than 15.
    assert "5 more" in scaffold


def test_scaffold_includes_provenance_facts() -> None:
    report = _report()
    scaffold = generate_profile_scaffold(report, model_id="test.example")

    assert str(report.pkml_path) in scaffold
    assert report.pkml_sha256 in scaffold
    assert "test.example" in scaffold
