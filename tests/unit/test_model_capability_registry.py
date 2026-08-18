"""Contract tests for the in-process model capability registry."""

from __future__ import annotations

import pytest

from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.models.registry import (
    DuplicateModelCapabilityError,
    ModelCapabilityRegistry,
    UnknownModelCapabilityError,
)


def test_register_and_get_round_trips() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)

    assert "osp.aciclovir.vergin-1995-iv" in registry
    assert registry.get("osp.aciclovir.vergin-1995-iv") is ACICLOVIR_IV_CAPABILITY_PROFILE
    assert registry.model_ids() == ("osp.aciclovir.vergin-1995-iv",)


def test_register_rejects_a_duplicate_model_id() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)
    with pytest.raises(DuplicateModelCapabilityError):
        registry.register(ACICLOVIR_IV_CAPABILITY_PROFILE)


def test_get_rejects_an_unknown_model_id() -> None:
    registry = ModelCapabilityRegistry()
    with pytest.raises(UnknownModelCapabilityError):
        registry.get("unregistered.model")
    assert "unregistered.model" not in registry
