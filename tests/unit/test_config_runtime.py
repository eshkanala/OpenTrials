"""Contract tests for OSP runtime resolution: CLI arg > env var > config file > default."""

from __future__ import annotations

from pathlib import Path

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT
from opentrials.config.runtime import resolve_osp_runtime


def test_resolves_to_built_in_defaults_when_nothing_else_is_set() -> None:
    result = resolve_osp_runtime(environ={})

    assert result.rscript_path == DEFAULT_FRAMEWORK_RSCRIPT
    assert result.dotnet_root == DEFAULT_DOTNET_ROOT
    assert result.r_libs_user is None
    assert result.source == {
        "rscript_path": "default",
        "dotnet_root": "default",
        "r_libs_user": "unset",
    }


def test_environment_variables_override_the_default() -> None:
    result = resolve_osp_runtime(
        environ={
            "OPENTRIALS_RSCRIPT_PATH": "/opt/R/bin/Rscript",
            "OPENTRIALS_DOTNET_ROOT": "/opt/dotnet",
            "R_LIBS_USER": "/home/researcher/R/library",
        }
    )

    assert result.rscript_path == Path("/opt/R/bin/Rscript")
    assert result.dotnet_root == "/opt/dotnet"
    assert result.r_libs_user == "/home/researcher/R/library"
    assert result.source == {
        "rscript_path": "env",
        "dotnet_root": "env",
        "r_libs_user": "env",
    }


def test_explicit_arguments_override_environment_variables() -> None:
    result = resolve_osp_runtime(
        rscript_path=Path("/explicit/Rscript"),
        dotnet_root="/explicit/dotnet",
        r_libs_user="/explicit/R/library",
        environ={
            "OPENTRIALS_RSCRIPT_PATH": "/opt/R/bin/Rscript",
            "OPENTRIALS_DOTNET_ROOT": "/opt/dotnet",
            "R_LIBS_USER": "/home/researcher/R/library",
        },
    )

    assert result.rscript_path == Path("/explicit/Rscript")
    assert result.dotnet_root == "/explicit/dotnet"
    assert result.r_libs_user == "/explicit/R/library"
    assert result.source == {
        "rscript_path": "cli",
        "dotnet_root": "cli",
        "r_libs_user": "cli",
    }


def test_config_file_fills_in_between_env_and_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "rscript_path: /lab/shared/R/bin/Rscript\n"
        "dotnet_root: /lab/shared/dotnet\n"
        "r_libs_user: /lab/shared/R/library\n",
        encoding="utf-8",
    )

    result = resolve_osp_runtime(environ={"OPENTRIALS_CONFIG": str(config_path)})

    assert result.rscript_path == Path("/lab/shared/R/bin/Rscript")
    assert result.dotnet_root == "/lab/shared/dotnet"
    assert result.r_libs_user == "/lab/shared/R/library"
    assert result.source == {
        "rscript_path": "config_file",
        "dotnet_root": "config_file",
        "r_libs_user": "config_file",
    }


def test_env_var_beats_config_file() -> None:
    # No config file exists at the default search locations in this environ,
    # so this also exercises the "no config file found" path alongside an
    # explicit OPENTRIALS_CONFIG pointing nowhere real.
    result = resolve_osp_runtime(
        environ={
            "OPENTRIALS_CONFIG": "/does/not/exist.yaml",
            "OPENTRIALS_RSCRIPT_PATH": "/opt/R/bin/Rscript",
        }
    )

    assert result.rscript_path == Path("/opt/R/bin/Rscript")
    assert result.source["rscript_path"] == "env"
