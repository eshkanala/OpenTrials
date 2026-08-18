"""Versioned YAML configuration loading for a researcher-facing OpenTrials project.

A project wraps exactly one existing ``opentrials.trial`` payload shape
(the same schema ``config.trial.load_trial`` already validates, unchanged)
with the one additional piece of information a trial protocol alone does
not carry: which registered model to execute it through. Kept as a
separate top-level schema, rather than added as a field on ``Trial``
itself, so the existing ``opentrials.trial`` schema and every test fixture
built against it stay completely untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opentrials.core.serialization import SchemaDocument
from opentrials.trials import Trial

PROJECT_SCHEMA = "opentrials.project"
PROJECT_SCHEMA_VERSION = "1.0.0"


class ProjectConfigurationError(ValueError):
    """Raised when a project configuration cannot be safely interpreted."""


class ProjectConfig(BaseModel):
    """A trial protocol paired with the registered model to execute it through."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial: Trial
    model_id: str | None = Field(
        default=None,
        description=(
            "Registered ModelCapabilityProfile ID (see models.registry). "
            "When omitted, the SDK uses the one registered profile if "
            "exactly one exists, and raises if the choice is ambiguous."
        ),
    )
    population_generation_id: str | None = Field(
        default=None,
        description=(
            "Reuse an already-generated, verified OTPGEN population instead of "
            "generating one."
        ),
    )
    population_root: Path | None = Field(
        default=None,
        description="Required alongside population_generation_id when reusing a population.",
    )


def load_project(path: Path) -> ProjectConfig:
    """Load and validate a versioned project YAML document without executing it."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProjectConfigurationError(
            f"Unable to read project configuration {path}: {error}"
        ) from error
    except yaml.YAMLError as error:
        raise ProjectConfigurationError(f"Invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ProjectConfigurationError("Project configuration must be a YAML mapping.")
    try:
        document = SchemaDocument.model_validate(raw)
    except ValidationError as error:
        raise ProjectConfigurationError(f"Invalid OpenTrials schema envelope: {error}") from error
    if document.schema_id != PROJECT_SCHEMA:
        raise ProjectConfigurationError(
            f"Expected schema {PROJECT_SCHEMA!r}; received {document.schema_id!r}."
        )
    if document.schema_version != PROJECT_SCHEMA_VERSION:
        raise ProjectConfigurationError(
            f"Unsupported {PROJECT_SCHEMA} version {document.schema_version!r}."
        )
    try:
        return ProjectConfig.model_validate(document.payload)
    except ValidationError as error:
        raise ProjectConfigurationError(f"Invalid project payload: {error}") from error
