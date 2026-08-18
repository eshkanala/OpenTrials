"""Generic external-evidence connector contract (v0.8-A).

The founding-spec gap this closes: every ``ObservedDataset``/``Evidence``
record in this project so far has been hand-constructed in test fixtures.
Nothing has ever declared, generically, how OpenTrials is supposed to get
from *an external source* to *an immutable, provenance-complete observed
dataset*. This module is that contract -- deliberately modeled after
``models.capability.ModelCapabilityProfile``'s v0.7 shape: a small, explicit,
data-first description of a capability (there, what a model supports; here,
where evidence came from and how it was turned into OpenTrials' own types),
kept independent of any one source's fetch mechanics.

Mirrors the same layering discipline used throughout this project: this
module knows nothing about HTTP, a specific file format, or OSP -- those
belong to a connector's own ``fetch()``/``normalize()`` implementation (see
``evidence.connectors`` for the first one), never to this contract.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.evidence import EvidenceSet
from opentrials.validation.observed import ObservedDataset


class DataConnectorIdentity(BaseModel):
    """Which connector implementation produced a run, and at what version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connector_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class SourceDescriptor(BaseModel):
    """Where the raw content came from, and under what rights.

    At least one of ``source_url``/``doi``/``accession`` is required --
    a connector must be able to point back to something a reader could,
    in principle, independently re-fetch or cite. ``retrieved_at`` is when
    *this* fetch happened, not when the upstream source was published.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: str | None = None
    doi: str | None = None
    accession: str | None = None
    license: str = Field(min_length=1)
    rights_notes: str | None = None
    retrieved_at: datetime

    @model_validator(mode="after")
    def validate_has_a_locator(self) -> SourceDescriptor:
        if not (self.source_url or self.doi or self.accession):
            raise ValueError(
                "A SourceDescriptor must declare at least one of source_url, doi, or accession."
            )
        return self


class RawSnapshot(BaseModel):
    """The exact bytes fetched from a source, before any interpretation.

    Kept deliberately separate from ``normalize()``'s output so a
    connector's "did we get the right bytes" step and its "what do these
    bytes mean" step can be verified independently -- the same fetch vs.
    execute separation ``adapters.osp.engine`` already uses for simulation
    runs. Never passed through ``core.serialization.document()``/``sha256()``
    directly (canonical JSON cannot represent raw bytes); the storage layer
    persists ``content`` to its own file and records only its hash and
    metadata in a manifest, the same pattern used for population Parquet
    tables elsewhere in this project.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: bytes
    media_type: str = Field(min_length=1)
    retrieved_at: datetime

    def content_sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.content).hexdigest()


class TransformationStep(BaseModel):
    """One explicit, human-readable step in turning raw content into OpenTrials types.

    Deliberately a plain description, not a machine-verifiable transform --
    the point is that nothing about how a connector interpreted its source
    is left implicit or undocumented, matching this project's discipline of
    recording *why*, not just *what*, everywhere else (see e.g.
    ``PhysiologyCoverageReport.interpretation``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1)
    details: dict[str, str] = Field(default_factory=dict)


class DataConnectorRunResult(BaseModel):
    """Everything one connector run produced, before persistence.

    This is the connector layer's return type, not a storage manifest --
    it legitimately holds the full raw bytes and the full normalized
    dataset in memory; ``orchestration.evidence_ingestion`` is what turns
    this into the three separate immutable, independently re-verifiable
    artifacts (raw snapshot, observed dataset, connector-run record).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: DataConnectorIdentity
    source: SourceDescriptor
    raw_snapshot: RawSnapshot
    transformation_provenance: tuple[TransformationStep, ...] = Field(min_length=1)
    evidence: EvidenceSet
    dataset: ObservedDataset


class IneligibleEvidenceCandidateError(ValueError):
    """Raised when ``normalize()`` discovers a candidate cannot be honestly represented.

    Distinct from a bug: this is a connector reporting that the source data
    itself does not fit OpenTrials' domain model in a way that would require
    inventing a value to paper over (e.g. a weight-normalized dose with no
    recoverable body weight, which ``compound.intervention.Dose`` correctly
    refuses since it requires mass dimensions). Raising this rather than
    forcing a workaround keeps the "nothing invented" discipline intact even
    when a candidate does not clear the gate.
    """


class DataConnector(Protocol):
    """The generic shape every evidence connector implements.

    ``fetch()`` is the only step allowed to know about the outside world
    (a network call, a local bundled file, a package resource -- the
    contract does not care which). ``normalize()`` must be pure with
    respect to its ``RawSnapshot`` argument: same bytes in, same
    ``DataConnectorRunResult`` out, no re-fetching, so it can be exercised
    in tests without whatever external dependency ``fetch()`` requires.
    """

    @property
    def identity(self) -> DataConnectorIdentity: ...

    def fetch(self) -> RawSnapshot: ...

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult: ...


def run_connector(connector: DataConnector) -> DataConnectorRunResult:
    """Execute one connector's full fetch-then-normalize cycle.

    The one generic orchestration entry point every connector shares --
    deliberately trivial, since the entire point of the contract is that
    nothing source-specific needs to live here.
    """
    return connector.normalize(connector.fetch())
