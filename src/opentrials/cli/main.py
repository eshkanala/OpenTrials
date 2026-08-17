"""Minimal Phase 0 command-line entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from opentrials.config import TrialConfigurationError, load_trial
from opentrials.orchestration import run_aciclovir_iv_engineering


def main() -> int:
    parser = argparse.ArgumentParser(prog="opentrials")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate a versioned trial YAML configuration."
    )
    validate.add_argument("trial", type=Path)
    run = commands.add_parser(
        "run", help="Execute the supported, verified Aciclovir IV engineering workflow."
    )
    run.add_argument("trial", type=Path)
    run.add_argument("--output-root", type=Path, default=Path("runs"))
    run.add_argument("--r-libs-user", default=os.environ.get("R_LIBS_USER"))
    arguments = parser.parse_args()

    if arguments.command == "validate":
        try:
            trial = load_trial(arguments.trial)
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
    if arguments.command == "run":
        if arguments.r_libs_user is None:
            print(
                "Run unavailable: set --r-libs-user or R_LIBS_USER for the local ospsuite library."
            )
            return 2
        try:
            trial = load_trial(arguments.trial)
            run_result = run_aciclovir_iv_engineering(
                trial,
                output_root=arguments.output_root,
                r_libs_user=arguments.r_libs_user,
                progress=lambda stage: print(f"[✓] {stage.replace('_', ' ')}"),
            )
        except (TrialConfigurationError, OSError, ValueError, RuntimeError) as error:
            print(f"Run failed: {error}")
            return 1
        print(f"\nOpenTrials run completed: {run_result.run_id}")
        print(f"Run directory: {run_result.run_directory}")
        for endpoint in run_result.endpoints:
            print(f"{endpoint.endpoint_type.value:<12} {endpoint.value:g} {endpoint.unit}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
