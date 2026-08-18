"""Contract tests for the CSV-file transport helpers (v0.6-C)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.csv as pa_csv
import pytest

from opentrials.adapters.osp.csv_transport import read_result_csv_rows, write_population_csv


def test_write_population_csv_round_trips_via_pyarrow(tmp_path: Path) -> None:
    columns = ("IndividualId", "Gender", "Organism|Age")
    rows = (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 40.0},
        {"IndividualId": 1, "Gender": "MALE", "Organism|Age": 55.5},
    )
    path = tmp_path / "population.csv"
    write_population_csv(columns, rows, path)

    table = pa_csv.read_csv(path)
    assert table.column_names == list(columns)
    assert table.to_pylist() == list(rows)


def test_read_result_csv_rows_unpivots_wide_format_to_long_rows(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    path.write_text(
        '"IndividualId","Time [min]","Organism|Path A [umol/l]","Organism|Path B [umol/l]"\n'
        "0,0,1.5,10.0\n"
        "0,10,2.5,20.0\n"
        "1,0,3.5,30.0\n",
        encoding="utf-8",
    )

    rows = read_result_csv_rows(path)

    assert len(rows) == 6  # 3 (IndividualId, Time) pairs x 2 value columns
    by_key = {
        (row["IndividualId"], row["Time"], row["paths"]): (row["simulationValues"], row["unit"])
        for row in rows
    }
    assert by_key[(0, 0, "Organism|Path A")] == (1.5, "umol/l")
    assert by_key[(0, 10, "Organism|Path B")] == (20.0, "umol/l")
    assert by_key[(1, 0, "Organism|Path A")] == (3.5, "umol/l")


def test_read_result_csv_rows_handles_a_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "results_bom.csv"
    content = '"IndividualId","Time [min]","Organism|Path A [umol/l]"\n0,0,1.0\n'
    path.write_bytes(content.encode("utf-8-sig"))

    rows = read_result_csv_rows(path)
    assert len(rows) == 1
    assert rows[0]["paths"] == "Organism|Path A"
    assert rows[0]["unit"] == "umol/l"


def test_read_result_csv_rows_rejects_a_header_without_a_time_column(tmp_path: Path) -> None:
    path = tmp_path / "no_time.csv"
    path.write_text('"IndividualId","Organism|Path A [umol/l]"\n0,1.0\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Time column"):
        read_result_csv_rows(path)
