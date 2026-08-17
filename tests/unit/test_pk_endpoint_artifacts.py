from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.storage.endpoints import (
    PK_ENDPOINT_COLUMNS,
    PkEndpointArtifactStore,
    PkEndpointSubjectLineage,
    semantic_pk_endpoint_hash,
)

SOURCE_HASH = "sha256:" + "a" * 64
POPULATION_HASH = "sha256:" + "c" * 64


def endpoint(
    *, subject_id: str = "1", source_result_hash: str = SOURCE_HASH, value: float = 1.25
) -> PkEndpointResult:
    return PkEndpointResult(
        subject_id=subject_id,
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


def lineage(row_index: int, *, generation_id: str = "OTPGEN-test") -> PkEndpointSubjectLineage:
    return PkEndpointSubjectLineage(
        source_generation_id=generation_id,
        source_population_semantic_sha256=POPULATION_HASH,
        source_population_row_index=row_index,
        source_population_row_sha256="sha256:" + f"{row_index:064d}",
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


def test_endpoint_artifact_without_lineage_declares_no_population_lineage(tmp_path: Path) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact("OTPK-nolineage")
    manifest = store.write_endpoints(
        "OTPK-nolineage",
        endpoints=(endpoint(),),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-001",
        run_id="OTR-aciclovir-001",
    )
    assert manifest.population_lineage_present is False
    assert manifest.source_generation_id is None
    assert manifest.source_population_semantic_sha256 is None
    reloaded = store.verify_endpoints("OTPK-nolineage")
    assert reloaded == manifest


def test_endpoint_artifact_with_lineage_binds_every_subject_to_its_population_row(
    tmp_path: Path,
) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact("OTPK-lineage")
    endpoints = (endpoint(subject_id="0", value=1.0), endpoint(subject_id="1", value=2.0))
    manifest = store.write_endpoints(
        "OTPK-lineage",
        endpoints=endpoints,
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-001",
        run_id="OTR-aciclovir-001",
        subject_lineage={"0": lineage(0), "1": lineage(1)},
    )
    assert manifest.population_lineage_present is True
    assert manifest.source_generation_id == "OTPGEN-test"
    assert manifest.source_population_semantic_sha256 == POPULATION_HASH
    assert manifest.schema_version.split(".")[0] == "2"

    reloaded = store.verify_endpoints("OTPK-lineage")
    assert reloaded == manifest
    table = pq.read_table(tmp_path / "endpoints" / "OTPK-lineage" / "endpoints.parquet")
    rows = {row["subject_id"]: row for row in table.to_pylist()}
    assert rows["0"]["source_population_row_index"] == 0
    assert rows["1"]["source_population_row_index"] == 1
    assert rows["0"]["source_population_row_sha256"] != rows["1"]["source_population_row_sha256"]


def test_write_endpoints_rejects_incomplete_subject_lineage(tmp_path: Path) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact("OTPK-partial")
    endpoints = (endpoint(subject_id="0"), endpoint(subject_id="1"))
    with pytest.raises(ValueError, match="exactly the subjects"):
        store.write_endpoints(
            "OTPK-partial",
            endpoints=endpoints,
            source_result_semantic_sha256=SOURCE_HASH,
            source_result_id="OTRES-001",
            run_id="OTR-aciclovir-001",
            subject_lineage={"0": lineage(0)},
        )


def test_write_endpoints_rejects_lineage_spanning_multiple_populations(tmp_path: Path) -> None:
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact("OTPK-mixed")
    endpoints = (endpoint(subject_id="0"), endpoint(subject_id="1"))
    with pytest.raises(ValueError, match="same OTPGEN generation"):
        store.write_endpoints(
            "OTPK-mixed",
            endpoints=endpoints,
            source_result_semantic_sha256=SOURCE_HASH,
            source_result_id="OTRES-001",
            run_id="OTR-aciclovir-001",
            subject_lineage={
                "0": lineage(0, generation_id="OTPGEN-a"),
                "1": lineage(1, generation_id="OTPGEN-b"),
            },
        )


def test_semantic_pk_endpoint_hash_normalizes_equivalent_numeric_cells() -> None:
    integer_rows = ({"subject_id": "1", "value": 1, "endpoint_type": "CMAX"},)
    float_rows = ({"subject_id": "1", "value": 1.0, "endpoint_type": "CMAX"},)

    assert semantic_pk_endpoint_hash(
        ("subject_id", "value", "endpoint_type"), integer_rows
    ) == semantic_pk_endpoint_hash(("subject_id", "value", "endpoint_type"), float_rows)
