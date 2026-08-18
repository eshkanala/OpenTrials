"""CSV-file transport for population execution, as an alternative to embedded JSON.

A v0.6-C capability probe measured the existing JSON path's dominant cost at
N=100: building an R row-list plus ``jsonlite::toJSON`` over a 98,200-row
result took ~23s and produced a 24.75MB payload, versus 0.16s and 1.35MB for
OSP's own ``exportResultsToCSV``. This module is the Python-side half of the
replacement: it writes a population table to the exact CSV format
``loadPopulation()`` accepts (verified byte-for-byte equivalent to
``populationFromDataFrame()`` reconstruction), and reads OSP's wide-format
result CSV back into the same long-row shape
(``IndividualId``/``Time``/``simulationValues``/``unit``/``paths``) the
existing JSON-transport pipeline already expects -- so every downstream
consumer (lineage resolution, normalization, PK calculation, artifact
persistence) is completely unaware which transport produced the rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.csv as pa_csv  # type: ignore[import-untyped]

_NON_VALUE_COLUMNS = {"IndividualId"}


def write_population_csv(
    columns: Sequence[str], rows: Sequence[Mapping[str, object]], path: Path
) -> None:
    """Write a population table in the exact format OSP's ``loadPopulation()`` accepts.

    Verified (v0.6-C capability probe) to round-trip through
    ``loadPopulation()`` into a population identical, column for column, to
    ``populationFromDataFrame()`` reconstruction of the same table.
    """
    table = pa.table({column: [row[column] for row in rows] for column in columns})
    pa_csv.write_csv(table, path)


def read_result_csv_rows(path: Path) -> tuple[dict[str, object], ...]:
    """Read OSP's wide-format result CSV into the existing long-row shape.

    ``exportResultsToCSV`` writes one column per output path, with the path
    and its unit encoded in the header as ``"<path> [<unit>]"``, and a
    ``"Time [<unit>]"`` column. This unpivots that wide table into the same
    ``{"IndividualId", "Time", "simulationValues", "unit", "paths"}`` row
    shape the JSON transport's ``raw_result_rows`` already uses, so callers
    never need to know which transport produced the rows.
    """
    table = pa_csv.read_csv(path)
    column_names = table.column_names
    if "IndividualId" not in column_names:
        raise ValueError("Result CSV is missing an IndividualId column.")
    time_column = next((name for name in column_names if name.startswith("Time")), None)
    if time_column is None:
        raise ValueError("Result CSV is missing a Time column.")

    individual_ids = table.column("IndividualId").to_pylist()
    times = table.column(time_column).to_pylist()
    value_columns = [
        name
        for name in column_names
        if name not in _NON_VALUE_COLUMNS and name != time_column
    ]

    rows: list[dict[str, object]] = []
    for value_column in value_columns:
        path_name, unit = _parse_path_and_unit(value_column)
        values = table.column(value_column).to_pylist()
        for individual_id, time, value in zip(individual_ids, times, values, strict=True):
            rows.append(
                {
                    "IndividualId": individual_id,
                    "Time": time,
                    "simulationValues": value,
                    "unit": unit,
                    "paths": path_name,
                }
            )
    return tuple(rows)


def _parse_path_and_unit(header: str) -> tuple[str, str]:
    """Split ``"<path> [<unit>]"`` into its path and unit, as OSP writes it."""
    marker = header.rfind(" [")
    if marker == -1 or not header.endswith("]"):
        raise ValueError(f"Result CSV column header is not in '<path> [<unit>]' form: {header!r}")
    return header[:marker], header[marker + 2 : -1]
