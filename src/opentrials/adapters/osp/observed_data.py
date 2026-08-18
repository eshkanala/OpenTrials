"""Read-only OSP adapter for bundled observed-data PKML ``DataSet`` files.

This is deliberately separate from ``OspSimulationEngine``: reading an
observed-data building block never touches a simulation, a population, or
the solver, and has its own tiny request/response worker contract. It exists
to give ``evidence`` connectors a way to turn an OSP-bundled observed-PK
building block into raw bytes -- nothing here decides what the data means;
that is the connector's ``normalize()`` step, deliberately kept OSP-agnostic.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT
from opentrials.core.serialization import SchemaDocument, document

OBSERVED_DATASET_WORKER_REQUEST_SCHEMA = "opentrials.osp.observed-dataset-worker-request"
OBSERVED_DATASET_WORKER_RESPONSE_SCHEMA = "opentrials.osp.observed-dataset-worker-response"
OBSERVED_DATASET_WORKER_SCHEMA_VERSION = "1.0.0"


class OspObservedDataWorkerError(RuntimeError):
    """Raised when the observed-dataset PKML worker cannot produce a valid result."""


def read_observed_dataset_pkml(
    pkml_path: Path,
    *,
    r_libs_user: str | None = None,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    worker_path: Path | None = None,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
    timeout_seconds: float = 120.0,
) -> Mapping[str, Any]:
    """Read one bundled observed-data PKML and return the worker's raw response payload.

    Returns the worker's own JSON payload unmodified (field names, units, and
    metadata exactly as ``ospsuite``'s ``DataSet`` object reports them) --
    this function performs no interpretation, matching the same
    engine-owns-its-facts discipline every other OSP adapter call in this
    project already follows.
    """
    worker = worker_path or Path(__file__).with_name("read_observed_dataset.R")
    if not rscript_path.is_file():
        raise OspObservedDataWorkerError(f"Rscript executable does not exist: {rscript_path}")
    if not worker.is_file():
        raise OspObservedDataWorkerError(f"OSP worker script does not exist: {worker}")

    request = document(
        OBSERVED_DATASET_WORKER_REQUEST_SCHEMA,
        {"pkml_path": str(pkml_path)},
        OBSERVED_DATASET_WORKER_SCHEMA_VERSION,
    )

    environment = os.environ.copy()
    environment["DOTNET_ROOT"] = dotnet_root
    if r_libs_user is not None:
        environment["R_LIBS_USER"] = r_libs_user

    with tempfile.TemporaryDirectory(prefix="opentrials-osp-observed-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        request_path = temporary_path / "request.json"
        response_path = temporary_path / "response.json"
        request_path.write_text(request.canonical_json(), encoding="utf-8")
        completed = subprocess.run(
            [
                str(rscript_path),
                str(worker),
                "--input",
                str(request_path),
                "--output",
                str(response_path),
            ],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=timeout_seconds,
        )
        if not response_path.is_file():
            raise OspObservedDataWorkerError(
                "OSP observed-dataset worker completed without writing a response artifact: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        try:
            decoded: Mapping[str, Any] = json.loads(response_path.read_text(encoding="utf-8"))
            response = SchemaDocument.model_validate(decoded)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise OspObservedDataWorkerError(
                f"OSP observed-dataset worker emitted an invalid JSON response: {error}"
            ) from error
        if response.schema_id != OBSERVED_DATASET_WORKER_RESPONSE_SCHEMA:
            raise OspObservedDataWorkerError(
                f"Unexpected observed-dataset worker response schema: {response.schema_id!r}"
            )
        if completed.returncode != 0 or response.payload.get("status") != "SUCCEEDED":
            raise OspObservedDataWorkerError(
                "OSP observed-dataset worker did not succeed: "
                f"{response.payload.get('error', completed.stderr.strip())}"
            )
        return response.payload
