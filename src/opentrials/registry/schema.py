"""OpenTrials Registry v0.1: immutable, versioned records of reusable scientific knowledge.

Every record kind (model, compound, parameter evidence, dataset, experiment)
shares one envelope, ``RegistryEntryManifest``, wrapping a kind-specific
payload. This deliberately does not redeclare fields the project already
has correct, hand-verified types for: a ``MODEL`` record's payload *is* a
``models.capability.ModelCapabilityProfile``, a ``COMPOUND`` record's
payload *is* a ``compound.Compound``, a ``DATASET`` record's payload *is* a
``validation.ObservedDataset`` -- the Registry only adds what those types
do not already carry: a stable record identity, an explicit evidence
class, license/source/compatibility metadata, and a content hash, using
exactly the ``SchemaDocument``/``sha256()`` convention every other
persisted artifact in this project already follows (see
``core.serialization``).

Three record kinds are genuinely new to this project and have no existing
type to wrap: ``PARAMETER_EVIDENCE`` (one registered parameter value with
its own evidence trail, distinct from a full dataset), ``EXPERIMENT``
(a registered OpenTrials trial protocol, optionally linked to a real
execution -- simulated outcomes are recorded with ``evidence_class =
SIMULATED``, never promoted to ``MEASURED``/``CURATED``, enforced by
``RegistryEntryManifest``'s own validator, not left to caller discipline),
and ``MODEL_VERIFICATION`` (Studio v0.4's guided onboarding: a small,
immutable record of exactly what was verified about a ``MODEL`` record --
which profile content hash, against which real executed run, on which
OSP/R/OpenTrials versions -- distinct from the ``MODEL`` record itself,
which only declares what a profile *claims*).

``ValueType`` (``core.scientific_value``) and this module's
``EvidenceClass`` are deliberately distinct, not aliases: ``ValueType``
tags one scalar ``ScientificValue`` with how *that number* was produced
(observed/derived/assumed/...); ``EvidenceClass`` classifies an entire
*Registry record* by how trustworthy/reusable it is as a whole. A
``ParameterEvidenceRecord`` legitimately holds a ``ScientificValue`` whose
own ``value_type`` and the record's own ``evidence_class`` do not have to
match one-for-one.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.compound import Compound
from opentrials.core.scientific_value import ScientificValue
from opentrials.core.serialization import sha256
from opentrials.models import ModelCapabilityProfile
from opentrials.models.package import SHA256_PATTERN
from opentrials.trials.trial import Trial
from opentrials.validation import ObservedDataset

RECORD_ID_PATTERN = r"^OTREG-[A-Z_]+-[A-Za-z0-9_.-]+$"
SEMVER_PATTERN = r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
REGISTRY_ENTRY_SCHEMA = "opentrials.registry-entry"


class EvidenceClass(StrEnum):
    """How trustworthy/reusable a whole Registry record is, coarse-to-fine.

    Distinct from ``core.scientific_value.ValueType`` -- see this module's
    own docstring for why. No record enters the Registry without one of
    these; there is no "unclassified" option.
    """

    MEASURED = "MEASURED"
    """Directly measured in a real experiment (e.g. an observed PK sample)."""
    CURATED = "CURATED"
    """Hand-reviewed and selected from a real source by a researcher."""
    DERIVED = "DERIVED"
    """Computed from other MEASURED/CURATED records by a documented, reproducible method."""
    FITTED = "FITTED"
    """The result of fitting a model/parameter to real data."""
    MODEL_INHERITED = "MODEL_INHERITED"
    """Carried over from a model's own prior parameterization, not independently re-derived."""
    SIMULATED = "SIMULATED"
    """Produced by running an OpenTrials model -- a prediction, never evidence of the real world."""
    ASSUMED = "ASSUMED"
    """An explicit, undocumented-elsewhere assumption -- the weakest class, never silent."""


class RegistryRecordKind(StrEnum):
    """The six record kinds Registry v0.1 supports.

    Deliberately excludes one kind named in earlier planning ("capability
    profiles"): a capability profile is already the ``MODEL`` payload's
    own content (``ModelCapabilityProfile`` already bundles
    package/manifest/capabilities -- registering it separately would
    fragment one correct unit into two). "Validation records", the other
    kind named in that same earlier planning note, are close kin to
    ``DATASET``/``EXPERIMENT`` but need their own design pass against
    ``validation.study.ValidationResult`` -- still left open, distinct
    from ``MODEL_VERIFICATION`` below (which verifies a *model's own
    onboarding claims*, not a trial's scientific validity against real data).
    """

    MODEL = "MODEL"
    COMPOUND = "COMPOUND"
    PARAMETER_EVIDENCE = "PARAMETER_EVIDENCE"
    DATASET = "DATASET"
    EXPERIMENT = "EXPERIMENT"
    MODEL_VERIFICATION = "MODEL_VERIFICATION"


class RegistrySource(BaseModel):
    """Where this record's content actually came from -- always required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(
        min_length=1,
        description=(
            "e.g. 'connector', 'manual_curation', 'model_package', "
            "'experiment_run', 'literature'."
        ),
    )
    identifier: str = Field(
        min_length=1, description="connector_id / DOI / file path / run_id / free citation text."
    )
    url: str | None = None
    retrieved_at: datetime | None = None


class RegistryCompatibility(BaseModel):
    """Optional declared context this record is only known to be valid within."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    species: tuple[str, ...] = ()
    route: str | None = None
    model_ids: tuple[str, ...] = Field(
        default=(), description="Registered model IDs this record applies to or was derived from."
    )
    notes: str | None = None


class ParameterEvidenceRecord(BaseModel):
    """One registered parameter value with its own evidence trail.

    Distinct from a full ``DATASET`` record: this is a single reusable
    value (e.g. one clearance estimate), not a collection of observations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str = Field(min_length=1, description="e.g. 'aciclovir.renal_clearance'.")
    compound_id: str | None = None
    target: str | None = Field(
        default=None, description="e.g. a physiology target string or model parameter path."
    )
    value: ScientificValue
    applicable_model_ids: tuple[str, ...] = ()
    narrative: str | None = None


class ExperimentRecord(BaseModel):
    """A registered OpenTrials trial protocol, optionally linked to a real execution.

    Carries the full ``trial`` protocol, not just a hash of it: a
    registered experiment exists so a researcher can later *fork* it (load
    it as the starting point for a new project), which a hash alone
    cannot reconstruct. ``trial_sha256`` still pins this record to one
    exact, immutable content identity (via ``core.serialization.sha256``,
    the same convention every other cross-reference in this project uses)
    so a caller can cite/verify the trial without re-hashing it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_id: str = Field(min_length=1)
    trial: Trial
    trial_sha256: str = Field(pattern=SHA256_PATTERN)
    model_id: str = Field(min_length=1)
    run_id: str | None = Field(default=None, description="OTR-* if a real execution is attached.")
    title: str = Field(min_length=1)
    summary: str | None = None
    endpoint_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_trial_hash(self) -> ExperimentRecord:
        actual = sha256(self.trial)
        if actual != self.trial_sha256:
            raise ValueError(
                f"trial_sha256 ({self.trial_sha256}) does not match the actual hash of "
                f"the embedded trial ({actual}) -- pass sha256(trial), not a stale value."
            )
        if self.trial_id != self.trial.trial_id:
            raise ValueError("trial_id must match the embedded trial's own trial_id.")
        return self


class ModelVerificationRecord(BaseModel):
    """What was actually verified about one registered ``MODEL`` record.

    A ``MODEL`` record's ``ModelCapabilityProfile`` only declares what a
    profile *claims* to support; this record is the evidence that a real
    execution actually confirmed those claims -- pinned to the exact
    profile content hash verified (so a later, edited profile version
    cannot silently inherit an old verification) and the exact executed
    run that proved it, matching this project's "verify, don't just
    trust a claim" discipline everywhere else (``registry.store.verify``,
    ``sdk.physiology.verify_physiology_states``, ...).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    profile_sha256: str = Field(pattern=SHA256_PATTERN)
    pkml_sha256: str = Field(pattern=SHA256_PATTERN)
    run_id: str = Field(min_length=1)
    endpoint_types: tuple[str, ...] = Field(min_length=1)
    opentrials_version: str = Field(min_length=1)
    ospsuite_version: str = Field(min_length=1)
    r_version: str = Field(min_length=1)


class RegistryEntryManifest(BaseModel):
    """The one shared envelope every Registry record kind is wrapped in.

    Immutable and versioned by convention, not by mutation: a "new
    version" of a record is a brand-new ``record_id`` with an incremented
    ``version``, never a rewrite of an existing one -- matching every
    other artifact store in this project (write-once, ``FileExistsError``
    on any attempted overwrite; see ``registry.store``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    record_id: str = Field(pattern=RECORD_ID_PATTERN)
    logical_id: str = Field(
        min_length=1,
        description=(
            "Stable identity across versions (e.g. 'osp.aciclovir.vergin-1995-iv' for a "
            "model, 'aciclovir' for a compound) -- what a 'give me the latest' query resolves."
        ),
    )
    kind: RegistryRecordKind
    version: str = Field(pattern=SEMVER_PATTERN)
    evidence_class: EvidenceClass
    license: str = Field(min_length=1)
    source: RegistrySource
    compatibility: RegistryCompatibility | None = None
    provenance_ids: tuple[str, ...] = ()
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    superseded_id: str | None = Field(
        default=None,
        pattern=RECORD_ID_PATTERN,
        description="The prior record_id this version replaces, if any.",
    )
    created_at: datetime

    @model_validator(mode="after")
    def validate_simulated_evidence_stays_simulated(self) -> RegistryEntryManifest:
        if (
            self.kind is RegistryRecordKind.EXPERIMENT
            and self.source.kind == "experiment_run"
            and self.evidence_class is not EvidenceClass.SIMULATED
        ):
            raise ValueError(
                "An experiment record sourced from a real OpenTrials execution "
                "('experiment_run') must be classified evidence_class=SIMULATED -- "
                "a simulated outcome may never be registered as MEASURED/CURATED/DERIVED "
                "evidence of the real world."
            )
        if (
            self.kind is RegistryRecordKind.MODEL_VERIFICATION
            and self.source.kind == "model_verification_run"
            and self.evidence_class is not EvidenceClass.SIMULATED
        ):
            raise ValueError(
                "A model-verification record sourced from a real onboarding execution "
                "('model_verification_run') must be classified evidence_class=SIMULATED -- "
                "it documents what a simulation showed, not measured real-world evidence."
            )
        return self


PAYLOAD_TYPES: dict[RegistryRecordKind, type[BaseModel]] = {
    RegistryRecordKind.MODEL: ModelCapabilityProfile,
    RegistryRecordKind.COMPOUND: Compound,
    RegistryRecordKind.PARAMETER_EVIDENCE: ParameterEvidenceRecord,
    RegistryRecordKind.DATASET: ObservedDataset,
    RegistryRecordKind.EXPERIMENT: ExperimentRecord,
    RegistryRecordKind.MODEL_VERIFICATION: ModelVerificationRecord,
}
"""Each record kind's payload is either a type this project already had (``MODEL``/
``COMPOUND``/``DATASET`` wrap existing, correct, hand-verified schemas rather than
redeclaring their fields) or one of the two genuinely new types this module defines
(``PARAMETER_EVIDENCE``, ``EXPERIMENT``) -- see the module docstring."""


def coerce_payload(kind: RegistryRecordKind, payload: dict[str, Any]) -> BaseModel:
    """Validate a raw payload dict against its kind's registered pydantic type."""
    return PAYLOAD_TYPES[kind].model_validate(payload)
