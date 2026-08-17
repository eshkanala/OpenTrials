"""Minimal Phase 0 command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from opentrials.config import TrialConfigurationError, load_trial


def main() -> int:
    parser = argparse.ArgumentParser(prog="opentrials")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate", help="Validate a versioned trial YAML configuration."
    )
    validate.add_argument("trial", type=Path)
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
