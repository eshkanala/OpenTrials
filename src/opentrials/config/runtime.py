"""Machine-local OSP runtime configuration: where R/dotnet live on this machine.

Kept separate from ``config.project``/``config.trial`` on purpose: a trial
protocol describes *science*, and should read identically whether it runs on
a researcher's laptop, a lab's shared workstation, or an HPC cluster node.
Where the local ``Rscript``/``dotnet`` install happens to live is a property
of the machine, not the protocol, so it is resolved independently here
through the usual sequence of increasingly durable overrides: an explicit
CLI flag beats an environment variable for one invocation, which beats a
config file that persists across invocations, which beats OpenTrials' own
compiled-in default (verified only against one specific macOS layout -- see
``adapters.osp.engine.DEFAULT_FRAMEWORK_RSCRIPT``/``DEFAULT_DOTNET_ROOT``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT

RSCRIPT_PATH_ENV_VAR = "OPENTRIALS_RSCRIPT_PATH"
DOTNET_ROOT_ENV_VAR = "OPENTRIALS_DOTNET_ROOT"
R_LIBS_USER_ENV_VAR = "R_LIBS_USER"
CONFIG_PATH_ENV_VAR = "OPENTRIALS_CONFIG"
LOCAL_CONFIG_FILENAME = ".opentrials.yaml"


@dataclass(frozen=True)
class OspRuntimeConfig:
    """The resolved local machine settings needed to run the OSP R worker.

    ``source`` records where each field actually came from (``"cli"``,
    ``"env"``, ``"config_file"``, ``"default"``, or ``"unset"``) so a caller
    can print an honest "why did it pick this path" explanation rather than
    leaving a researcher to guess.
    """

    rscript_path: Path
    dotnet_root: str
    r_libs_user: str | None
    source: dict[str, str] = field(default_factory=dict)


def _default_config_search_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "opentrials" / "config.yaml"


def _load_config_file(environ: Mapping[str, str]) -> dict[str, Any]:
    explicit = environ.get(CONFIG_PATH_ENV_VAR)
    candidates = (
        [Path(explicit)]
        if explicit
        else [Path.cwd() / LOCAL_CONFIG_FILENAME, _default_config_search_path()]
    )
    for candidate in candidates:
        if candidate.is_file():
            raw: Any = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    return {}


def resolve_osp_runtime(
    *,
    rscript_path: Path | None = None,
    dotnet_root: str | None = None,
    r_libs_user: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> OspRuntimeConfig:
    """Resolve the OSP runtime location: CLI arg > env var > config file > built-in default.

    Every parameter is the already-parsed CLI value (``None`` if the
    researcher didn't pass one) -- this function does not read ``sys.argv``
    itself, so it stays trivially testable and reusable from both the CLI
    and any direct SDK caller that wants the same resolution behavior.
    """
    environ = environ if environ is not None else os.environ
    config_file = _load_config_file(environ)
    source: dict[str, str] = {}

    if rscript_path is not None:
        resolved_rscript = rscript_path
        source["rscript_path"] = "cli"
    elif environ.get(RSCRIPT_PATH_ENV_VAR):
        resolved_rscript = Path(environ[RSCRIPT_PATH_ENV_VAR])
        source["rscript_path"] = "env"
    elif config_file.get("rscript_path"):
        resolved_rscript = Path(str(config_file["rscript_path"]))
        source["rscript_path"] = "config_file"
    else:
        resolved_rscript = DEFAULT_FRAMEWORK_RSCRIPT
        source["rscript_path"] = "default"

    if dotnet_root is not None:
        resolved_dotnet = dotnet_root
        source["dotnet_root"] = "cli"
    elif environ.get(DOTNET_ROOT_ENV_VAR):
        resolved_dotnet = environ[DOTNET_ROOT_ENV_VAR]
        source["dotnet_root"] = "env"
    elif config_file.get("dotnet_root"):
        resolved_dotnet = str(config_file["dotnet_root"])
        source["dotnet_root"] = "config_file"
    else:
        resolved_dotnet = DEFAULT_DOTNET_ROOT
        source["dotnet_root"] = "default"

    resolved_r_libs_user: str | None
    if r_libs_user is not None:
        resolved_r_libs_user = r_libs_user
        source["r_libs_user"] = "cli"
    elif environ.get(R_LIBS_USER_ENV_VAR):
        resolved_r_libs_user = environ[R_LIBS_USER_ENV_VAR]
        source["r_libs_user"] = "env"
    elif config_file.get("r_libs_user"):
        resolved_r_libs_user = str(config_file["r_libs_user"])
        source["r_libs_user"] = "config_file"
    else:
        resolved_r_libs_user = None
        source["r_libs_user"] = "unset"

    return OspRuntimeConfig(
        rscript_path=resolved_rscript,
        dotnet_root=resolved_dotnet,
        r_libs_user=resolved_r_libs_user,
        source=source,
    )
