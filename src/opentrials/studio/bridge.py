"""The strict, sole boundary between Studio's web layer and ``opentrials.sdk``.

This is the only module in ``opentrials.studio`` allowed to import both web
concerns (JSON-friendly dicts, HTTP-shaped errors) and the SDK/Core. It
translates between the two and contains zero scientific logic of its own --
every number here already came from a ``ProjectConfig``/``Trial`` that the
SDK validated. If a screen needs something this module cannot produce by
translation alone, that capability belongs in the SDK, not here (see
``../../../CLAUDE.md`` discipline mirrored from the CLI's own module
docstring: "no scientific logic lives here").

Editing works by round-tripping through ``ProjectConfig.model_validate``
rather than mutating the frozen models by hand: apply the requested edits to
the JSON-mode dict, then let pydantic's own validators (uniqueness, range,
allocation-sums-to-one, etc.) decide whether the result is a legal project,
exactly as they would for a hand-written YAML file.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentrials.config.project import (
    ProjectConfig,
    ProjectConfigurationError,
    dump_project,
    load_project,
)
from opentrials.config.runtime import resolve_osp_runtime
from opentrials.events import Event
from opentrials.evidence.connector import IneligibleEvidenceCandidateError, run_connector
from opentrials.reporting import render_html
from opentrials.sdk.evidence import default_evidence_connectors
from opentrials.sdk.model_onboarding import (
    generate_profile_scaffold,
    inspect_model,
)
from opentrials.sdk.project import Project
from opentrials.sdk.registry import default_model_registry
from opentrials.sdk.run import PopulationRun, TrialRun


class StudioError(ValueError):
    """A user-facing error: bad path, invalid edit, failed validation."""


def _scientific_value(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"value": value.value, "unit": value.unit}


def _project_summary(config: ProjectConfig, path: Path) -> dict[str, Any]:
    trial = config.trial
    population = trial.population

    resolved_model: dict[str, Any] | None = None
    model_error: str | None = None
    try:
        model = Project(config).model()
        resolved_model = {
            "id": model.package.manifest.id,
            "engine": model.package.manifest.engine,
            "version": model.package.manifest.version,
            "routes": sorted({a.route.value for a in model.administrations}),
        }
    except ValueError as error:
        model_error = str(error)

    arms = []
    for arm in trial.arms:
        dose = arm.intervention.regimen.doses[0]
        arms.append(
            {
                "arm_id": arm.arm_id,
                "name": arm.name,
                "allocation": arm.allocation,
                "intervention_id": arm.intervention.intervention_id,
                "compound_id": arm.intervention.compound.identity.compound_id,
                "compound": arm.intervention.compound.identity.preferred_name,
                "regimen_id": arm.intervention.regimen.regimen_id,
                "dose": _scientific_value(dose.amount),
                "route": dose.route.value,
                "administration_time": _scientific_value(dose.administration_time),
                "infusion_duration": _scientific_value(dose.infusion_duration),
            }
        )

    endpoints = [
        {
            "endpoint_id": endpoint.endpoint_id,
            "endpoint_type": endpoint.endpoint_type.value,
            "measurement": endpoint.measurement,
            "unit": endpoint.unit,
        }
        for endpoint in trial.endpoints
    ]

    return {
        "path": str(path),
        "trial_id": trial.trial_id,
        "title": trial.title,
        "question_of_interest": trial.question_of_interest,
        "model_id": config.model_id,
        "resolved_model": resolved_model,
        "model_error": model_error,
        "population": {
            "id": population.id,
            "size": population.size,
            "seed": population.seed,
            "generator_version": population.generator_version,
            "age_range": (
                {
                    "minimum": _scientific_value(population.age_range.minimum),
                    "maximum": _scientific_value(population.age_range.maximum),
                }
                if population.age_range is not None
                else None
            ),
            "sexes": [sex.value for sex in population.sexes],
        },
        "randomization": trial.randomization.value,
        "seed": trial.seed,
        "arms": arms,
        "endpoints": endpoints,
    }


def open_project(path: str) -> dict[str, Any]:
    """Load a real project YAML and return its display-ready configuration."""
    resolved_path = Path(path)
    try:
        config = load_project(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error
    return _project_summary(config, resolved_path)


def validate_project(path: str) -> dict[str, Any]:
    """Run the same SDK validation the CLI's ``validate`` command runs.

    Returns a status-ladder-shaped list of checks, matching the vocabulary
    already established for the Verification Status component (verified /
    pending / absent), not a bespoke result shape invented for this screen.
    """
    resolved_path = Path(path)
    checks: list[dict[str, str]] = []
    try:
        project = Project.load(resolved_path)
    except ProjectConfigurationError as error:
        return {
            "ok": False,
            "checks": [{"label": "Configuration", "status": "absent", "detail": str(error)}],
        }

    trial = project.trial
    checks.append({"label": "Trial", "status": "verified", "detail": trial.trial_id})

    ok = True
    try:
        model = project.model()
        checks.append(
            {
                "label": "Model",
                "status": "verified",
                "detail": model.package.manifest.id,
            }
        )
    except ValueError as error:
        checks.append({"label": "Model", "status": "absent", "detail": str(error)})
        ok = False

    checks.append(
        {
            "label": "Population",
            "status": "verified",
            "detail": f"{trial.population.id} ({trial.population.size})",
        }
    )
    checks.append(
        {"label": "Trial arms", "status": "verified", "detail": f"{len(trial.arms)} arm(s)"}
    )
    checks.append(
        {"label": "Endpoints", "status": "verified", "detail": f"{len(trial.endpoints)}"}
    )
    return {"ok": ok, "checks": checks}


def list_models() -> list[dict[str, Any]]:
    """List every model registered with the SDK's default registry."""
    registry = default_model_registry()
    models = []
    for model_id in registry.model_ids():
        profile = registry.get(model_id)
        manifest = profile.package.manifest
        models.append(
            {
                "model_id": model_id,
                "engine": manifest.engine,
                "version": manifest.version,
                "routes": sorted({a.route.value for a in profile.administrations}),
            }
        )
    return models


def save_project(
    path: str,
    edits: dict[str, Any],
) -> dict[str, Any]:
    """Apply a partial edit and save, re-validating entirely through pydantic.

    ``edits`` is shaped like a (partial) ``ProjectConfig`` JSON payload --
    e.g. ``{"trial": {"population": {"size": 25}}}`` or
    ``{"trial": {"arms": [...]}}`` with a complete replacement arms list.
    Deep-merged onto the currently-saved config (dicts merge recursively;
    any other value, including a list, replaces its current value outright
    -- an edited arms list is meant to fully replace the old one, not be
    spliced with it). The merged result is re-validated from scratch via
    ``ProjectConfig.model_validate``, so every existing invariant (range
    checks, ID uniqueness, allocations summing to one, ...) is enforced by
    the same schema a hand-written YAML file would have to satisfy -- none
    of it reimplemented here.
    """
    resolved_path = Path(path)
    try:
        config = load_project(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error

    data = config.model_dump(mode="json")
    _deep_update(data, edits)

    try:
        new_config = ProjectConfig.model_validate(data)
    except Exception as error:  # pydantic ValidationError, or any schema violation
        raise StudioError(f"Edit failed validation: {error}") from error

    resolved_path.write_text(dump_project(new_config), encoding="utf-8")
    return _project_summary(new_config, resolved_path)


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


# ================= Run + Results =================
#
# Studio must never invent progress information: every event rendered by
# the Live Execution screen is the exact same ``events.Event`` stream the
# CLI's own ``ProgressRenderer`` consumes (see ``cli/progress.py``) -- no
# separate percentage or stage vocabulary. Likewise, Results is never a
# second analysis engine: ``get_run_report_html`` returns the exact HTML
# ``opentrials report``/``run.report()`` already produce (concentration-time
# curves, endpoint summaries, arm comparisons) re-verified from the produced
# artifacts, not recomputed here. A real SDK execution is synchronous and
# can take anywhere from seconds to minutes, so it runs on a background
# thread; the frontend polls ``get_run`` for the events/status accumulated
# so far, matching the same "no invented complexity" bar as the rest of
# this module -- no websockets/SSE for a purely local, single-user tool.


@dataclass
class _RunState:
    status: str = "running"  # "running" | "completed" | "failed"
    events: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    run_directory: str | None = None
    summary: str | None = None
    verified: bool | None = None
    run_object: PopulationRun | TrialRun | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_RUNS: dict[str, _RunState] = {}


def start_run(path: str, *, output_root: str = "runs") -> dict[str, Any]:
    """Start a real SDK execution on a background thread; return a run_id to poll."""
    resolved_path = Path(path)
    try:
        project = Project.load(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error

    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Run unavailable: set R_LIBS_USER, or r_libs_user in a config file "
            "(.opentrials.yaml / ~/.config/opentrials/config.yaml), for the local "
            "ospsuite R library -- the same resolution the CLI's `run` command uses."
        )

    run_id = uuid.uuid4().hex
    state = _RunState()
    _RUNS[run_id] = state

    def on_event(event: Event) -> None:
        with state.lock:
            state.events.append(
                {
                    "stage": event.stage,
                    "status": event.status.value,
                    "timestamp": event.timestamp.isoformat(),
                }
            )

    def worker() -> None:
        try:
            run = project.run(
                output_root=Path(output_root),
                r_libs_user=runtime.r_libs_user,  # type: ignore[arg-type]  # checked above
                rscript_path=runtime.rscript_path,
                dotnet_root=runtime.dotnet_root,
                events=on_event,
            )
            verified = run.verify()
            with state.lock:
                state.status = "completed"
                state.run_directory = str(run.run_directory)
                state.summary = run.summary()
                state.verified = verified
                state.run_object = run
        except Exception as error:  # noqa: BLE001 -- a real run can fail for many real reasons
            with state.lock:
                state.status = "failed"
                state.error = str(error)

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id}


def get_run(run_id: str) -> dict[str, Any]:
    """Report the current status and every event accumulated so far."""
    state = _RUNS.get(run_id)
    if state is None:
        raise StudioError(f"Unknown run_id: {run_id!r}")
    with state.lock:
        return {
            "status": state.status,
            "events": list(state.events),
            "error": state.error,
            "run_directory": state.run_directory,
            "summary": state.summary,
            "verified": state.verified,
        }


def get_run_report_html(run_id: str) -> str:
    """Render the same self-contained HTML report ``opentrials report`` produces."""
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None:
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    return render_html(state.run_object.report())


def get_run_provenance(run_id: str) -> dict[str, Any]:
    """Return the real, re-verified provenance chain for a completed run.

    Nothing here is computed -- ``run.report()`` already re-verifies the
    whole artifact chain from disk (see ``reporting.build``) and carries
    the hashes/IDs this just reshapes into JSON. This is the same call
    ``get_run_report_html`` makes; re-verification is cheap relative to the
    run itself and re-reading from disk rather than trusting an in-memory
    cache is the same discipline every other artifact store in this project
    follows.
    """
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None:
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    data = state.run_object.report()
    return {
        "model": data.model.model_dump(mode="json"),
        "population": data.population.model_dump(mode="json"),
        "provenance": data.provenance.model_dump(mode="json"),
        "execution_verification": [
            row.model_dump(mode="json") for row in data.execution_verification
        ],
    }


# ================= Model Builder (PKML discovery + scaffold) =================
#
# ``inspect_model``/``generate_profile_scaffold`` already exist in the SDK
# (``sdk/model_onboarding.py``) and are exactly what ``opentrials model
# inspect``/``opentrials model init`` call -- this is a second client of
# that same capability, not a reimplementation. Discovery never implies
# capability verification: the generated scaffold still refuses to import
# until a researcher deletes its own guard, unchanged from the CLI path.


def inspect_pkml(pkml_path: str) -> dict[str, Any]:
    """Discover a PKML file's structure through real OSP -- read-only."""
    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Model inspection unavailable: set R_LIBS_USER, or r_libs_user in a config "
            "file, for the local ospsuite R library."
        )
    try:
        report = inspect_model(
            Path(pkml_path),
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Inspection failed: {error}") from error
    return report.model_dump(mode="json")


def create_model_scaffold(
    pkml_path: str, *, model_id: str, output_path: str | None = None
) -> dict[str, Any]:
    """Discover a PKML file, then write a reviewable ``ModelCapabilityProfile`` scaffold."""
    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Model inspection unavailable: set R_LIBS_USER, or r_libs_user in a config "
            "file, for the local ospsuite R library."
        )
    try:
        report = inspect_model(
            Path(pkml_path),
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Inspection failed: {error}") from error

    scaffold = generate_profile_scaffold(report, model_id=model_id)
    resolved_output = Path(output_path) if output_path else Path(f"{_slug(report.name)}_profile.py")
    resolved_output.write_text(scaffold, encoding="utf-8")
    return {"output_path": str(resolved_output), "scaffold": scaffold}


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


# ================= Evidence Browser =================
#
# ``sdk.evidence.default_evidence_connectors()`` composes the exact same
# connector implementations v0.8-A/B-C already built and proved -- this
# module runs them (via the generic ``evidence.connector.run_connector``,
# not a Studio-specific reimplementation) and translates the result. A
# connector legitimately declining a candidate (``IneligibleEvidenceCandidateError``,
# the real outcome for the Laskin 1982 connector -- see its own module
# docstring) is reported as a real, honest result, not hidden as an error.


def list_evidence_connectors() -> list[dict[str, Any]]:
    """List every evidence connector this project ships, by identity only (no fetch)."""
    return [
        {"connector_id": c.identity.connector_id, "version": c.identity.version}
        for c in default_evidence_connectors()
    ]


def run_evidence_connector(connector_id: str) -> dict[str, Any]:
    """Run one evidence connector's real fetch-then-normalize cycle and report the outcome."""
    runtime = resolve_osp_runtime()
    connectors = {
        c.identity.connector_id: c
        for c in default_evidence_connectors(r_libs_user=runtime.r_libs_user)
    }
    connector = connectors.get(connector_id)
    if connector is None:
        raise StudioError(f"Unknown evidence connector: {connector_id!r}")

    try:
        result = run_connector(connector)
    except IneligibleEvidenceCandidateError as error:
        return {"connector_id": connector_id, "eligible": False, "reason": str(error)}
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Evidence connector failed: {error}") from error

    dataset = result.dataset
    return {
        "connector_id": connector_id,
        "eligible": True,
        "role": dataset.role.value,
        "license": dataset.license,
        "source_identifier": dataset.source_identifier,
        "observation_count": len(dataset.observations),
        "source_url": result.source.source_url,
        "doi": result.source.doi,
        "accession": result.source.accession,
    }
