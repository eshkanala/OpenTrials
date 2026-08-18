"""Contract tests for the `opentrials init` project scaffold generator.

The scaffold must actually run, not just look plausible -- every test
here loads the generated YAML through the real ``config.project.load_project``
validator, the same one the CLI itself uses.
"""

from __future__ import annotations

from pathlib import Path

from opentrials.config.project import load_project
from opentrials.sdk.project_scaffold import generate_project_scaffold


def test_generated_scaffold_loads_as_a_valid_project(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text(generate_project_scaffold(), encoding="utf-8")

    config = load_project(path)

    assert config.trial.trial_id == "MY-FIRST-TRIAL"
    assert config.model_id == "osp.aciclovir.vergin-1995-iv"
    assert len(config.trial.arms) == 1


def test_generated_scaffold_respects_custom_fields(tmp_path: Path) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text(
        generate_project_scaffold(
            filename="custom.yaml",
            trial_id="CUSTOM-TRIAL",
            title="Custom title",
            population_id="custom-population",
        ),
        encoding="utf-8",
    )

    config = load_project(path)

    assert config.trial.trial_id == "CUSTOM-TRIAL"
    assert config.trial.title == "Custom title"
    assert config.trial.population.id == "custom-population"


def test_generated_scaffold_mentions_its_own_filename(tmp_path: Path) -> None:
    content = generate_project_scaffold(filename="my-study.yaml")
    assert "opentrials validate my-study.yaml" in content
