"""Read-only OSP adapter for generic PKML model discovery.

Deliberately separate from ``OspSimulationEngine`` and
``observed_data.py``: this never executes a simulation and never
interprets what it finds as a verified OpenTrials capability -- it
reports exactly what ``ospsuite`` itself can discover about a model file
(molecules, administration event containers and their parameter paths,
candidate output paths, a mutable-parameter count, a population-support
heuristic), and nothing more. Turning a discovery into a registered
``ModelCapabilityProfile`` is a separate, explicitly researcher-reviewed
step (see ``sdk.model_onboarding``).
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

MODEL_INSPECTION_WORKER_REQUEST_SCHEMA = "opentrials.osp.model-inspection-worker-request"
MODEL_INSPECTION_WORKER_RESPONSE_SCHEMA = "opentrials.osp.model-inspection-worker-response"
MODEL_INSPECTION_WORKER_SCHEMA_VERSION = "1.0.0"


class OspModelInspectionWorkerError(RuntimeError):
    """Raised when the model-inspection PKML worker cannot produce a valid result."""


def inspect_model_pkml(
    pkml_path: Path,
    *,
    r_libs_user: str | None = None,
    rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
    worker_path: Path | None = None,
    dotnet_root: str = DEFAULT_DOTNET_ROOT,
    timeout_seconds: float = 120.0,
) -> Mapping[str, Any]:
    """Ask OSP to discover a PKML file's own structure and return its raw report.

    Returns the worker's own JSON payload unmodified -- this function
    performs no interpretation or classification beyond what the worker
    itself already reports; see ``sdk.model_onboarding`` for the
    researcher-facing scaffold that turns this into something reviewable.
    """
    worker = worker_path or Path(__file__).with_name("inspect_model.R")
    if not rscript_path.is_file():
        raise OspModelInspectionWorkerError(f"Rscript executable does not exist: {rscript_path}")
    if not worker.is_file():
        raise OspModelInspectionWorkerError(f"OSP worker script does not exist: {worker}")

    request = document(
        MODEL_INSPECTION_WORKER_REQUEST_SCHEMA,
        {"pkml_path": str(pkml_path)},
        MODEL_INSPECTION_WORKER_SCHEMA_VERSION,
    )

    environment = os.environ.copy()
    environment["DOTNET_ROOT"] = dotnet_root
    if r_libs_user is not None:
        environment["R_LIBS_USER"] = r_libs_user

    with tempfile.TemporaryDirectory(prefix="opentrials-osp-inspect-") as temporary_directory:
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
            raise OspModelInspectionWorkerError(
                "OSP model-inspection worker completed without writing a response artifact: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        try:
            decoded: Mapping[str, Any] = json.loads(response_path.read_text(encoding="utf-8"))
            response = SchemaDocument.model_validate(decoded)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise OspModelInspectionWorkerError(
                f"OSP model-inspection worker emitted an invalid JSON response: {error}"
            ) from error
        if response.schema_id != MODEL_INSPECTION_WORKER_RESPONSE_SCHEMA:
            raise OspModelInspectionWorkerError(
                f"Unexpected model-inspection worker response schema: {response.schema_id!r}"
            )
        if completed.returncode != 0 or response.payload.get("status") != "SUCCEEDED":
            raise OspModelInspectionWorkerError(
                "OSP model-inspection worker did not succeed: "
                f"{response.payload.get('error', completed.stderr.strip())}"
            )
        return response.payload
