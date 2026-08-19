"""Studio v0.4: guided model onboarding -- turning discovery into a reviewed registration.

``sdk.model_onboarding`` answers "what did OSP discover about this PKML
file?" and stops there, deliberately (see its own module docstring). This
module is the next stage: a mutable, persisted working document (an
``OnboardingDraft``) that a researcher fills in one capability at a time --
compound identity, administration route, output mapping, population
applicability -- with every filled-in value carrying its own source
record, evidence class, unit, and context, never just a bare number.

The whole flow refuses to skip steps:

    start_draft()            -- inspect once, keep the facts
    select_capability() * N  -- one researcher decision per slot,
                                 evidence-bearing, never silent
    set_unsupported_capabilities()
    build_profile_from_draft() -- assemble a real ModelCapabilityProfile,
                                    or fail clearly on what is still missing
    record_verification_run()  -- only a real completed execution can
                                    promote a selection from MAPPED to VERIFIED
    checklist()               -- every unresolved requirement, computed
                                    fresh each time, never cached/trusted
    register_model()          -- re-checks the checklist itself; no caller
                                    can bypass it by skipping a step client-side

``register_model()`` writes two immutable Registry records: the ``MODEL``
profile itself, and a separate ``MODEL_VERIFICATION`` record pinning
exactly which profile content hash was verified, against which real
executed run, on which OSP/R/OpenTrials versions -- so a later edit to
the profile can never silently inherit an old verification's credibility.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT
from opentrials.compound.intervention import Route
from opentrials.core.serialization import SchemaDocument, document, sha256
from opentrials.models.capability import (
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
    UnsupportedCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType
from opentrials.models.package import ModelPackage
from opentrials.registry import (
    EvidenceClass,
    ModelVerificationRecord,
    RegistryBackend,
    RegistryCompatibility,
    RegistryEntryManifest,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.sdk.model_onboarding import ModelInspectionReport, inspect_model

ONBOARDING_ROOT_ENV_VAR = "OPENTRIALS_ONBOARDING_ROOT"
ONBOARDING_DRAFT_SCHEMA = "opentrials.onboarding-draft"

REQUIRED_SLOTS = ("compound", "administration", "output", "applicability")


class CapabilityStatus(StrEnum):
    """What OpenTrials believes about one discovered/mapped capability.

    ``DISCOVERED``: OSP found a raw candidate; no researcher decision yet.
    ``MAPPED``: a researcher selected/entered a value; not yet confirmed
    by a real execution. ``VERIFIED``: a live verification run succeeded
    against the exact profile this selection is part of.
    ``UNSUPPORTED``: an explicit, reasoned gap, not a silent omission.
    ``REQUIRES_REVIEW``: a genuine, rules-detected ambiguity (e.g. more
    than one discovered candidate) that a researcher must resolve.
    """

    DISCOVERED = "DISCOVERED"
    MAPPED = "MAPPED"
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class CapabilitySelection(BaseModel):
    """One researcher decision for one onboarding slot.

    Deliberately carries more than the resolved value: a Registry-sourced
    selection is traceable back to ``source_record_id``, and every
    selection (Registry-sourced or hand-entered) must declare its own
    ``evidence_class`` -- there is no way to select a value without
    saying how trustworthy it is, matching the Registry's own "no value
    without an evidence class" discipline.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    slot: str = Field(min_length=1)
    status: CapabilityStatus
    value: dict[str, Any]
    source_record_id: str | None = None
    evidence_class: EvidenceClass | None = None
    unit: str | None = None
    context: str | None = None
    provenance_ids: tuple[str, ...] = ()


class OnboardingDraft(BaseModel):
    """A mutable, persisted working document -- not a registered artifact.

    Unlike everything in ``registry.store`` (write-once, immutable), a
    draft is edited in place: each mutating function here loads the
    current JSON, applies one change, and re-validates and re-saves the
    whole document, mirroring the same "full re-validation, never
    ``model_copy``" discipline ``config.project`` already uses for
    ``ProjectConfig`` edits.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    draft_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    pkml_path: str = Field(min_length=1)
    pkml_sha256: str = Field(min_length=1)
    inspection: ModelInspectionReport
    model_version: str | None = None
    license: str | None = None
    selections: dict[str, CapabilitySelection] = Field(default_factory=dict)
    unsupported_capabilities: tuple[UnsupportedCapability, ...] = ()
    unsupported_reviewed: bool = False
    verification_run_id: str | None = None
    verified_profile_sha256: str | None = None
    verified_endpoint_types: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime


# ================= persistence =================


def _default_onboarding_root() -> Path:
    """Shared across every project a researcher opens, same convention as the Registry."""
    explicit = os.environ.get(ONBOARDING_ROOT_ENV_VAR)
    if explicit:
        return Path(explicit)
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "opentrials" / "onboarding"


def _resolve_root(root: str | Path | None) -> Path:
    return _default_onboarding_root() if root is None else Path(root)


def _draft_path(draft_id: str, root: Path) -> Path:
    return root / f"{draft_id}.json"


def _save_draft(draft: OnboardingDraft, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _draft_path(draft.draft_id, root).write_text(
        document(ONBOARDING_DRAFT_SCHEMA, draft).canonical_json() + "\n", encoding="utf-8"
    )


def load_draft(draft_id: str, *, root: str | Path | None = None) -> OnboardingDraft:
    path = _draft_path(draft_id, _resolve_root(root))
    if not path.is_file():
        raise ValueError(f"Unknown onboarding draft: {draft_id!r}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    envelope = SchemaDocument.model_validate(raw)
    if envelope.schema_id != ONBOARDING_DRAFT_SCHEMA:
        raise ValueError(
            f"Expected schema {ONBOARDING_DRAFT_SCHEMA!r}; got {envelope.schema_id!r}."
        )
    return OnboardingDraft.model_validate(envelope.payload)


def list_drafts(*, root: str | Path | None = None) -> tuple[OnboardingDraft, ...]:
    resolved_root = _resolve_root(root)
    if not resolved_root.is_dir():
        return ()
    drafts = [
        load_draft(candidate.stem, root=resolved_root)
        for candidate in sorted(resolved_root.glob("*.json"))
    ]
    drafts.sort(key=lambda d: d.updated_at, reverse=True)
    return tuple(drafts)


def _resave(draft: OnboardingDraft, data: dict[str, Any], root: Path) -> OnboardingDraft:
    data["updated_at"] = datetime.now(UTC).isoformat()
    updated = OnboardingDraft.model_validate(data)
    _save_draft(updated, root)
    return updated


# ================= draft lifecycle =================


def start_draft(
    pkml_path: str | Path,
    *,
    model_id: str,
    r_libs_user: str | None = None,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
    root: str | Path | None = None,
) -> OnboardingDraft:
    """Inspect a PKML file once and start a fresh, empty draft for it."""
    report = inspect_model(
        Path(pkml_path), r_libs_user=r_libs_user, rscript_path=rscript_path, dotnet_root=dotnet_root
    )
    now = datetime.now(UTC)
    draft = OnboardingDraft(
        draft_id=uuid.uuid4().hex,
        model_id=model_id,
        pkml_path=str(report.pkml_path),
        pkml_sha256=report.pkml_sha256,
        inspection=report,
        created_at=now,
        updated_at=now,
    )
    _save_draft(draft, _resolve_root(root))
    return draft


def set_model_metadata(
    draft_id: str, *, model_version: str, license: str, root: str | Path | None = None
) -> OnboardingDraft:
    """Declare the two profile-level facts that are not a Registry-matchable capability."""
    resolved_root = _resolve_root(root)
    draft = load_draft(draft_id, root=resolved_root)
    data = draft.model_dump(mode="json")
    data["model_version"] = model_version
    data["license"] = license
    return _resave(draft, data, resolved_root)


def select_capability(
    draft_id: str,
    *,
    slot: str,
    value: dict[str, Any],
    source_record_id: str | None = None,
    evidence_class: EvidenceClass | None = None,
    unit: str | None = None,
    context: str | None = None,
    provenance_ids: tuple[str, ...] = (),
    root: str | Path | None = None,
) -> OnboardingDraft:
    """Record one researcher decision for one slot.

    Always lands as ``MAPPED`` -- only ``record_verification_run`` may
    promote a selection to ``VERIFIED``, since that is the only event
    that actually proves the mapping works.
    """
    if slot not in REQUIRED_SLOTS:
        raise ValueError(f"Unknown onboarding slot {slot!r}; expected one of {REQUIRED_SLOTS}.")
    resolved_root = _resolve_root(root)
    draft = load_draft(draft_id, root=resolved_root)
    selection = CapabilitySelection(
        slot=slot,
        status=CapabilityStatus.MAPPED,
        value=value,
        source_record_id=source_record_id,
        evidence_class=evidence_class,
        unit=unit,
        context=context,
        provenance_ids=provenance_ids,
    )
    data = draft.model_dump(mode="json")
    data["selections"][slot] = selection.model_dump(mode="json")
    return _resave(draft, data, resolved_root)


def set_unsupported_capabilities(
    draft_id: str, *, items: Sequence[dict[str, str]], root: str | Path | None = None
) -> OnboardingDraft:
    """Explicitly record what this model does not support -- called at least once, even if empty.

    Calling this with an empty list is a real, meaningful action ("I
    reviewed this and there is nothing to declare"), distinct from never
    having called it at all -- the checklist's
    ``unsupported_capabilities_reviewed`` item checks for exactly that.
    """
    resolved_root = _resolve_root(root)
    draft = load_draft(draft_id, root=resolved_root)
    capabilities = [UnsupportedCapability.model_validate(item) for item in items]
    data = draft.model_dump(mode="json")
    data["unsupported_capabilities"] = [c.model_dump(mode="json") for c in capabilities]
    data["unsupported_reviewed"] = True
    return _resave(draft, data, resolved_root)


# ================= assembly =================


def build_profile_from_draft(draft: OnboardingDraft) -> ModelCapabilityProfile:
    """Assemble a real ``ModelCapabilityProfile`` from the draft's current selections.

    Raises ``ValueError`` with exactly what is still missing -- used both
    to gate a live verification run and, via ``checklist()``, to gate
    registration itself. Physiology targets are deliberately never
    populated here: they are not discovered automatically (see
    ``sdk.model_onboarding``'s own scaffold) and are out of this
    milestone's scope, matching that existing, already-documented gap.
    """
    missing = [slot for slot in REQUIRED_SLOTS if slot not in draft.selections]
    model_version = draft.model_version
    license_value = draft.license
    if model_version is None:
        missing.append("model_version")
    if license_value is None:
        missing.append("license")
    if missing:
        raise ValueError(f"Cannot build a profile yet -- missing: {', '.join(missing)}.")
    assert model_version is not None  # guaranteed by the missing-list check above
    assert license_value is not None  # guaranteed by the missing-list check above

    try:
        compound_value = draft.selections["compound"].value
        compound_capability = CompoundCapability(
            compound_id=str(compound_value["compound_id"]),
            engine_molecule_id=str(compound_value["engine_molecule_id"]),
        )

        admin_value = dict(draft.selections["administration"].value)
        administration_capability = AdministrationCapability(
            target_id=str(admin_value["target_id"]),
            compound_id=compound_capability.compound_id,
            route=Route(admin_value["route"]),
            administration_container_path=str(admin_value["administration_container_path"]),
            dose_parameter_path=str(admin_value["dose_parameter_path"]),
            dose_unit=str(admin_value["dose_unit"]),
            administration_time_parameter_path=str(
                admin_value["administration_time_parameter_path"]
            ),
            administration_time_unit=str(admin_value["administration_time_unit"]),
            infusion_duration_parameter_path=admin_value.get("infusion_duration_parameter_path"),
            infusion_duration_unit=admin_value.get("infusion_duration_unit"),
            supported_doses=tuple(float(d) for d in admin_value.get("supported_doses", ())),
            supported_dose_unit=admin_value.get("supported_dose_unit"),
            fixed_administration_time_min=(
                float(admin_value["fixed_administration_time_min"])
                if admin_value.get("fixed_administration_time_min") is not None
                else None
            ),
            fixed_infusion_duration_min=(
                float(admin_value["fixed_infusion_duration_min"])
                if admin_value.get("fixed_infusion_duration_min") is not None
                else None
            ),
        )

        output_value = dict(draft.selections["output"].value)
        output_capability = OutputCapability(
            output_id=str(output_value["output_id"]),
            parameter_path=str(output_value["parameter_path"]),
            analyte=str(output_value.get("analyte") or compound_capability.compound_id),
            matrix=str(output_value["matrix"]),
            fraction=str(output_value["fraction"]),
            measurement=str(output_value.get("measurement") or "concentration"),
            unit=str(output_value["unit"]),
            time_unit=str(output_value["time_unit"]),
        )

        applicability_value = dict(draft.selections["applicability"].value)
        species = tuple(str(s) for s in applicability_value["species"])

        manifest = ModelManifest(
            id=draft.model_id,
            version=model_version,
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),
            units={"plasma_concentration": output_capability.unit},
            applicability=Applicability(species=species),
            license=license_value,
        )
        package = ModelPackage(
            manifest=manifest,
            artifact_uri=f"file://{draft.pkml_path}",
            artifact_hash=draft.pkml_sha256,
            parameter_set_id=draft.pkml_sha256,
            parameter_hash=draft.pkml_sha256,
            package_hash=draft.pkml_sha256,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Cannot build a profile from the current selections: {error}") from error

    return ModelCapabilityProfile(
        package=package,
        compounds=(compound_capability,),
        administrations=(administration_capability,),
        physiology_targets=(),
        outputs=(output_capability,),
        unsupported_capabilities=draft.unsupported_capabilities,
    )


def record_verification_run(
    draft_id: str, *, run_id: str, endpoint_types: Sequence[str], root: str | Path | None = None
) -> OnboardingDraft:
    """Promote every currently-``MAPPED`` selection to ``VERIFIED`` after a real completed run.

    Pins the exact profile content hash that was verified -- if the
    researcher changes a selection afterward, ``checklist()`` will report
    the verification as stale, since the recomputed hash will no longer
    match, rather than silently letting an edited profile keep an old run's
    credibility.
    """
    resolved_root = _resolve_root(root)
    draft = load_draft(draft_id, root=resolved_root)
    profile = build_profile_from_draft(draft)
    profile_sha256 = sha256(profile)

    data = draft.model_dump(mode="json")
    for selection in data["selections"].values():
        if selection["status"] == CapabilityStatus.MAPPED.value:
            selection["status"] = CapabilityStatus.VERIFIED.value
    data["verification_run_id"] = run_id
    data["verified_profile_sha256"] = profile_sha256
    data["verified_endpoint_types"] = list(endpoint_types)
    return _resave(draft, data, resolved_root)


# ================= checklist + registration =================


def checklist(draft: OnboardingDraft) -> dict[str, Any]:
    """Every unresolved requirement, recomputed fresh -- never cached or trusted from the client."""
    checks: list[dict[str, str]] = []
    ok = True

    def add(requirement: str, label: str, satisfied: bool, detail: str) -> None:
        nonlocal ok
        checks.append(
            {
                "requirement": requirement,
                "label": label,
                "status": "verified" if satisfied else "absent",
                "detail": detail,
            }
        )
        if not satisfied:
            ok = False

    compound_sel = draft.selections.get("compound")
    add(
        "compound_identity",
        "Compound identity",
        compound_sel is not None,
        str(compound_sel.value.get("compound_id", "")) if compound_sel else "not yet mapped",
    )

    admin_sel = draft.selections.get("administration")
    admin_value = admin_sel.value if admin_sel else {}
    add(
        "route",
        "Administration route",
        bool(admin_value.get("route")),
        str(admin_value.get("route") or "not yet chosen"),
    )
    add(
        "dose_parameter",
        "Dose parameter mapping",
        bool(admin_value.get("dose_parameter_path")),
        str(admin_value.get("dose_parameter_path") or "not yet mapped"),
    )

    output_sel = draft.selections.get("output")
    output_value = output_sel.value if output_sel else {}
    units_present = bool(
        admin_value.get("dose_unit")
        and admin_value.get("administration_time_unit")
        and output_value.get("unit")
        and output_value.get("time_unit")
    )
    add(
        "units",
        "Units (dose, administration time, output, output time)",
        units_present,
        "all declared" if units_present else "one or more units not yet declared",
    )

    add(
        "output_mapping",
        "Output mapping",
        "output" in draft.selections,
        str(output_value.get("parameter_path") or "not yet mapped"),
    )

    applic_sel = draft.selections.get("applicability")
    add(
        "population_compatibility",
        "Population applicability",
        applic_sel is not None,
        ", ".join(applic_sel.value.get("species", [])) if applic_sel else "not yet declared",
    )

    mapped_or_verified = [
        selection
        for selection in draft.selections.values()
        if selection.status in (CapabilityStatus.MAPPED, CapabilityStatus.VERIFIED)
    ]
    provenance_ok = bool(mapped_or_verified) and all(
        selection.evidence_class is not None for selection in mapped_or_verified
    )
    add(
        "evidence_provenance",
        "Evidence provenance on every selection",
        provenance_ok,
        "every selection carries an evidence class"
        if provenance_ok
        else "one or more selections has no evidence_class",
    )

    add(
        "unsupported_capabilities_reviewed",
        "Unsupported capabilities reviewed",
        draft.unsupported_reviewed,
        f"{len(draft.unsupported_capabilities)} declared"
        if draft.unsupported_reviewed
        else "not yet reviewed",
    )

    try:
        current_profile_sha256: str | None = sha256(build_profile_from_draft(draft))
    except ValueError:
        current_profile_sha256 = None
    verification_ok = (
        draft.verification_run_id is not None
        and current_profile_sha256 is not None
        and draft.verified_profile_sha256 == current_profile_sha256
    )
    if draft.verification_run_id is None:
        verification_detail = "not yet run"
    elif not verification_ok:
        verification_detail = "stale -- selections changed since the last verified run"
    else:
        verification_detail = f"run {draft.verification_run_id}"
    add("live_verification_run", "Live verification run", verification_ok, verification_detail)

    return {"ok": ok, "checks": checks}


def register_model(
    draft_id: str, *, backend: RegistryBackend, root: str | Path | None = None
) -> dict[str, RegistryEntryManifest]:
    """Register a MODEL record and its MODEL_VERIFICATION record -- gated, no bypass.

    Recomputes the checklist itself rather than trusting a client-side
    "all done" flag: every requirement is re-checked here, and a caller
    cannot register a model by skipping a step in the UI.
    """
    draft = load_draft(draft_id, root=root)
    result = checklist(draft)
    if not result["ok"]:
        unmet = [c["label"] for c in result["checks"] if c["status"] != "verified"]
        raise ValueError(
            f"Cannot register model {draft.model_id!r}: unmet requirement(s) -- {'; '.join(unmet)}."
        )

    profile = build_profile_from_draft(draft)
    if draft.verification_run_id is None:
        raise ValueError(
            "Cannot register: no verification run recorded despite a passing checklist."
        )

    model_manifest = backend.put(
        RegistryRecordKind.MODEL,
        profile,
        logical_id=profile.package.manifest.id,
        evidence_class=EvidenceClass.CURATED,
        license=profile.package.manifest.license,
        source=RegistrySource(kind="studio_onboarding", identifier=draft.draft_id),
    )
    verification_record = ModelVerificationRecord(
        model_id=profile.package.manifest.id,
        profile_sha256=sha256(profile),
        pkml_sha256=draft.pkml_sha256,
        run_id=draft.verification_run_id,
        endpoint_types=draft.verified_endpoint_types,
        opentrials_version=installed_version("opentrials"),
        ospsuite_version=draft.inspection.ospsuite_version,
        r_version=draft.inspection.r_version,
    )
    verification_manifest = backend.put(
        RegistryRecordKind.MODEL_VERIFICATION,
        verification_record,
        logical_id=f"{profile.package.manifest.id}-verification",
        evidence_class=EvidenceClass.SIMULATED,
        license=profile.package.manifest.license,
        source=RegistrySource(kind="model_verification_run", identifier=draft.verification_run_id),
        compatibility=RegistryCompatibility(model_ids=(profile.package.manifest.id,)),
    )
    return {"model": model_manifest, "verification": verification_manifest}
