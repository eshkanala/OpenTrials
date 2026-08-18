"""OpenTrials command-line interface.

Deliberately thin: every command parses arguments, calls the public
``opentrials`` SDK, and renders the result -- no scientific logic lives
here. A future GUI is expected to be a second such client of the exact same
SDK. Two YAML schemas are accepted and auto-detected: the original
``opentrials.trial`` (the v0.1 single-individual engineering workflow,
unchanged) and the newer ``opentrials.project`` (population/multi-arm-trial
execution through the SDK's ``Project``).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from opentrials.cli.progress import ProgressRenderer
from opentrials.config import TrialConfigurationError, load_trial
from opentrials.config.project import ProjectConfigurationError
from opentrials.orchestration import run_aciclovir_iv_engineering
from opentrials.reporting import (
    build_population_report,
    build_trial_report,
    render_html,
    render_markdown,
)
from opentrials.sdk.project import Project

PROJECT_SCHEMA = "opentrials.project"


def _sniff_schema(path: Path) -> str | None:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if isinstance(raw, dict):
        schema = raw.get("schema")
        return schema if isinstance(schema, str) else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="opentrials")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate", help="Validate a versioned trial or project YAML configuration."
    )
    validate.add_argument("config", type=Path)

    run = commands.add_parser(
        "run", help="Execute a versioned trial or project YAML configuration."
    )
    run.add_argument("config", type=Path)
    run.add_argument("--output-root", type=Path, default=Path("runs"))
    run.add_argument("--r-libs-user", default=os.environ.get("R_LIBS_USER"))
    run.add_argument(
        "--verbose", action="store_true", help="Print every event's detail, not just its stage."
    )

    report = commands.add_parser(
        "report", help="Render a human-readable report from an already-executed run directory."
    )
    report.add_argument("run_directory", type=Path)
    report.add_argument(
        "--population-root",
        type=Path,
        required=True,
        help="The population artifact root the run was executed against.",
    )
    report.add_argument("--format", choices=("markdown", "html"), default="markdown")
    report.add_argument("--output", type=Path, default=None)

    arguments = parser.parse_args()

    if arguments.command == "report":
        return _report(arguments)

    schema = _sniff_schema(arguments.config)
    if arguments.command == "validate":
        return _validate(arguments.config, schema)
    if arguments.command == "run":
        return _run(arguments.config, schema, arguments)
    return 2


def _validate(path: Path, schema: str | None) -> int:
    if schema == PROJECT_SCHEMA:
        try:
            project = Project.load(path)
        except ProjectConfigurationError as error:
            print(f"Configuration invalid: {error}")
            return 1
        trial = project.trial
        print("OpenTrials Configuration Validation\n")
        print(f"Trial                 ✓ {trial.trial_id}")
        try:
            model = project.model()
            print(f"Model                 ✓ {model.package.manifest.id}")
        except ValueError as error:
            print(f"Model                 ✗ {error}")
            return 1
        print(f"Population            ✓ {trial.population.id} ({trial.population.size})")
        print(f"Trial arms            ✓ {len(trial.arms)} arm(s)")
        print(f"Endpoints             ✓ {len(trial.endpoints)}")
        print("\nConfiguration valid. No simulation was run.")
        return 0

    # Default/fallback: the original opentrials.trial schema.
    try:
        trial = load_trial(path)
    except TrialConfigurationError as error:
        print(f"Configuration invalid: {error}")
        return 1
    print("OpenTrials Configuration Validation\n")
    print(f"Trial                 ✓ {trial.trial_id}")
    print(f"Population            ✓ {trial.population.id}")
    print(f"Intervention          ✓ {len(trial.arms)} arm(s)")
    print("Dose units            ✓")
    print(f"Endpoints             ✓ {len(trial.endpoints)}")
    print("Engine requirements   ✓ deferred to adapter validation")
    print("\nConfiguration valid. No simulation was run.")
    return 0


def _run(path: Path, schema: str | None, arguments: argparse.Namespace) -> int:
    if arguments.r_libs_user is None:
        print("Run unavailable: set --r-libs-user or R_LIBS_USER for the local ospsuite library.")
        return 2

    if schema == PROJECT_SCHEMA:
        return _run_project(path, arguments)
    return _run_legacy_trial(path, arguments)


def _run_project(path: Path, arguments: argparse.Namespace) -> int:
    try:
        project = Project.load(path)
    except ProjectConfigurationError as error:
        print(f"Configuration invalid: {error}")
        return 1

    renderer = ProgressRenderer(
        title=project.trial.title,
        trial_id=project.trial.trial_id,
        verbose=arguments.verbose,
        is_tty=sys.stdout.isatty(),
    )
    try:
        model = project.model()
    except ValueError as error:
        print(f"Run failed: {error}")
        return 1
    renderer.start(model_id=model.package.manifest.id)
    try:
        run = project.run(
            output_root=arguments.output_root,
            r_libs_user=arguments.r_libs_user,
            events=renderer.on_event,
        )
    except (TrialConfigurationError, OSError, ValueError, RuntimeError) as error:
        renderer.finish(failed=True)
        print(f"\nRun failed: {error}")
        return 1
    renderer.finish(failed=False)
    print()
    print(run.summary())
    print(f"\nRun directory: {run.run_directory}")
    return 0


def _report(arguments: argparse.Namespace) -> int:
    run_directory: Path = arguments.run_directory
    population_root: Path = arguments.population_root
    is_trial = (run_directory / "trial_run").is_dir()
    try:
        data = (
            build_trial_report(run_directory, population_root)
            if is_trial
            else build_population_report(run_directory, population_root)
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"Report failed: could not verify this run: {error}")
        return 1

    rendered = render_html(data) if arguments.format == "html" else render_markdown(data)
    default_name = "report.html" if arguments.format == "html" else "report.md"
    output_path = arguments.output or Path(default_name)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Report written: {output_path}")
    return 0


def _run_legacy_trial(path: Path, arguments: argparse.Namespace) -> int:
    try:
        trial = load_trial(path)
        started = time.monotonic()
        run_result = run_aciclovir_iv_engineering(
            trial,
            output_root=arguments.output_root,
            r_libs_user=arguments.r_libs_user,
            progress=lambda stage: print(
                f"[✓] {stage.replace('_', ' ')} ({time.monotonic() - started:.1f}s)"
            ),
        )
    except (TrialConfigurationError, OSError, ValueError, RuntimeError) as error:
        print(f"Run failed: {error}")
        return 1
    print(f"\nOpenTrials run completed: {run_result.run_id}")
    print(f"Run directory: {run_result.run_directory}")
    for endpoint in run_result.endpoints:
        print(f"{endpoint.endpoint_type.value:<12} {endpoint.value:g} {endpoint.unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
