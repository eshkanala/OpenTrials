"""The default, pre-populated model registry the SDK resolves models against.

``models.registry.ModelCapabilityRegistry`` is deliberately generic and
knows nothing about any specific profile (see its own module docstring).
Composing it with the profiles this project actually ships is a top-level
concern, not a core one -- this is that composition, and the one place a
new profile needs to be added to become reachable from the SDK/CLI.
"""

from __future__ import annotations

from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.models.registry import ModelCapabilityRegistry


def default_model_registry() -> ModelCapabilityRegistry:
    """Build a fresh registry containing every profile this project ships."""
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    return registry
