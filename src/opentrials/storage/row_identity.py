"""Canonical hashing for one verified source-table row.

Kept dependency-free (only ``core.serialization``) so both ``cohort`` and
other ``storage`` modules can share it without creating an import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from opentrials.core.serialization import sha256


def source_row_sha256(column_names: Sequence[str], row: Mapping[str, object]) -> str:
    """Hash every declared source-table cell, not merely fields used in selection."""
    columns = tuple(column_names)
    return sha256({"columns": columns, "row": {column: row[column] for column in columns}})
