"""Contract tests for sdk.onboarding -- Studio v0.4's guided model onboarding.

``inspect_model`` itself already has its own coverage (``test_sdk_...``
does not exist for it because it needs real OSP); here it is monkeypatched
to a fixed fake report so draft lifecycle, selection persistence, profile
assembly, the validation checklist, and the registration gate can all be
proven without OSP -- exactly the same isolation discipline
``test_studio_bridge.py`` already uses for its own OSP-dependent paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentrials.registry import EvidenceClass, FilesystemRegistryBackend, RegistryRecordKind
from opentrials.sdk import onboarding as sdk_onboarding
from opentrials.sdk.model_onboarding import ModelInspectionReport


def fake_report(pkml_path: Path) -> ModelInspectionReport:
    return ModelInspectionReport(
        pkml_path=pkml_path,
        pkml_sha256="sha256:" + "a" * 64,
        name="Fake Model",
        molecule_names=("Aciclovir",),
        administrations=(),
        output_paths=("Organism|VenousBlood|Plasma|Aciclovir|Concentration in container",),
        mutable_parameter_count=3,
        population_support_detected=True,
        ospsuite_version="12.0.0",
        r_version="4.6.0",
    )


@pytest.fixture(autouse=True)
def _stub_inspect_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_inspect_model(pkml_path: Path, **kwargs: Any) -> ModelInspectionReport:
        return fake_report(Path(pkml_path))

    monkeypatch.setattr(sdk_onboarding, "inspect_model", fake_inspect_model)


def start(tmp_path: Path, *, model_id: str = "osp.fake.test") -> sdk_onboarding.OnboardingDraft:
    return sdk_onboarding.start_draft(
        tmp_path / "fake.pkml", model_id=model_id, root=tmp_path / "onboarding"
    )


def fill_all_slots(
    tmp_path: Path, draft: sdk_onboarding.OnboardingDraft
) -> sdk_onboarding.OnboardingDraft:
    root = tmp_path / "onboarding"
    sdk_onboarding.select_capability(
        draft.draft_id,
        slot="compound",
        value={"compound_id": "aciclovir", "engine_molecule_id": "Aciclovir"},
        evidence_class=EvidenceClass.CURATED,
        source_record_id="OTREG-COMPOUND-abc",
        root=root,
    )
    sdk_onboarding.select_capability(
        draft.draft_id,
        slot="administration",
        value={
            "target_id": "iv-target",
            "route": "INTRAVENOUS",
            "administration_container_path": "Events|IV|",
            "dose_parameter_path": "Events|IV|Dose",
            "dose_unit": "mg",
            "administration_time_parameter_path": "Events|IV|Start time",
            "administration_time_unit": "min",
            "infusion_duration_parameter_path": None,
            "infusion_duration_unit": None,
            "supported_doses": [250.0],
            "supported_dose_unit": "mg",
        },
        evidence_class=EvidenceClass.ASSUMED,
        context="hand-entered from discovery",
        root=root,
    )
    sdk_onboarding.select_capability(
        draft.draft_id,
        slot="output",
        value={
            "output_id": "plasma",
            "parameter_path": "Organism|VenousBlood|Plasma|Aciclovir|Concentration in container",
            "analyte": "aciclovir",
            "matrix": "plasma",
            "fraction": "total",
            "measurement": "concentration",
            "unit": "mg/l",
            "time_unit": "h",
        },
        evidence_class=EvidenceClass.ASSUMED,
        root=root,
    )
    sdk_onboarding.select_capability(
        draft.draft_id,
        slot="applicability",
        value={"species": ["human"]},
        evidence_class=EvidenceClass.ASSUMED,
        root=root,
    )
    sdk_onboarding.set_model_metadata(
        draft.draft_id, model_version="1.0.0", license="CC-BY-4.0", root=root
    )
    return sdk_onboarding.load_draft(draft.draft_id, root=root)


def test_start_draft_persists_and_round_trips(tmp_path: Path) -> None:
    draft = start(tmp_path)
    reloaded = sdk_onboarding.load_draft(draft.draft_id, root=tmp_path / "onboarding")
    assert reloaded.draft_id == draft.draft_id
    assert reloaded.model_id == "osp.fake.test"
    assert reloaded.inspection.molecule_names == ("Aciclovir",)
    assert reloaded.selections == {}


def test_load_draft_raises_for_an_unknown_draft_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown onboarding draft"):
        sdk_onboarding.load_draft("no-such-draft", root=tmp_path / "onboarding")


def test_list_drafts_returns_every_persisted_draft(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    first = sdk_onboarding.start_draft(tmp_path / "a.pkml", model_id="osp.a", root=root)
    second = sdk_onboarding.start_draft(tmp_path / "b.pkml", model_id="osp.b", root=root)
    ids = {d.draft_id for d in sdk_onboarding.list_drafts(root=root)}
    assert ids == {first.draft_id, second.draft_id}


def test_select_capability_rejects_an_unknown_slot(tmp_path: Path) -> None:
    draft = start(tmp_path)
    with pytest.raises(ValueError, match="Unknown onboarding slot"):
        sdk_onboarding.select_capability(
            draft.draft_id,
            slot="not-a-real-slot",
            value={},
            root=tmp_path / "onboarding",
        )


def test_select_capability_persists_a_mapped_selection_with_its_evidence(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    updated = sdk_onboarding.select_capability(
        draft.draft_id,
        slot="compound",
        value={"compound_id": "aciclovir", "engine_molecule_id": "Aciclovir"},
        evidence_class=EvidenceClass.CURATED,
        source_record_id="OTREG-COMPOUND-abc",
        root=root,
    )
    selection = updated.selections["compound"]
    assert selection.status == sdk_onboarding.CapabilityStatus.MAPPED
    assert selection.evidence_class == EvidenceClass.CURATED
    assert selection.source_record_id == "OTREG-COMPOUND-abc"
    assert selection.value["compound_id"] == "aciclovir"


def test_build_profile_from_draft_raises_when_required_slots_are_missing(tmp_path: Path) -> None:
    draft = start(tmp_path)
    with pytest.raises(ValueError, match="missing"):
        sdk_onboarding.build_profile_from_draft(draft)


def test_build_profile_from_draft_assembles_a_real_profile_once_complete(tmp_path: Path) -> None:
    draft = start(tmp_path)
    complete = fill_all_slots(tmp_path, draft)
    profile = sdk_onboarding.build_profile_from_draft(complete)
    assert profile.package.manifest.id == "osp.fake.test"
    assert profile.compounds[0].compound_id == "aciclovir"
    assert profile.administrations[0].dose_parameter_path == "Events|IV|Dose"
    assert profile.outputs[0].unit == "mg/l"
    assert profile.package.manifest.applicability.species == ("human",)


def test_checklist_reports_every_requirement_unmet_on_a_fresh_draft(tmp_path: Path) -> None:
    draft = start(tmp_path)
    result = sdk_onboarding.checklist(draft)
    assert result["ok"] is False
    statuses = {c["requirement"]: c["status"] for c in result["checks"]}
    assert statuses["compound_identity"] == "absent"
    assert statuses["live_verification_run"] == "absent"


def test_checklist_is_satisfied_once_every_slot_and_verification_are_in_place(
    tmp_path: Path,
) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    complete = fill_all_slots(tmp_path, draft)
    complete = sdk_onboarding.set_unsupported_capabilities(complete.draft_id, items=[], root=root)
    complete = sdk_onboarding.record_verification_run(
        complete.draft_id, run_id="OTR-population-fake123", endpoint_types=("AUC",), root=root
    )
    result = sdk_onboarding.checklist(complete)
    assert result["ok"] is True, result["checks"]
    assert all(c["status"] == "verified" for c in result["checks"])


def test_record_verification_run_promotes_mapped_selections_to_verified(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    complete = fill_all_slots(tmp_path, draft)
    verified = sdk_onboarding.record_verification_run(
        complete.draft_id, run_id="OTR-population-fake123", endpoint_types=("AUC",), root=root
    )
    assert verified.verification_run_id == "OTR-population-fake123"
    assert all(
        s.status == sdk_onboarding.CapabilityStatus.VERIFIED for s in verified.selections.values()
    )


def test_checklist_reports_a_stale_verification_after_a_selection_changes(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    complete = fill_all_slots(tmp_path, draft)
    complete = sdk_onboarding.set_unsupported_capabilities(complete.draft_id, items=[], root=root)
    verified = sdk_onboarding.record_verification_run(
        complete.draft_id, run_id="OTR-population-fake123", endpoint_types=("AUC",), root=root
    )
    assert sdk_onboarding.checklist(verified)["ok"] is True

    changed = sdk_onboarding.select_capability(
        verified.draft_id,
        slot="output",
        value={
            "output_id": "plasma",
            "parameter_path": "Organism|VenousBlood|Plasma|Aciclovir|Concentration in container",
            "analyte": "aciclovir",
            "matrix": "plasma",
            "fraction": "total",
            "measurement": "concentration",
            "unit": "ug/l",  # changed unit -- profile content now differs
            "time_unit": "h",
        },
        evidence_class=EvidenceClass.ASSUMED,
        root=root,
    )
    result = sdk_onboarding.checklist(changed)
    assert result["ok"] is False
    live_check = next(c for c in result["checks"] if c["requirement"] == "live_verification_run")
    assert "stale" in live_check["detail"]


def test_register_model_raises_when_the_checklist_is_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    backend = FilesystemRegistryBackend(tmp_path / "registry")
    with pytest.raises(ValueError, match="unmet requirement"):
        sdk_onboarding.register_model(draft.draft_id, backend=backend, root=root)


def test_register_model_writes_model_and_verification_records(tmp_path: Path) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    complete = fill_all_slots(tmp_path, draft)
    complete = sdk_onboarding.set_unsupported_capabilities(complete.draft_id, items=[], root=root)
    sdk_onboarding.record_verification_run(
        complete.draft_id, run_id="OTR-population-fake123", endpoint_types=("AUC",), root=root
    )
    backend = FilesystemRegistryBackend(tmp_path / "registry")

    result = sdk_onboarding.register_model(complete.draft_id, backend=backend, root=root)

    assert result["model"].kind == RegistryRecordKind.MODEL
    assert result["model"].evidence_class == EvidenceClass.CURATED
    assert result["verification"].kind == RegistryRecordKind.MODEL_VERIFICATION
    assert result["verification"].evidence_class == EvidenceClass.SIMULATED
    # Both records verify cleanly from disk -- not just written, actually re-readable.
    backend.verify(result["model"].record_id)
    backend.verify(result["verification"].record_id)


def test_set_unsupported_capabilities_marks_reviewed_even_when_the_list_is_empty(
    tmp_path: Path,
) -> None:
    root = tmp_path / "onboarding"
    draft = start(tmp_path)
    updated = sdk_onboarding.set_unsupported_capabilities(draft.draft_id, items=[], root=root)
    assert updated.unsupported_reviewed is True
    assert updated.unsupported_capabilities == ()
