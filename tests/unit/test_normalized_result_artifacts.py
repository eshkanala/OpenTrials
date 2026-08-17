from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.storage.results import (
    CONCENTRATION_TIME_COLUMNS,
    ConversionPolicy,
    ResultArtifactStore,
    ResultSelectionMapping,
    normalize_osp_concentration_time_rows,
    semantic_concentration_time_hash,
)

SOURCE_PATH = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"


def selection() -> ResultSelectionMapping:
    return ResultSelectionMapping(
        source_path=SOURCE_PATH,
        analyte="aciclovir",
        matrix="plasma",
        fraction="total",
        measurement="concentration",
        time_unit="min",
    )


def raw_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "IndividualId": 1,
            "Time": 0,
            "simulationValues": 1.25,
            "unit": "µmol/l",
            "paths": SOURCE_PATH,
        },
        {
            "IndividualId": 1,
            "Time": 60,
            "simulationValues": 0.75,
            "unit": "µmol/l",
            "paths": SOURCE_PATH,
        },
    )


def test_normalization_selects_one_path_and_preserves_source_value_and_unit() -> None:
    normalized = normalize_osp_concentration_time_rows(raw_rows(), selection())

    assert normalized[0] == {
        "subject_id": "1",
        "time": 0.0,
        "time_unit": "min",
        "analyte": "aciclovir",
        "matrix": "plasma",
        "fraction": "total",
        "measurement": "concentration",
        "value": 1.25,
        "unit": "µmol/l",
        "source_engine": "osp",
        "source_path": SOURCE_PATH,
        "source_value": 1.25,
        "source_unit": "µmol/l",
        "conversion_policy": "PRESERVE_SOURCE",
    }
    assert normalized[1]["value"] == normalized[1]["source_value"]
    assert normalized[1]["unit"] == normalized[1]["source_unit"]


def test_normalization_rejects_rows_from_a_different_source_path() -> None:
    mismatched = ({**raw_rows()[0], "paths": "Organism|Liver|Aciclovir|Concentration"},)

    with pytest.raises(ValueError, match="does not match"):
        normalize_osp_concentration_time_rows(mismatched, selection())


def test_result_artifact_is_immutable_and_verifies_file_and_semantic_hash(tmp_path: Path) -> None:
    store = ResultArtifactStore(tmp_path / "results")
    directory = store.create_result("OTRES-001")
    manifest = store.write_concentration_time(
        "OTRES-001",
        source_raw_result={"raw_result_rows": raw_rows(), "engine": "osp"},
        raw_rows=raw_rows(),
        engine_id="osp",
        model_id="org.example.aciclovir-pbpk",
        run_id="OTR-aciclovir-001",
        selection=selection(),
    )

    reloaded = store.verify_result("OTRES-001")
    table = pq.read_table(directory / "concentration_time.parquet")

    assert reloaded == manifest
    assert table.column_names == list(CONCENTRATION_TIME_COLUMNS)
    assert table.num_rows == 2
    assert manifest.conversion_policy is ConversionPolicy.PRESERVE_SOURCE
    assert '"schema":"opentrials.result-artifact"' in (directory / "manifest.json").read_text()
    with pytest.raises(FileExistsError, match="already exist"):
        store.write_concentration_time(
            "OTRES-001",
            source_raw_result={"raw_result_rows": raw_rows()},
            raw_rows=raw_rows(),
            engine_id="osp",
            model_id="org.example.aciclovir-pbpk",
            run_id="OTR-aciclovir-001",
            selection=selection(),
        )


def test_semantic_result_hash_normalizes_equivalent_numeric_cells() -> None:
    integer_rows = ({"subject_id": "1", "value": 1, "time": 60},)
    float_rows = ({"subject_id": "1", "value": 1.0, "time": 60.0},)

    assert semantic_concentration_time_hash(
        ("subject_id", "value", "time"), integer_rows
    ) == semantic_concentration_time_hash(("subject_id", "value", "time"), float_rows)
