"""Immutable, deterministic rank/percentile-based extreme-responder rules.

Deliberately transparent selection only: percentile/rank cutoffs against one
lineage-aware ``OTPK`` endpoint. No machine-learning anomaly detection, and no
causal claim -- a selection rule only ever describes *how subjects were
grouped*, never *why they responded that way*.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.analysis.pk import PkEndpointType
from opentrials.core.serialization import sha256
from opentrials.models.package import SHA256_PATTERN

RESPONDER_DEFINITION_ID_PATTERN = r"^OTRESP-[A-Za-z0-9_-]+$"
RESPONDER_MEMBERSHIP_ID_PATTERN = r"^OTXMEM-[A-Za-z0-9_-]+$"


class SelectionMethod(StrEnum):
    """How the extreme tail is carved out of the ranked population."""

    TOP_PERCENTILE = "TOP_PERCENTILE"
    BOTTOM_PERCENTILE = "BOTTOM_PERCENTILE"
    ABOVE_PERCENTILE = "ABOVE_PERCENTILE"
    BELOW_PERCENTILE = "BELOW_PERCENTILE"
    TOP_N = "TOP_N"
    BOTTOM_N = "BOTTOM_N"


class TiePolicy(StrEnum):
    """How subjects exactly at a selection boundary are treated.

    For count-based methods (``TOP_N``/``BOTTOM_N``/percentile-by-count):
    ``STRICT_COUNT`` always returns exactly the requested count, breaking
    ties by a stable deterministic secondary key; ``INCLUDE_ALL_TIES``
    includes every subject tied with the boundary value, so the actual count
    may exceed the requested one. For threshold methods
    (``ABOVE_PERCENTILE``/``BELOW_PERCENTILE``): ``STRICT_COUNT`` excludes
    subjects exactly at the computed cutoff value; ``INCLUDE_ALL_TIES``
    includes them.
    """

    STRICT_COUNT = "STRICT_COUNT"
    INCLUDE_ALL_TIES = "INCLUDE_ALL_TIES"


_PERCENTILE_COUNT_METHODS = frozenset(
    {SelectionMethod.TOP_PERCENTILE, SelectionMethod.BOTTOM_PERCENTILE}
)
_PERCENTILE_THRESHOLD_METHODS = frozenset(
    {SelectionMethod.ABOVE_PERCENTILE, SelectionMethod.BELOW_PERCENTILE}
)
_COUNT_METHODS = frozenset({SelectionMethod.TOP_N, SelectionMethod.BOTTOM_N})
PERCENTILE_METHODS = _PERCENTILE_COUNT_METHODS | _PERCENTILE_THRESHOLD_METHODS
HIGH_DIRECTION_METHODS = frozenset(
    {SelectionMethod.TOP_PERCENTILE, SelectionMethod.ABOVE_PERCENTILE, SelectionMethod.TOP_N}
)


class ExtremeResponderDefinition(BaseModel):
    """An immutable selection rule bound to one verified, lineage-aware OTPK."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    definition_id: str = Field(pattern=RESPONDER_DEFINITION_ID_PATTERN)
    source_endpoint_id: str = Field(pattern=r"^OTPK-[A-Za-z0-9_-]+$")
    source_endpoint_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    source_generation_id: str = Field(pattern=r"^OTPGEN-[A-Za-z0-9_-]+$")
    source_population_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_type: PkEndpointType
    method: SelectionMethod
    percentile: float | None = Field(default=None, gt=0.0, lt=100.0)
    count: int | None = Field(default=None, gt=0)
    tie_policy: TiePolicy

    @model_validator(mode="after")
    def validate_threshold_shape(self) -> ExtremeResponderDefinition:
        if self.method in PERCENTILE_METHODS:
            if self.percentile is None or self.count is not None:
                raise ValueError(f"{self.method.value} requires percentile only, not count.")
        elif self.method in _COUNT_METHODS:
            if self.count is None or self.percentile is not None:
                raise ValueError(f"{self.method.value} requires count only, not percentile.")
        else:  # pragma: no cover - defensive, all StrEnum members are covered above
            raise ValueError(f"Unhandled selection method: {self.method.value}")
        return self

    def canonical_sha256(self) -> str:
        return sha256(self)
