"""Versioned YAML configuration loading for virtual-trial protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from opentrials.core.serialization import SchemaDocument
from opentrials.trials import Trial

TRIAL_SCHEMA = "opentrials.trial"
TRIAL_SCHEMA_VERSION = "1.0.0"


class TrialConfigurationError(ValueError):
    """Raised when a trial configuration cannot be safely interpreted."""


def load_trial(path: Path) -> Trial:
    """Load and validate a versioned trial YAML document without executing it."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise TrialConfigurationError(
            f"Unable to read trial configuration {path}: {error}"
        ) from error
    except yaml.YAMLError as error:
        raise TrialConfigurationError(f"Invalid YAML in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise TrialConfigurationError("Trial configuration must be a YAML mapping.")
    try:
        document = SchemaDocument.model_validate(raw)
    except ValidationError as error:
        raise TrialConfigurationError(f"Invalid OpenTrials schema envelope: {error}") from error
    if document.schema_id != TRIAL_SCHEMA:
        raise TrialConfigurationError(
            f"Expected schema {TRIAL_SCHEMA!r}; received {document.schema_id!r}."
        )
    if document.schema_version != TRIAL_SCHEMA_VERSION:
        raise TrialConfigurationError(
            f"Unsupported {TRIAL_SCHEMA} version {document.schema_version!r}."
        )
    try:
        return Trial.model_validate(document.payload)
    except ValidationError as error:
        raise TrialConfigurationError(f"Invalid trial payload: {error}") from error
