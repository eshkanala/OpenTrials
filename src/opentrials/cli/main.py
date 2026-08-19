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
import sys
import time
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

import yaml

from opentrials.cli import model_commands, registry_commands
from opentrials.cli.progress import ProgressRenderer
from opentrials.config import TrialConfigurationError, load_trial
from opentrials.config.project import ProjectConfigurationError
from opentrials.config.runtime import OspRuntimeConfig, resolve_osp_runtime
from opentrials.orchestration import run_aciclovir_iv_engineering
from opentrials.reporting import (
    build_population_report,
    build_trial_report,
    render_html,
    render_markdown,
)
from opentrials.sdk.project import Project
from opentrials.sdk.project_scaffold import generate_project_scaffold

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
    parser.add_argument(
        "--version", action="version", version=f"opentrials {installed_version('opentrials')}"
    )
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
    run.add_argument(
        "--r-libs-user",
        default=None,
        help="Local ospsuite R library path. Falls back to R_LIBS_USER, then a config file.",
    )
    run.add_argument(
        "--rscript-path",
        type=Path,
        default=None,
        help=(
            "Local Rscript executable. Falls back to OPENTRIALS_RSCRIPT_PATH, then a config "
            "file, then OpenTrials' compiled-in macOS default."
        ),
    )
    run.add_argument(
        "--dotnet-root",
        default=None,
        help=(
            "Local .NET runtime root. Falls back to OPENTRIALS_DOTNET_ROOT, then a config "
            "file, then OpenTrials' compiled-in macOS default."
        ),
    )
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

    init = commands.add_parser(
        "init", help="Generate a working, commented project.yaml to get started."
    )
    init.add_argument("--output", type=Path, default=Path("project.yaml"))

    model_parser = commands.add_parser(
        "model", help="Discover and scaffold a model from a PKML file."
    )
    model_commands_parser = model_parser.add_subparsers(dest="model_command", required=True)
    model_inspect = model_commands_parser.add_parser(
        "inspect", help="Discover a PKML file's structure (read-only, no capability claims)."
    )
    model_inspect.add_argument("pkml_path", type=Path)
    model_inspect.add_argument("--r-libs-user", default=None)
    model_inspect.add_argument("--rscript-path", type=Path, default=None)
    model_inspect.add_argument("--dotnet-root", default=None)
    model_init_parser = model_commands_parser.add_parser(
        "init", help="Generate a reviewable ModelCapabilityProfile scaffold from discovery."
    )
    model_init_parser.add_argument("pkml_path", type=Path)
    model_init_parser.add_argument("--r-libs-user", default=None)
    model_init_parser.add_argument("--rscript-path", type=Path, default=None)
    model_init_parser.add_argument("--dotnet-root", default=None)
    model_init_parser.add_argument("--model-id", required=True)
    model_init_parser.add_argument("--output", type=Path, default=None)

    studio = commands.add_parser(
        "studio", help="Launch OpenTrials Studio, a local browser-based GUI."
    )
    studio.add_argument("config", type=Path, nargs="?", default=None)
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8765)
    studio.add_argument(
        "--no-browser", action="store_true", help="Print the URL but do not open a browser."
    )

    models_parser = commands.add_parser(
        "models", help="Inspect the local registered-model registry."
    )
    models_commands_parser = models_parser.add_subparsers(dest="models_command", required=True)
    models_commands_parser.add_parser("list", help="List every registered model.")
    models_show_parser = models_commands_parser.add_parser(
        "show", help="Show one registered model's full declared capability."
    )
    models_show_parser.add_argument("model_id")

    registry_parser = commands.add_parser(
        "registry", help="Manage the local OpenTrials Registry (models/compounds/evidence)."
    )
    registry_commands_parser = registry_parser.add_subparsers(
        dest="registry_command", required=True
    )
    registry_seed_parser = registry_commands_parser.add_parser(
        "seed", help="Register the real models/compounds/evidence this project ships."
    )
    registry_seed_parser.add_argument(
        "--root", type=Path, default=None,
        help="Defaults to $OPENTRIALS_REGISTRY_ROOT, then ~/.local/share/opentrials/registry.",
    )
    registry_seed_parser.add_argument("--r-libs-user", default=None)
    registry_seed_parser.add_argument("--rscript-path", type=Path, default=None)
    registry_seed_parser.add_argument("--dotnet-root", default=None)
    registry_list_parser = registry_commands_parser.add_parser(
        "list", help="List every registered record, optionally filtered by kind."
    )
    registry_list_parser.add_argument("--root", type=Path, default=None)
    registry_list_parser.add_argument(
        "--kind",
        default=None,
        choices=["model", "compound", "parameter_evidence", "dataset", "experiment"],
    )
    registry_show_parser = registry_commands_parser.add_parser(
        "show", help="Show one registered record's full, re-verified payload."
    )
    registry_show_parser.add_argument("--root", type=Path, default=None)
    registry_show_parser.add_argument("logical_id")

    arguments = parser.parse_args()

    try:
        return _dispatch(arguments)
    except Exception as error:  # last-resort boundary: turn a bug into a message, not a traceback
        print(
            f"opentrials hit an unexpected internal error: {type(error).__name__}: {error}\n"
            "This is likely a bug in OpenTrials itself, not your configuration -- please open "
            "an issue against this project with the command you ran and this message."
        )
        return 3


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "report":
        return _report(arguments)
    if arguments.command == "init":
        return _init(arguments)
    if arguments.command == "studio":
        return _studio(arguments)
    if arguments.command == "model":
        if arguments.model_command == "inspect":
            return model_commands.model_inspect(arguments)
        return model_commands.model_init(arguments)
    if arguments.command == "models":
        if arguments.models_command == "list":
            return model_commands.models_list(arguments)
        return model_commands.models_show(arguments)
    if arguments.command == "registry":
        if arguments.registry_command == "seed":
            return registry_commands.registry_seed(arguments)
        if arguments.registry_command == "list":
            return registry_commands.registry_list(arguments)
        return registry_commands.registry_show(arguments)

    schema = _sniff_schema(arguments.config)
    if arguments.command == "validate":
        return _validate(arguments.config, schema)
    if arguments.command == "run":
        return _run(arguments.config, schema, arguments)
    return 2


def _init(arguments: argparse.Namespace) -> int:
    output_path: Path = arguments.output
    if output_path.exists():
        print(f"Refusing to overwrite an existing file: {output_path}")
        return 1
    output_path.write_text(generate_project_scaffold(filename=output_path.name), encoding="utf-8")
    print(f"Project created: {output_path}\n")
    print("Next:")
    print(f"  opentrials validate {output_path}")
    print(f"  opentrials run {output_path} --r-libs-user <path to your ospsuite R library>")
    return 0


def _studio(arguments: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "Studio unavailable: the 'studio' extra is not installed.\n"
            "Install it with: pip install 'opentrials[studio]'"
        )
        return 2

    from opentrials.studio.server import app

    url = f"http://{arguments.host}:{arguments.port}/"
    if arguments.config is not None:
        url += f"?path={arguments.config}"

    if not arguments.no_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"OpenTrials Studio: {url}")
    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="warning")
    return 0


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
    runtime = resolve_osp_runtime(
        rscript_path=arguments.rscript_path,
        dotnet_root=arguments.dotnet_root,
        r_libs_user=arguments.r_libs_user,
    )
    if runtime.r_libs_user is None:
        print(
            "Run unavailable: set --r-libs-user, R_LIBS_USER, or r_libs_user in a config file "
            "for the local ospsuite library."
        )
        return 2

    if schema == PROJECT_SCHEMA:
        return _run_project(path, arguments, runtime)
    return _run_legacy_trial(path, arguments, runtime)


def _run_project(path: Path, arguments: argparse.Namespace, runtime: OspRuntimeConfig) -> int:
    assert runtime.r_libs_user is not None  # _run already rejected the unset case
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
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
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


def _run_legacy_trial(path: Path, arguments: argparse.Namespace, runtime: OspRuntimeConfig) -> int:
    assert runtime.r_libs_user is not None  # _run already rejected the unset case
    try:
        trial = load_trial(path)
        started = time.monotonic()
        run_result = run_aciclovir_iv_engineering(
            trial,
            output_root=arguments.output_root,
            r_libs_user=runtime.r_libs_user,
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
