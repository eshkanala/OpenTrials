"""OpenTrials Studio's FastAPI routes.

Deliberately thin, the same rule the CLI documents for itself: parse the
request, call ``bridge``, return the result. No scientific logic here --
see ``bridge.py``'s module docstring for where that boundary lives and why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from opentrials.studio import bridge

STATIC_ROOT = Path(__file__).parent / "static"

app = FastAPI(title="OpenTrials Studio")
app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")


class SaveRequest(BaseModel):
    path: str
    edits: dict[str, Any]


class RunRequest(BaseModel):
    path: str
    output_root: str = "runs"


class InspectRequest(BaseModel):
    pkml_path: str


class ScaffoldRequest(BaseModel):
    pkml_path: str
    model_id: str
    output_path: str | None = None


class AttachEvidenceRequest(BaseModel):
    path: str


class PhysiologyStateRequest(BaseModel):
    state_id: str
    target: str
    scale_factor: float
    unit: str
    purpose: str


class PhysiologyRunRequest(BaseModel):
    path: str
    states: list[PhysiologyStateRequest]
    baseline_state_id: str
    output_root: str = "runs"


class CohortDefinitionRequest(BaseModel):
    label: str
    predicates: list[dict[str, Any]]


class DefineCohortsRequest(BaseModel):
    cohorts: list[CohortDefinitionRequest]


class CompareCohortsRequest(BaseModel):
    group_a_membership_id: str
    group_b_membership_id: str
    group_a_label: str
    group_b_label: str


class RegisterExperimentRequest(BaseModel):
    title: str
    summary: str | None = None
    license: str


class ForkExperimentRequest(BaseModel):
    output_path: str


class StartDraftRequest(BaseModel):
    pkml_path: str
    model_id: str


class DraftMetadataRequest(BaseModel):
    model_version: str
    license: str


class SelectCapabilityRequest(BaseModel):
    slot: str
    value: dict[str, Any]
    source_record_id: str | None = None
    evidence_class: str | None = None
    unit: str | None = None
    context: str | None = None
    provenance_ids: tuple[str, ...] = ()


class UnsupportedCapabilitiesRequest(BaseModel):
    items: list[dict[str, str]]


class DraftVerificationRunRequest(BaseModel):
    path: str
    output_root: str = "runs"


class RecordVerificationRequest(BaseModel):
    run_id: str


class RunConnectorForCurationRequest(BaseModel):
    connector_id: str


class SetCandidateIdentityRequest(BaseModel):
    logical_id: str
    evidence_class: str


class SetCandidateCompatibilityRequest(BaseModel):
    model_ids: tuple[str, ...] = ()
    route: str | None = None
    species: tuple[str, ...] = ()
    notes: str | None = None


class RejectCandidateRequest(BaseModel):
    reason: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/project")
def get_project(path: str) -> dict[str, Any]:
    try:
        return bridge.open_project(path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/project/export")
def get_project_export(path: str) -> PlainTextResponse:
    try:
        yaml_text = bridge.export_project_yaml(path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return PlainTextResponse(
        yaml_text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="project.yaml"'},
    )


@app.post("/api/project/validate")
def post_validate(path: str) -> dict[str, Any]:
    return bridge.validate_project(path)


@app.post("/api/project/save")
def post_save(request: SaveRequest) -> dict[str, Any]:
    try:
        return bridge.save_project(request.path, request.edits)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/models")
def get_models() -> list[dict[str, Any]]:
    return bridge.list_models()


@app.post("/api/run")
def post_run(request: RunRequest) -> dict[str, Any]:
    try:
        return bridge.start_run(request.path, output_root=request.output_root)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/run/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return bridge.get_run(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/run/{run_id}/report.html", response_class=HTMLResponse)
def get_run_report(run_id: str) -> str:
    try:
        return bridge.get_run_report_html(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/run/{run_id}/report.md")
def get_run_report_markdown(run_id: str) -> PlainTextResponse:
    try:
        markdown = bridge.get_run_report_markdown(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="report.md"'},
    )


@app.get("/api/run/{run_id}/provenance")
def get_run_provenance(run_id: str) -> dict[str, Any]:
    try:
        return bridge.get_run_provenance(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/model/inspect")
def post_model_inspect(request: InspectRequest) -> dict[str, Any]:
    try:
        return bridge.inspect_pkml(request.pkml_path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/model/scaffold")
def post_model_scaffold(request: ScaffoldRequest) -> dict[str, Any]:
    try:
        return bridge.create_model_scaffold(
            request.pkml_path, model_id=request.model_id, output_path=request.output_path
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/registry/matches/{compound_id}")
def get_registry_matches(compound_id: str) -> dict[str, Any]:
    try:
        return bridge.get_registry_matches_for_compound(compound_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/evidence")
def get_evidence_connectors() -> list[dict[str, Any]]:
    return bridge.list_evidence_connectors()


@app.post("/api/evidence/{connector_id}/run")
def post_evidence_run(connector_id: str) -> dict[str, Any]:
    try:
        return bridge.run_evidence_connector(connector_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/evidence/{connector_id}/attach")
def post_evidence_attach(connector_id: str, request: AttachEvidenceRequest) -> dict[str, Any]:
    try:
        return bridge.attach_evidence_to_project(request.path, connector_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/runs")
def get_runs(output_root: str = "runs") -> list[dict[str, Any]]:
    return bridge.list_runs(output_root)


@app.get("/api/runs/report.html", response_class=HTMLResponse)
def get_historical_run_report(run_directory: str, population_root: str | None = None) -> str:
    try:
        return bridge.get_historical_run_report_html(
            run_directory, population_root=population_root
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/runs/report.md")
def get_historical_run_report_markdown(
    run_directory: str, population_root: str | None = None
) -> PlainTextResponse:
    try:
        markdown = bridge.get_historical_run_report_markdown(
            run_directory, population_root=population_root
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="report.md"'},
    )


@app.get("/api/runs/data")
def get_historical_run_data(
    run_directory: str, population_root: str | None = None
) -> dict[str, Any]:
    try:
        return bridge.get_historical_run_result_data(
            run_directory, population_root=population_root
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/run/{run_id}/data")
def get_run_data(run_id: str) -> dict[str, Any]:
    try:
        return bridge.get_run_result_data(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/physiology/targets")
def get_physiology_targets(path: str) -> list[dict[str, Any]]:
    try:
        return bridge.list_physiology_targets(path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/physiology/run")
def post_physiology_run(request: PhysiologyRunRequest) -> dict[str, Any]:
    try:
        return bridge.start_physiology_run(
            request.path,
            states=[s.model_dump() for s in request.states],
            baseline_state_id=request.baseline_state_id,
            output_root=request.output_root,
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/physiology/run/{run_id}")
def get_physiology_run(run_id: str) -> dict[str, Any]:
    try:
        return bridge.get_physiology_run(run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/cohort/fields")
def get_cohort_fields() -> list[dict[str, Any]]:
    return bridge.list_cohort_fields()


@app.post("/api/run/{run_id}/cohorts")
def post_define_cohorts(run_id: str, request: DefineCohortsRequest) -> dict[str, Any]:
    try:
        return bridge.define_cohorts_for_run(
            run_id, [c.model_dump() for c in request.cohorts]
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/run/{run_id}/cohorts/compare")
def post_compare_cohorts(run_id: str, request: CompareCohortsRequest) -> dict[str, Any]:
    try:
        return bridge.compare_cohorts_for_run(
            run_id,
            group_a_membership_id=request.group_a_membership_id,
            group_b_membership_id=request.group_b_membership_id,
            group_a_label=request.group_a_label,
            group_b_label=request.group_b_label,
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/registry")
def get_registry_records(kind: str | None = None) -> list[dict[str, Any]]:
    return bridge.list_registry_records(kind)


@app.get("/api/registry/{logical_id}")
def get_registry_record(logical_id: str) -> dict[str, Any]:
    try:
        return bridge.get_registry_record(logical_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/run/{run_id}/register-experiment")
def post_register_experiment(run_id: str, request: RegisterExperimentRequest) -> dict[str, Any]:
    try:
        return bridge.register_run_as_experiment(
            run_id, title=request.title, summary=request.summary, license=request.license
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/registry/{logical_id}/fork")
def post_fork_experiment(logical_id: str, request: ForkExperimentRequest) -> dict[str, Any]:
    try:
        return bridge.fork_experiment(logical_id, output_path=request.output_path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# ================= Guided Model Onboarding (Studio v0.4) =================


@app.post("/api/onboarding/draft")
def post_start_draft(request: StartDraftRequest) -> dict[str, Any]:
    try:
        return bridge.start_model_draft(request.pkml_path, model_id=request.model_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/onboarding/drafts")
def get_drafts() -> list[dict[str, Any]]:
    return bridge.list_model_drafts()


@app.get("/api/onboarding/draft/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    try:
        return bridge.get_model_draft(draft_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/metadata")
def post_draft_metadata(draft_id: str, request: DraftMetadataRequest) -> dict[str, Any]:
    try:
        return bridge.set_model_draft_metadata(
            draft_id, model_version=request.model_version, license=request.license
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/select")
def post_draft_select(draft_id: str, request: SelectCapabilityRequest) -> dict[str, Any]:
    try:
        return bridge.select_model_draft_capability(
            draft_id,
            slot=request.slot,
            value=request.value,
            source_record_id=request.source_record_id,
            evidence_class=request.evidence_class,
            unit=request.unit,
            context=request.context,
            provenance_ids=request.provenance_ids,
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/unsupported")
def post_draft_unsupported(
    draft_id: str, request: UnsupportedCapabilitiesRequest
) -> dict[str, Any]:
    try:
        return bridge.set_model_draft_unsupported_capabilities(draft_id, items=request.items)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/onboarding/draft/{draft_id}/checklist")
def get_draft_checklist(draft_id: str) -> dict[str, Any]:
    try:
        return bridge.get_model_draft_checklist(draft_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/verify")
def post_draft_verify(draft_id: str, request: DraftVerificationRunRequest) -> dict[str, Any]:
    try:
        return bridge.start_model_draft_verification_run(
            draft_id, path=request.path, output_root=request.output_root
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/verify/record")
def post_draft_verify_record(draft_id: str, request: RecordVerificationRequest) -> dict[str, Any]:
    try:
        return bridge.record_model_draft_verification(draft_id, run_id=request.run_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/onboarding/draft/{draft_id}/register")
def post_draft_register(draft_id: str) -> dict[str, Any]:
    try:
        return bridge.register_model_from_draft(draft_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# ================= Registry Curation Pipeline =================


@app.post("/api/curation/run")
def post_curation_run(request: RunConnectorForCurationRequest) -> dict[str, Any]:
    try:
        return bridge.run_connector_for_curation(request.connector_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/curation/candidates")
def get_curation_candidates() -> list[dict[str, Any]]:
    return bridge.list_curation_candidates()


@app.get("/api/curation/ineligible")
def get_curation_ineligible() -> list[dict[str, Any]]:
    return bridge.list_ineligible_curation_candidates()


@app.get("/api/curation/candidate/{candidate_id}")
def get_curation_candidate(candidate_id: str) -> dict[str, Any]:
    try:
        return bridge.get_curation_candidate(candidate_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/identity")
def post_curation_identity(
    candidate_id: str, request: SetCandidateIdentityRequest
) -> dict[str, Any]:
    try:
        return bridge.set_curation_candidate_identity(
            candidate_id, logical_id=request.logical_id, evidence_class=request.evidence_class
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/compatibility")
def post_curation_compatibility(
    candidate_id: str, request: SetCandidateCompatibilityRequest
) -> dict[str, Any]:
    try:
        return bridge.set_curation_candidate_compatibility(
            candidate_id,
            model_ids=request.model_ids,
            route=request.route,
            species=request.species,
            notes=request.notes,
        )
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/license-reviewed")
def post_curation_license_reviewed(candidate_id: str) -> dict[str, Any]:
    try:
        return bridge.mark_curation_license_reviewed(candidate_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/acknowledge-identity")
def post_curation_acknowledge_identity(candidate_id: str) -> dict[str, Any]:
    try:
        return bridge.acknowledge_curation_identity(candidate_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/curation/candidate/{candidate_id}/checklist")
def get_curation_checklist(candidate_id: str) -> dict[str, Any]:
    try:
        return bridge.get_curation_checklist(candidate_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/accept")
def post_curation_accept(candidate_id: str) -> dict[str, Any]:
    try:
        return bridge.accept_curation_candidate(candidate_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/curation/candidate/{candidate_id}/reject")
def post_curation_reject(candidate_id: str, request: RejectCandidateRequest) -> dict[str, Any]:
    try:
        return bridge.reject_curation_candidate(candidate_id, reason=request.reason)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
