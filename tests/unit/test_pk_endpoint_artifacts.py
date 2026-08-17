from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.storage.endpoints import (
    PK_ENDPOINT_COLUMNS,
    PkEndpointArtifactStore,
    semantic_pk_endpoint_hash,
)

SOURCE_HASH = "sha256:" + "a" * 64


def endpoint(*, source_result_hash: str = SOURCE_HASH, value: float = 1.25) -> PkEndpointResult:
    return PkEndpointResult(
        subject_id="1",
        endpoint_type=PkEndpointType.CMAX,
        value=value,
        unit="µmol/l",
        time_basis="actual_sample_times",
        integration_method="not_applicable",
        source_result_hash=source_result_hash,
        analyte="aciclovir",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
    )


def test_pk_endpoint_artifact_is_immutable_and_verifies(tmp_path: Path) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    directory = store.create_endpoint_artifact("OTPK-001")
    manifest = store.write_endpoints(
        "OTPK-001",
        endpoints=(endpoint(),),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-001",
        run_id="OTR-aciclovir-001",
        source_engine_id="osp",
        source_model_id="org.example.aciclovir-pbpk",
    )

    reloaded = store.verify_endpoints("OTPK-001")
    table = pq.read_table(directory / "endpoints.parquet")

    assert reloaded == manifest
    assert table.column_names == list(PK_ENDPOINT_COLUMNS)
    assert table.num_rows == 1
    assert manifest.source_result_semantic_sha256 == SOURCE_HASH
    assert '"schema":"opentrials.pk-endpoint-artifact"' in (directory / "manifest.json").read_text()
    with pytest.raises(FileExistsError, match="already exist"):
        store.write_endpoints(
            "OTPK-001",
            endpoints=(endpoint(),),
            source_result_semantic_sha256=SOURCE_HASH,
            source_result_id="OTRES-001",
            run_id="OTR-aciclovir-001",
        )


def test_pk_endpoint_artifact_rejects_mismatched_source_hash(tmp_path: Path) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact("OTPK-001")

    with pytest.raises(ValueError, match="source result hash"):
        store.write_endpoints(
            "OTPK-001",
            endpoints=(endpoint(source_result_hash="sha256:" + "b" * 64),),
            source_result_semantic_sha256=SOURCE_HASH,
            source_result_id="OTRES-001",
            run_id="OTR-aciclovir-001",
        )


def test_semantic_pk_endpoint_hash_normalizes_equivalent_numeric_cells() -> None:
    integer_rows = ({"subject_id": "1", "value": 1, "endpoint_type": "CMAX"},)
    float_rows = ({"subject_id": "1", "value": 1.0, "endpoint_type": "CMAX"},)

    assert semantic_pk_endpoint_hash(
        ("subject_id", "value", "endpoint_type"), integer_rows
    ) == semantic_pk_endpoint_hash(("subject_id", "value", "endpoint_type"), float_rows)
