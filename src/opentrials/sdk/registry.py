"""The default, pre-populated model registry the SDK resolves models against.

``models.registry.ModelCapabilityRegistry`` is deliberately generic and
knows nothing about any specific profile (see its own module docstring).
Composing it with the profiles this project actually ships is a top-level
concern, not a core one -- this is that composition, and the one place a
new profile needs to be added to become reachable from the SDK/CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.models.profiles.midazolam_po import MIDAZOLAM_PO_CAPABILITY_PROFILE
from opentrials.models.registry import ModelCapabilityRegistry
from opentrials.registry import FilesystemRegistryBackend, RegistryBackend

REGISTRY_ROOT_ENV_VAR = "OPENTRIALS_REGISTRY_ROOT"


def _default_registry_root() -> Path:
    """A Registry is shared across every project a researcher opens, unlike
    ``runs/``/``evidence/`` which are naturally per-project -- so, unlike
    those, its default location must not depend on whatever directory
    ``opentrials``/Studio happens to be launched from. Resolved the same
    way ``config.runtime`` already resolves a machine-local, durable
    default: an explicit env var first, then the XDG data-home convention
    (``$XDG_DATA_HOME/opentrials/registry``, falling back to
    ``~/.local/share/opentrials/registry``).
    """
    explicit = os.environ.get(REGISTRY_ROOT_ENV_VAR)
    if explicit:
        return Path(explicit)
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "opentrials" / "registry"


def default_model_registry() -> ModelCapabilityRegistry:
    """Build a fresh registry containing every profile this project ships."""
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    registry.register(MIDAZOLAM_PO_CAPABILITY_PROFILE)
    return registry


def default_registry_backend(root: str | Path | None = None) -> RegistryBackend:
    """Return the default, local-filesystem OpenTrials Registry backend.

    ``root=None`` (the common case) resolves the shared, stable default
    location via ``_default_registry_root()``; pass an explicit root to
    use a different one (e.g. an isolated registry for testing). The one
    place a hosted/SQLite backend would be swapped in later -- every
    caller (Studio's bridge, CLI, scripts) should go through this
    function rather than constructing ``FilesystemRegistryBackend``
    directly, so that swap requires changing one function, not every
    call site.
    """
    resolved_root = _default_registry_root() if root is None else Path(root)
    return FilesystemRegistryBackend(resolved_root)
