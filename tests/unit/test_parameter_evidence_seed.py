"""Contract tests for sdk.parameter_evidence_seed -- the real, cited seed set."""

from __future__ import annotations

from pathlib import Path

from opentrials.registry import FilesystemRegistryBackend, RegistryRecordKind
from opentrials.sdk.parameter_evidence_seed import seed_parameter_evidence


def test_seed_parameter_evidence_registers_every_real_candidate_once(tmp_path: Path) -> None:
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    registered = seed_parameter_evidence(backend, curation_root=str(tmp_path / "curation"))

    assert len(registered) == 8
    manifests = backend.list(RegistryRecordKind.PARAMETER_EVIDENCE)
    assert len(manifests) == 8
    for manifest in manifests:
        backend.verify(manifest.record_id)  # every record re-verifies from disk


def test_seed_parameter_evidence_is_idempotent(tmp_path: Path) -> None:
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    first = seed_parameter_evidence(backend, curation_root=str(tmp_path / "curation"))
    second = seed_parameter_evidence(backend, curation_root=str(tmp_path / "curation"))

    assert len(first) == 8
    assert second == []
    assert len(backend.list(RegistryRecordKind.PARAMETER_EVIDENCE)) == 8


def test_seed_parameter_evidence_preserves_complementary_aciclovir_half_life_values(
    tmp_path: Path,
) -> None:
    """A real, deliberate case: same parameter, two different real populations."""
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    seed_parameter_evidence(backend, curation_root=str(tmp_path / "curation"))

    normal, normal_payload = backend.get_latest(
        "aciclovir.elimination_half_life.normal-renal-function"
    )
    esrd, esrd_payload = backend.get_latest("aciclovir.elimination_half_life.esrd")

    assert normal_payload.value.value == 2.5
    assert esrd_payload.value.value == 14.0
    assert normal.record_id != esrd.record_id  # both preserved independently, never merged
