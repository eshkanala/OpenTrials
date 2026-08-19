"""Contract tests for sdk.registry_seed.seed_default_registry.

The dataset step needs real OSP (skipped whenever ``r_libs_user`` is
None, exercised here) -- proven live separately, not in this offline
suite.
"""

from __future__ import annotations

from pathlib import Path

from opentrials.registry import FilesystemRegistryBackend, RegistryRecordKind
from opentrials.sdk.registry_seed import seed_default_registry


def test_seed_default_registry_registers_both_models_and_their_compounds(
    tmp_path: Path,
) -> None:
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    registered = seed_default_registry(backend)

    assert set(registered) == {
        "osp.aciclovir.vergin-1995-iv",
        "aciclovir",
        "osp.midazolam.po-10mg-tablet",
        "midazolam",
    }
    models = backend.list(RegistryRecordKind.MODEL)
    assert {m.logical_id for m in models} == {
        "osp.aciclovir.vergin-1995-iv",
        "osp.midazolam.po-10mg-tablet",
    }
    compounds = backend.list(RegistryRecordKind.COMPOUND)
    assert {c.logical_id for c in compounds} == {"aciclovir", "midazolam"}
    # No dataset without real OSP, and no fabricated parameter-evidence record.
    assert backend.list(RegistryRecordKind.DATASET) == ()
    assert backend.list(RegistryRecordKind.PARAMETER_EVIDENCE) == ()


def test_seed_default_registry_is_idempotent(tmp_path: Path) -> None:
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    first = seed_default_registry(backend)
    second = seed_default_registry(backend)

    assert len(first) == 4
    assert second == []
    assert len(backend.list()) == 4


def test_seed_default_registry_compound_preferred_name_matches_the_profile(
    tmp_path: Path,
) -> None:
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    seed_default_registry(backend)

    _, compound = backend.get_latest("aciclovir")
    assert compound.identity.preferred_name == "Aciclovir"
