import pytest
from pydantic import ValidationError

from opentrials.models import Applicability, ModelManifest, ModelPackage, ModelType

HASH = "sha256:" + "a" * 64


def make_manifest(**changes: object) -> ModelManifest:
    values: dict[str, object] = {
        "id": "renal.gfr.age-v1",
        "version": "1.2.0",
        "model_type": ModelType.PHYSIOLOGY,
        "engine": "python",
        "inputs": ("age", "disease.ckd_stage"),
        "outputs": ("renal.gfr",),
        "units": {"renal.gfr": "mL/min/m^2"},
        "applicability": Applicability(species=("human",), populations=("healthy_adult",)),
        "license": "Apache-2.0",
    }
    values.update(changes)
    return ModelManifest(**values)


def test_model_manifest_is_versioned_and_deterministic() -> None:
    manifest = make_manifest()

    assert manifest.schema_version == "1.0.0"
    assert '"id":"renal.gfr.age-v1"' in manifest.canonical_json()
    assert manifest.canonical_json() == make_manifest().canonical_json()


def test_model_manifest_requires_units_for_every_output() -> None:
    with pytest.raises(ValidationError, match="outputs require units"):
        make_manifest(units={})


def test_model_manifest_rejects_invalid_semantic_version() -> None:
    with pytest.raises(ValidationError):
        make_manifest(version="version-one")


def test_model_package_pins_all_executable_content() -> None:
    package = ModelPackage(
        manifest=make_manifest(),
        artifact_uri="https://models.example.org/renal.gfr.age-v1.tar.gz",
        artifact_hash=HASH,
        parameter_set_id="renal-gfr-parameters-v1",
        parameter_hash=HASH,
        package_hash=HASH,
    )

    assert package.manifest.id == "renal.gfr.age-v1"
    assert package.package_hash == HASH


def test_model_package_rejects_non_sha256_hashes() -> None:
    with pytest.raises(ValidationError):
        ModelPackage(
            manifest=make_manifest(),
            artifact_uri="file:///model.tar.gz",
            artifact_hash="not-a-hash",
            parameter_set_id="parameters-v1",
            parameter_hash=HASH,
            package_hash=HASH,
        )
