"""Versioned canonical serialization and SHA-256 object identity."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SchemaDocument(BaseModel):
    """The required persisted envelope for a top-level OpenTrials object."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_id: str = Field(
        alias="schema", serialization_alias="schema", pattern=r"^opentrials\.[a-z0-9.-]+$"
    )
    schema_version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    payload: dict[str, Any]

    def canonical_json(self) -> str:
        return canonical_json(self)

    def sha256(self) -> str:
        return sha256(self)


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(
            value.model_dump(mode="python", by_alias=True, exclude_none=True, exclude_defaults=True)
        )
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Canonical datetimes must be timezone-aware.")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
        raise ValueError("Canonical serialization rejects NaN and Infinity.")
    return value


def canonical_json(value: Any) -> str:
    """Emit UTF-8-safe, sorted, whitespace-free canonical JSON."""
    return json.dumps(
        _normalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256(value: Any) -> str:
    """Return the canonical SHA-256 content hash used across OpenTrials."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def document(
    schema: str, payload: BaseModel | dict[str, Any], schema_version: str = "1.0.0"
) -> SchemaDocument:
    """Wrap a typed object for durable top-level persistence."""
    normalized_payload = _normalize(payload)
    if not isinstance(normalized_payload, dict):
        raise TypeError("A schema document payload must be an object.")
    return SchemaDocument(schema=schema, schema_version=schema_version, payload=normalized_payload)
