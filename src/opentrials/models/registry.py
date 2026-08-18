"""An in-process registry of declared model capability profiles.

Deliberately minimal for v0.7-A: register, look up, and list -- no
versioning policy, no persistence, no remote publishing (those are the
founding spec's later "model registry" ambition, §38/§90, not this
milestone). What matters now is that a capability profile is looked up by
model ID rather than referenced by a hard-coded import in orchestration code.
"""

from __future__ import annotations

from opentrials.models.capability import ModelCapabilityProfile


class DuplicateModelCapabilityError(ValueError):
    """Raised when a model ID is registered more than once."""


class UnknownModelCapabilityError(KeyError):
    """Raised when a model ID has no registered capability profile."""


class ModelCapabilityRegistry:
    """Holds one capability profile per model ID."""

    def __init__(self) -> None:
        self._profiles: dict[str, ModelCapabilityProfile] = {}

    def register(self, profile: ModelCapabilityProfile) -> None:
        model_id = profile.package.manifest.id
        if model_id in self._profiles:
            raise DuplicateModelCapabilityError(
                f"A capability profile is already registered for model {model_id!r}."
            )
        self._profiles[model_id] = profile

    def get(self, model_id: str) -> ModelCapabilityProfile:
        try:
            return self._profiles[model_id]
        except KeyError as error:
            raise UnknownModelCapabilityError(
                f"No capability profile is registered for model {model_id!r}."
            ) from error

    def __contains__(self, model_id: str) -> bool:
        return model_id in self._profiles

    def model_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))
