"""OpenTrials Studio's FastAPI routes.

Deliberately thin, the same rule the CLI documents for itself: parse the
request, call ``bridge``, return the result. No scientific logic here --
see ``bridge.py``'s module docstring for where that boundary lives and why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/project")
def get_project(path: str) -> dict[str, Any]:
    try:
        return bridge.open_project(path)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get("/api/evidence")
def get_evidence_connectors() -> list[dict[str, Any]]:
    return bridge.list_evidence_connectors()


@app.post("/api/evidence/{connector_id}/run")
def post_evidence_run(connector_id: str) -> dict[str, Any]:
    try:
        return bridge.run_evidence_connector(connector_id)
    except bridge.StudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
