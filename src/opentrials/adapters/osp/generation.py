"""Subprocess boundary for raw OSP population generation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp.engine import (
    DEFAULT_DOTNET_ROOT,
    DEFAULT_FRAMEWORK_RSCRIPT,
    OspWorkerError,
)
from opentrials.adapters.osp.population import (
    OspDeterminismLevel,
    OspPopulationTranslation,
)
from opentrials.core.serialization import SchemaDocument, document

POPULATION_WORKER_REQUEST_SCHEMA = "opentrials.osp.population-worker-request"
POPULATION_WORKER_RESPONSE_SCHEMA = "opentrials.osp.population-worker-response"
POPULATION_WORKER_SCHEMA_VERSION = "1.0.0"


class OspPopulationGenerationResult(BaseModel):
    """Raw OSP-generated population table and reproducibility metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["SUCCEEDED"]
    population_id: str = Field(min_length=1)
    requested_seed: int
    engine_seed: int | None = None
    determinism_level: OspDeterminismLevel
    r_version: str = Field(min_length=1)
    ospsuite_version: str = Field(min_length=1)
    column_names: tuple[str, ...] = Field(min_length=1)
    raw_rows: tuple[dict[str, Any], ...] = Field(min_length=1)


class OspPopulationGenerator:
    """Generate raw OSP populations through a versioned JSON worker contract.

    The generator accepts only a fully mapped translation. It does not persist
    large artifacts, materialize OpenTrials ``Population`` objects, or run PBPK
    simulations; those responsibilities remain separate B3 milestones.
    """

    def __init__(
        self,
        *,
        rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
        worker_path: Path | None = None,
        dotnet_root: str = DEFAULT_DOTNET_ROOT,
        r_libs_user: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._rscript_path = rscript_path
        self._worker_path = worker_path or Path(__file__).with_name("generate_population.R")
        self._dotnet_root = dotnet_root
        self._r_libs_user = r_libs_user
        self._timeout_seconds = timeout_seconds

    def generate(self, translation: OspPopulationTranslation) -> OspPopulationGenerationResult:
        if translation.report.unsupported:
            raise ValueError(
                "Cannot generate an OSP population with unsupported translated features."
            )
        if translation.report.defaulted:
            raise ValueError("Cannot generate an OSP population with unverified OSP defaults.")
        request = document(
            POPULATION_WORKER_REQUEST_SCHEMA,
            translation.request,
            POPULATION_WORKER_SCHEMA_VERSION,
        )
        with tempfile.TemporaryDirectory(
            prefix="opentrials-osp-population-"
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            request_path = temporary_path / "request.json"
            response_path = temporary_path / "response.json"
            request_path.write_text(request.canonical_json(), encoding="utf-8")
            completed = self._invoke_worker(request_path, response_path)
            if completed.returncode != 0:
                worker_message = completed.stderr.strip() or completed.stdout.strip()
                raise OspWorkerError(
                    "OSP population worker failed with exit code "
                    f"{completed.returncode}: {worker_message}"
                )
            if not response_path.is_file():
                raise OspWorkerError(
                    "OSP population worker succeeded without writing a response artifact."
                )
            response = self._read_response(response_path)

        payload = response.payload
        if payload.get("status") != "SUCCEEDED":
            raise OspWorkerError(
                f"OSP population worker returned an unsuccessful response: {payload!r}"
            )
        if payload.get("population_id") != translation.request.population_id:
            raise OspWorkerError(
                "OSP population worker response ID does not match the submitted request."
            )
        try:
            result = OspPopulationGenerationResult.model_validate(payload)
        except ValueError as error:
            raise OspWorkerError(f"OSP population worker payload is invalid: {error}") from error
        if len(result.raw_rows) != translation.request.number_of_individuals:
            raise OspWorkerError("OSP population worker returned an unexpected individual count.")
        return result

    def _invoke_worker(
        self, request_path: Path, response_path: Path
    ) -> subprocess.CompletedProcess[str]:
        if not self._rscript_path.is_file():
            raise OspWorkerError(f"Rscript executable does not exist: {self._rscript_path}")
        if not self._worker_path.is_file():
            raise OspWorkerError(
                f"OSP population worker script does not exist: {self._worker_path}"
            )
        environment = os.environ.copy()
        environment["DOTNET_ROOT"] = self._dotnet_root
        if self._r_libs_user is not None:
            environment["R_LIBS_USER"] = self._r_libs_user
        return subprocess.run(
            [
                str(self._rscript_path),
                str(self._worker_path),
                "--input",
                str(request_path),
                "--output",
                str(response_path),
            ],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=self._timeout_seconds,
        )

    @staticmethod
    def _read_response(response_path: Path) -> SchemaDocument:
        try:
            decoded: Mapping[str, Any] = json.loads(response_path.read_text(encoding="utf-8"))
            response = SchemaDocument.model_validate(decoded)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise OspWorkerError(
                f"OSP population worker emitted an invalid JSON response: {error}"
            ) from error
        if response.schema_id != POPULATION_WORKER_RESPONSE_SCHEMA:
            raise OspWorkerError(
                f"Unexpected OSP population worker response schema: {response.schema_id!r}"
            )
        if response.schema_version != POPULATION_WORKER_SCHEMA_VERSION:
            raise OspWorkerError(
                f"Unsupported OSP population worker response version: {response.schema_version!r}"
            )
        return response
