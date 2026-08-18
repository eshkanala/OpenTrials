"""Subprocess adapter for the optional, headless OSP R worker."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp.intervention import OspParameterAssignment
from opentrials.core.serialization import SchemaDocument, document
from opentrials.models.manifest import ModelType
from opentrials.models.package import ModelPackage
from opentrials.simulation.engine import (
    EngineCapabilities,
    EngineValidation,
    PreparedRun,
    RawSimulationResult,
    SimulationResult,
)
from opentrials.trials.trial import Trial

WORKER_REQUEST_SCHEMA = "opentrials.osp.worker-request"
WORKER_RESPONSE_SCHEMA = "opentrials.osp.worker-response"
WORKER_SCHEMA_VERSION = "1.0.0"
POPULATION_EXECUTION_WORKER_REQUEST_SCHEMA = "opentrials.osp.population-execution-worker-request"
POPULATION_EXECUTION_WORKER_RESPONSE_SCHEMA = "opentrials.osp.population-execution-worker-response"
POPULATION_EXECUTION_WORKER_SCHEMA_VERSION = "1.0.0"
DEFAULT_FRAMEWORK_RSCRIPT = Path("/Library/Frameworks/R.framework/Resources/bin/Rscript")
DEFAULT_DOTNET_ROOT = "/opt/homebrew/opt/dotnet@8/libexec"


class OspWorkerError(RuntimeError):
    """Raised when the isolated OSP worker cannot produce a valid result."""


class OspExecutionVerificationError(OspWorkerError):
    """A worker-blocked run retaining the solver-state verification evidence."""

    def __init__(self, message: str, verification: Mapping[str, Any] | None) -> None:
        super().__init__(message)
        self.verification = verification


class OspOutputInterval(BaseModel):
    """One evenly-spaced solver output window, verified via ``addOutputInterval``.

    ``start_time``/``end_time``/``resolution`` are already in the model's own
    time unit (minutes, for the pinned aciclovir model); converting from a
    declared ``ObservationSchedule`` is the caller's responsibility.
    ``resolution`` is OSP's own convention: points per unit time, i.e.
    ``1 / interval``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_time: float = Field(ge=0)
    end_time: float
    resolution: float = Field(gt=0)
    interval_name: str = Field(min_length=1)


def _file_uri_to_path(artifact_uri: str) -> Path:
    parsed = urlparse(artifact_uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError("The v0.1 OSP adapter requires an absolute file:// PKML artifact URI.")
    path = Path(unquote(parsed.path))
    if not path.is_absolute() or path.suffix.lower() != ".pkml":
        raise ValueError("The v0.1 OSP adapter requires an absolute .pkml artifact path.")
    return path


class OspSimulationEngine:
    """Execute one immutable local PKML through an isolated R/ospsuite worker.

    This first adapter deliberately does not translate an OpenTrials intervention,
    create OSP populations, or normalize PK outputs. It only executes the model
    package's existing PKML for one individual and returns engine-owned raw rows.
    """

    engine_id = "osp"

    def __init__(
        self,
        *,
        rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
        worker_path: Path | None = None,
        population_worker_path: Path | None = None,
        dotnet_root: str = DEFAULT_DOTNET_ROOT,
        r_libs_user: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._rscript_path = rscript_path
        self._worker_path = worker_path or Path(__file__).with_name("run_simulation.R")
        self._population_worker_path = population_worker_path or Path(__file__).with_name(
            "run_population_simulation.R"
        )
        self._dotnet_root = dotnet_root
        self._r_libs_user = r_libs_user
        self._timeout_seconds = timeout_seconds

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            engine_id=self.engine_id,
            supported_model_types=(ModelType.PBPK,),
            supports_population_simulation=False,
            supports_parallel_execution=False,
        )

    def validate(self, packages: tuple[ModelPackage, ...], trial: Trial) -> EngineValidation:
        errors: list[str] = []
        warnings: list[str] = []
        if len(packages) != 1:
            errors.append("The v0.1 OSP adapter requires exactly one model package.")
        if trial.population.size != 1:
            errors.append("The v0.1 OSP adapter currently supports exactly one individual.")
        if packages:
            package = packages[0]
            if package.manifest.engine != self.engine_id:
                errors.append("The model package engine must be 'osp'.")
            if package.manifest.model_type is not ModelType.PBPK:
                errors.append("The v0.1 OSP adapter supports PBPK model packages only.")
            try:
                path = _file_uri_to_path(package.artifact_uri)
            except ValueError as error:
                errors.append(str(error))
            else:
                if not path.is_file():
                    errors.append(f"PKML artifact does not exist: {path}")
        if not errors:
            warnings.append(
                "The existing PKML is executed unchanged; OpenTrials regimen translation "
                "is not yet implemented."
            )
        return EngineValidation(is_valid=not errors, errors=tuple(errors), warnings=tuple(warnings))

    def prepare(self, run_id: str, packages: tuple[ModelPackage, ...], trial: Trial) -> PreparedRun:
        validation = self.validate(packages, trial)
        if not validation.is_valid:
            raise ValueError("Cannot prepare an invalid OSP run: " + "; ".join(validation.errors))
        return PreparedRun(run_id=run_id, trial=trial, model_packages=packages, seed=trial.seed)

    def run(
        self,
        prepared_run: PreparedRun,
        *,
        expected_pkml_sha256: str | None = None,
        expected_administration_container: str | None = None,
        parameter_assignments: tuple[OspParameterAssignment, ...] = (),
    ) -> RawSimulationResult:
        """Run unchanged PKML or a worker-verified, explicit assignment plan."""
        package = prepared_run.model_packages[0]
        pkml_path = _file_uri_to_path(package.artifact_uri)
        payload: dict[str, Any] = {"run_id": prepared_run.run_id, "pkml_path": str(pkml_path)}
        if parameter_assignments:
            if expected_pkml_sha256 is None or expected_administration_container is None:
                raise ValueError(
                    "Verified assignments require expected PKML hash and administration container."
                )
            payload.update(
                {
                    "expected_pkml_sha256": expected_pkml_sha256.removeprefix("sha256:"),
                    "expected_administration_container": expected_administration_container,
                    "parameter_assignments": [
                        {
                            "path": assignment.parameter_path,
                            "value": assignment.value,
                            "unit": assignment.unit,
                            "source_field": assignment.source_field,
                        }
                        for assignment in parameter_assignments
                    ],
                }
            )
        request = document(WORKER_REQUEST_SCHEMA, payload, WORKER_SCHEMA_VERSION)

        with tempfile.TemporaryDirectory(prefix="opentrials-osp-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            request_path = temporary_path / "request.json"
            response_path = temporary_path / "response.json"
            request_path.write_text(request.canonical_json(), encoding="utf-8")
            completed = self._invoke_worker(self._worker_path, request_path, response_path)
            if not response_path.is_file():
                raise OspWorkerError("OSP worker completed without writing a response artifact.")
            response = self._read_response(
                response_path,
                expected_schema=WORKER_RESPONSE_SCHEMA,
                expected_schema_version=WORKER_SCHEMA_VERSION,
            )
            if completed.returncode != 0:
                worker_message = completed.stderr.strip() or completed.stdout.strip()
                verification = response.payload.get("execution_verification")
                if isinstance(verification, dict):
                    raise OspExecutionVerificationError(
                        "OSP execution verification blocked the solver: "
                        f"{response.payload.get('error')}",
                        verification,
                    )
                raise OspWorkerError(
                    f"OSP worker failed with exit code {completed.returncode}: {worker_message}"
                )

        payload = response.payload
        if payload.get("status") != "SUCCEEDED":
            raise OspWorkerError(f"OSP worker returned an unsuccessful response: {payload!r}")
        if payload.get("run_id") != prepared_run.run_id:
            raise OspWorkerError("OSP worker response run ID does not match the submitted run.")
        generated_at = _parse_generated_at(payload.get("generated_at"))
        return RawSimulationResult(
            run_id=prepared_run.run_id,
            engine_id=self.engine_id,
            generated_at=generated_at,
            payload=payload,
        )

    def run_population(
        self,
        prepared_run: PreparedRun,
        *,
        population_columns: tuple[str, ...],
        population_rows: tuple[Mapping[str, Any], ...],
        expected_population_count: int,
        expected_pkml_sha256: str,
        expected_administration_container: str | None = None,
        parameter_assignments: tuple[OspParameterAssignment, ...] = (),
        output_intervals: tuple[OspOutputInterval, ...] = (),
    ) -> RawSimulationResult:
        """Reconstruct a verified population and batch-run it through PBPK.

        ``population_columns``/``population_rows`` must be the exact table
        already verified against a persisted ``OTPGEN`` artifact by the
        caller; this adapter performs no population generation or trust
        decision of its own. The PKML hash is always required here (unlike
        the single-individual ``run()``): population execution is always
        hash-pinned. ``output_intervals``, when supplied, declares the
        solver's output time grid explicitly (verified via
        ``addOutputInterval`` -- see HANDOFF v0.5-B); when empty (the
        default), the solver's own default dense grid is used unchanged,
        exactly as before this parameter existed.
        """
        package = prepared_run.model_packages[0]
        pkml_path = _file_uri_to_path(package.artifact_uri)
        if expected_population_count != len(population_rows):
            raise ValueError("expected_population_count does not match the supplied row count.")
        payload: dict[str, Any] = {
            "run_id": prepared_run.run_id,
            "pkml_path": str(pkml_path),
            "expected_pkml_sha256": expected_pkml_sha256.removeprefix("sha256:"),
            "population_columns": list(population_columns),
            "population_rows": [dict(row) for row in population_rows],
            "expected_population_count": expected_population_count,
        }
        if output_intervals:
            payload["output_intervals"] = [
                {
                    "start_time": interval.start_time,
                    "end_time": interval.end_time,
                    "resolution": interval.resolution,
                    "interval_name": interval.interval_name,
                }
                for interval in output_intervals
            ]
        if parameter_assignments:
            if expected_administration_container is None:
                raise ValueError("Verified assignments require an administration container.")
            payload.update(
                {
                    "expected_administration_container": expected_administration_container,
                    "parameter_assignments": [
                        {
                            "path": assignment.parameter_path,
                            "value": assignment.value,
                            "unit": assignment.unit,
                            "source_field": assignment.source_field,
                        }
                        for assignment in parameter_assignments
                    ],
                }
            )
        request = document(
            POPULATION_EXECUTION_WORKER_REQUEST_SCHEMA,
            payload,
            POPULATION_EXECUTION_WORKER_SCHEMA_VERSION,
        )

        with tempfile.TemporaryDirectory(
            prefix="opentrials-osp-population-"
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            request_path = temporary_path / "request.json"
            response_path = temporary_path / "response.json"
            request_path.write_text(request.canonical_json(), encoding="utf-8")
            completed = self._invoke_worker(
                self._population_worker_path, request_path, response_path
            )
            if not response_path.is_file():
                raise OspWorkerError(
                    "OSP population worker completed without writing a response artifact."
                )
            response = self._read_response(
                response_path,
                expected_schema=POPULATION_EXECUTION_WORKER_RESPONSE_SCHEMA,
                expected_schema_version=POPULATION_EXECUTION_WORKER_SCHEMA_VERSION,
            )
            if completed.returncode != 0:
                worker_message = completed.stderr.strip() or completed.stdout.strip()
                verification = response.payload.get("execution_verification")
                if isinstance(verification, dict):
                    raise OspExecutionVerificationError(
                        "OSP population execution verification blocked the solver: "
                        f"{response.payload.get('error')}",
                        verification,
                    )
                raise OspWorkerError(
                    f"OSP population worker failed with exit code {completed.returncode}: "
                    f"{worker_message}"
                )

        payload = response.payload
        if payload.get("status") != "SUCCEEDED":
            raise OspWorkerError(f"OSP population worker returned a failed response: {payload!r}")
        if payload.get("run_id") != prepared_run.run_id:
            raise OspWorkerError(
                "OSP population worker response run ID does not match the submitted run."
            )
        generated_at = _parse_generated_at(payload.get("generated_at"))
        return RawSimulationResult(
            run_id=prepared_run.run_id,
            engine_id=self.engine_id,
            generated_at=generated_at,
            payload=payload,
        )

    def extract(self, raw_result: RawSimulationResult) -> SimulationResult:
        if raw_result.engine_id != self.engine_id:
            raise ValueError("OSP adapter cannot extract a result from another engine.")
        return SimulationResult(
            run_id=raw_result.run_id,
            engine_id=self.engine_id,
            generated_at=raw_result.generated_at,
            warnings=(
                "Raw OSP rows are available in the engine result; PK result normalization "
                "is pending.",
            ),
        )

    def version_info(self) -> dict[str, str]:
        return {
            "engine": self.engine_id,
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "rscript_path": str(self._rscript_path),
        }

    def _invoke_worker(
        self, worker_path: Path, request_path: Path, response_path: Path
    ) -> subprocess.CompletedProcess[str]:
        if not self._rscript_path.is_file():
            raise OspWorkerError(f"Rscript executable does not exist: {self._rscript_path}")
        if not worker_path.is_file():
            raise OspWorkerError(f"OSP worker script does not exist: {worker_path}")
        environment = os.environ.copy()
        environment["DOTNET_ROOT"] = self._dotnet_root
        if self._r_libs_user is not None:
            environment["R_LIBS_USER"] = self._r_libs_user
        return subprocess.run(
            [
                str(self._rscript_path),
                str(worker_path),
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
    def _read_response(
        response_path: Path, *, expected_schema: str, expected_schema_version: str
    ) -> SchemaDocument:
        try:
            decoded: Mapping[str, Any] = json.loads(response_path.read_text(encoding="utf-8"))
            response = SchemaDocument.model_validate(decoded)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise OspWorkerError(f"OSP worker emitted an invalid JSON response: {error}") from error
        if response.schema_id != expected_schema:
            raise OspWorkerError(f"Unexpected OSP worker response schema: {response.schema_id!r}")
        if response.schema_version != expected_schema_version:
            raise OspWorkerError(
                f"Unsupported OSP worker response version: {response.schema_version!r}"
            )
        return response


def _parse_generated_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise OspWorkerError("OSP worker response is missing an ISO-8601 generated_at timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise OspWorkerError("OSP worker generated_at is not an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise OspWorkerError("OSP worker generated_at must include a timezone.")
    return parsed.astimezone(UTC)
