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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentrials.adapters.osp import osp_population_field_catalog
from opentrials.cohort.definitions import (
    CategoricalPredicate,
    NumericOperator,
    NumericPredicate,
    Predicate,
    PresencePredicate,
)
from opentrials.config.project import (
    ProjectConfig,
    ProjectConfigurationError,
    dump_project,
    load_project,
)
from opentrials.config.runtime import resolve_osp_runtime
from opentrials.core.serialization import sha256
from opentrials.events import Event
from opentrials.evidence.connector import IneligibleEvidenceCandidateError, run_connector
from opentrials.models.registry import DuplicateModelCapabilityError, ModelCapabilityRegistry
from opentrials.orchestration.physiology_trial_execution import PhysiologyStateDeclaration
from opentrials.physiology.overrides import PhysiologicalStateOverride
from opentrials.registry import (
    EvidenceClass,
    ExperimentRecord,
    RegistryCompatibility,
    RegistryError,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.reporting import (
    build_population_report,
    build_trial_report,
    render_html,
    render_markdown,
)
from opentrials.reporting.data import ReportData
from opentrials.sdk import curation as sdk_curation
from opentrials.sdk import onboarding as sdk_onboarding
from opentrials.sdk.cohort import compare_cohorts, define_and_persist_cohort
from opentrials.sdk.evidence import default_evidence_connectors, ingest_and_persist
from opentrials.sdk.model_onboarding import (
    generate_profile_scaffold,
    inspect_model,
)
from opentrials.sdk.physiology import run_trial_physiology_states, verify_physiology_states
from opentrials.sdk.project import Project, dose_mg_for_model
from opentrials.sdk.registry import default_model_registry, default_registry_backend
from opentrials.sdk.registry_match import (
    match_compound,
    match_datasets_for_compound,
    match_parameter_evidence,
    match_summary,
)
from opentrials.sdk.run import PopulationRun, TrialRun
from opentrials.trials.trial import Trial


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
            "physiology_targets": [t.target for t in model.physiology_targets],
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
            "time_window": {
                "start": _scientific_value(endpoint.time_window.start),
                "end": _scientific_value(endpoint.time_window.end),
            },
            "aggregation": endpoint.aggregation.value,
            "missingness_rule": endpoint.missingness_rule.value,
            "analysis_method": endpoint.analysis_method,
            "unit": endpoint.unit,
        }
        for endpoint in trial.endpoints
    ]

    def _criterion(criterion: Any) -> dict[str, Any]:
        value = criterion.value
        value_kind: str
        value_repr: Any
        if isinstance(value, tuple):
            value_kind, value_repr = "list", list(value)
        elif hasattr(value, "value") and hasattr(value, "unit"):
            value_kind, value_repr = "scientific", _scientific_value(value)
        elif value is None:
            value_kind, value_repr = "none", None
        else:
            value_kind, value_repr = "plain", value
        return {
            "criterion_id": criterion.criterion_id,
            "field_path": criterion.field_path,
            "operator": criterion.operator.value,
            "value_kind": value_kind,
            "value": value_repr,
            "description": criterion.description,
        }

    eligibility = {
        "inclusion": [_criterion(c) for c in trial.eligibility.inclusion],
        "exclusion": [_criterion(c) for c in trial.eligibility.exclusion],
        "narrative": trial.eligibility.narrative,
    }

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
        "eligibility": eligibility,
        "evidence_ids": list(trial.evidence_ids),
        "observation_schedule": (
            {
                "schedule_id": trial.observation_schedule.schedule_id,
                "time_unit": trial.observation_schedule.time_unit,
                "windows": [
                    {
                        "start": _scientific_value(w.start),
                        "end": _scientific_value(w.end),
                        "interval": _scientific_value(w.interval),
                    }
                    for w in trial.observation_schedule.windows
                ],
            }
            if trial.observation_schedule is not None
            else None
        ),
    }


def open_project(path: str) -> dict[str, Any]:
    """Load a real project YAML and return its display-ready configuration."""
    resolved_path = Path(path)
    try:
        config = load_project(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error
    return _project_summary(config, resolved_path)


def export_project_yaml(path: str) -> str:
    """Return the canonical ``opentrials.project`` YAML for a real project.

    Re-derived through ``load_project``/``dump_project`` (load then dump,
    not a raw file read) so an export always reflects the same canonical
    schema envelope every other save produces, even if the file on disk
    still carries hand-written comments or formatting.
    """
    resolved_path = Path(path)
    try:
        config = load_project(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error
    return dump_project(config)


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
    trial: Trial | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_RUNS: dict[str, _RunState] = {}


def start_run(
    path: str, *, output_root: str = "runs", registry: ModelCapabilityRegistry | None = None
) -> dict[str, Any]:
    """Start a real SDK execution on a background thread; return a run_id to poll.

    ``registry`` defaults to the SDK's normal default registry; guided
    onboarding's verification-run step passes a registry containing only
    an in-progress draft profile instead, so a not-yet-registered model
    can still be executed for real without special-casing execution
    itself around onboarding.
    """
    resolved_path = Path(path)
    try:
        project = Project.load(resolved_path, registry=registry)
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
    state = _RunState(trial=project.trial)
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


def get_run_report_markdown(run_id: str) -> str:
    """Render the same Markdown report ``opentrials report --format markdown`` produces."""
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None:
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    return render_markdown(state.run_object.report())


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


# ================= Physiology-state trials =================
#
# A separate execution mode from Run/Results: a physiology-state trial
# always executes the *whole* declared population at every state (states
# are not a partition, unlike trial arms -- see ``sdk.physiology``'s own
# docstring), so it is not a variant of ``start_run``'s population/trial
# routing. Only offered for a model that actually declares a verified
# physiology target (currently only the registered Aciclovir profile's
# renal GFR lever) -- Studio must not invent an override target a model's
# own capability profile does not declare.


@dataclass
class _PhysiologyRunState:
    status: str = "running"  # "running" | "completed" | "failed"
    events: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    run_directory: str | None = None
    manifest: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_PHYSIOLOGY_RUNS: dict[str, _PhysiologyRunState] = {}


def list_physiology_targets(path: str) -> list[dict[str, Any]]:
    """List the physiology targets the open project's resolved model actually declares."""
    resolved_path = Path(path)
    try:
        config = load_project(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error
    try:
        model = Project(config).model()
    except ValueError as error:
        raise StudioError(str(error)) from error
    return [
        {"target": t.target, "parameter_path": t.parameter_path, "unit": t.unit}
        for t in model.physiology_targets
    ]


def start_physiology_run(
    path: str,
    *,
    states: list[dict[str, Any]],
    baseline_state_id: str,
    output_root: str = "runs",
) -> dict[str, Any]:
    """Start a real physiology-state trial execution on a background thread."""
    resolved_path = Path(path)
    try:
        project = Project.load(resolved_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error

    try:
        model = project.model()
    except ValueError as error:
        raise StudioError(str(error)) from error
    if not model.physiology_targets:
        raise StudioError(
            f"Model {model.package.manifest.id!r} declares no verified physiology "
            "targets -- physiology-state execution is unavailable for this project."
        )
    if len(states) < 2:
        raise StudioError("A physiology-state trial requires at least two declared states.")

    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Run unavailable: set R_LIBS_USER, or r_libs_user in a config file, "
            "for the local ospsuite R library."
        )

    try:
        declarations = tuple(
            PhysiologyStateDeclaration(
                state_id=s["state_id"],
                override=PhysiologicalStateOverride(
                    target=s["target"],
                    scale_factor=s["scale_factor"],
                    unit=s["unit"],
                    purpose=s["purpose"],
                ),
            )
            for s in states
        )
    except Exception as error:  # pydantic ValidationError on a bad declared override
        raise StudioError(f"Invalid physiology state declaration: {error}") from error

    dose = project.trial.arms[0].intervention.regimen.doses[0]
    dose_mg = dose_mg_for_model(dose, model)
    resolved_output_root = Path(output_root)

    run_id = uuid.uuid4().hex
    state = _PhysiologyRunState()
    _PHYSIOLOGY_RUNS[run_id] = state

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
            generation_id, population_root = project.resolve_population(
                output_root=resolved_output_root,
                r_libs_user=runtime.r_libs_user,  # type: ignore[arg-type]  # checked above
                rscript_path=runtime.rscript_path,
                dotnet_root=runtime.dotnet_root,
                events=on_event,
            )
            physiology_root = resolved_output_root / "physiology"
            run = run_trial_physiology_states(
                model_capability_profile=model,
                population_generation_id=generation_id,
                population_root=population_root,
                physiology_root=physiology_root,
                states=declarations,
                baseline_state_id=baseline_state_id,
                dose_mg=dose_mg,
                output_root=resolved_output_root,
                r_libs_user=runtime.r_libs_user,  # type: ignore[arg-type]  # checked above
                observation_schedule=project.trial.observation_schedule,
                events=on_event,
            )
            manifest = verify_physiology_states(
                run, population_root=population_root, physiology_root=physiology_root
            )
            with state.lock:
                state.status = "completed"
                state.run_directory = str(run.run_directory)
                state.manifest = manifest.model_dump(mode="json")
        except Exception as error:  # noqa: BLE001 -- a real run can fail for many real reasons
            with state.lock:
                state.status = "failed"
                state.error = str(error)

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id}


def get_physiology_run(run_id: str) -> dict[str, Any]:
    """Report the current status, events, and (once complete) verified manifest."""
    state = _PHYSIOLOGY_RUNS.get(run_id)
    if state is None:
        raise StudioError(f"Unknown physiology run_id: {run_id!r}")
    with state.lock:
        return {
            "status": state.status,
            "events": list(state.events),
            "error": state.error,
            "run_directory": state.run_directory,
            "manifest": state.manifest,
        }


# ================= Cohorts / subgroups =================
#
# Cohort membership needs no OSP execution -- it is a pure filter over an
# already-generated, verified population (see sdk.cohort's own docstring),
# so unlike Run/physiology this never touches a background thread. Only
# available for a completed *population* (single-dose) run for now: a
# trial run's endpoints are split per arm (see sdk.run.TrialArtifacts),
# and picking which arm's endpoint store a cohort comparison should read
# from is a real design decision left for a later milestone rather than
# guessed at here.


def _parse_predicate(raw: dict[str, Any]) -> Predicate:
    predicate_type = raw.get("type")
    try:
        if predicate_type == "numeric":
            return NumericPredicate(
                field_id=raw["field_id"],
                operator=NumericOperator(raw["operator"]),
                value=raw["value"],
                unit=raw["unit"],
            )
        if predicate_type == "categorical":
            return CategoricalPredicate(field_id=raw["field_id"], values=tuple(raw["values"]))
        if predicate_type == "presence":
            return PresencePredicate(field_id=raw["field_id"], present=raw["present"])
    except Exception as error:
        raise StudioError(f"Invalid cohort predicate: {error}") from error
    raise StudioError(f"Unknown predicate type: {predicate_type!r}")


def list_cohort_fields() -> list[dict[str, Any]]:
    """List the registered logical fields a cohort predicate may reference."""
    catalog = osp_population_field_catalog()
    return [
        {"field_id": f.field_id, "kind": f.kind.value, "unit": f.unit} for f in catalog.fields
    ]


def define_cohorts_for_run(run_id: str, cohorts: list[dict[str, Any]]) -> dict[str, Any]:
    """Define and persist one or more cohorts against a completed population run."""
    state = _RUNS.get(run_id)
    if state is None or not isinstance(state.run_object, PopulationRun):
        raise StudioError(
            f"Run {run_id!r} is not a completed population (single-dose) run -- "
            "cohort comparison is currently only available for that run kind."
        )
    run = state.run_object
    population_root = run.artifacts.population_store.root
    generation_id = run.population.generation_id
    membership_root = run.run_directory / "cohorts"

    results = []
    for cohort in cohorts:
        predicates = tuple(_parse_predicate(p) for p in cohort["predicates"])
        try:
            manifest = define_and_persist_cohort(
                predicates=predicates,
                population_generation_id=generation_id,
                population_root=population_root,
                membership_root=membership_root,
            )
        except (OSError, ValueError) as error:
            raise StudioError(f"Cohort definition failed: {error}") from error
        results.append(
            {
                "label": cohort.get("label", manifest.membership_id),
                "membership_id": manifest.membership_id,
                "member_count": manifest.members.rows,
            }
        )
    return {"cohorts": results, "endpoint_id": run.artifacts.endpoint_id}


def compare_cohorts_for_run(
    run_id: str,
    *,
    group_a_membership_id: str,
    group_b_membership_id: str,
    group_a_label: str,
    group_b_label: str,
) -> dict[str, Any]:
    """Compare two persisted cohorts' PK endpoint outcomes from a completed population run."""
    state = _RUNS.get(run_id)
    if state is None or not isinstance(state.run_object, PopulationRun):
        raise StudioError(
            f"Run {run_id!r} is not a completed population (single-dose) run -- "
            "cohort comparison is currently only available for that run kind."
        )
    run = state.run_object
    try:
        result = compare_cohorts(
            group_a_membership_id=group_a_membership_id,
            group_b_membership_id=group_b_membership_id,
            group_a_label=group_a_label,
            group_b_label=group_b_label,
            endpoint_id=run.artifacts.endpoint_id,
            membership_root=run.run_directory / "cohorts",
            population_root=run.artifacts.population_store.root,
            endpoint_root=run.artifacts.endpoint_store.root,
        )
    except (OSError, ValueError) as error:
        raise StudioError(f"Cohort comparison failed: {error}") from error
    return result.model_dump(mode="json")


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


def get_registry_matches_for_compound(
    compound_id: str, *, root: str | None = None
) -> dict[str, Any]:
    """Real, rules-based Registry candidates for one discovered compound.

    Pure translation over ``sdk.registry_match`` -- no scoring/inference
    happens here, only reshaping into JSON. Every candidate returned
    already carries its own auditable ``reasons``.
    """
    backend = default_registry_backend(root)
    compound_match = match_compound(compound_id, backend=backend)
    return {
        "compound_match": match_summary(compound_match) if compound_match else None,
        "dataset_matches": [
            match_summary(m) for m in match_datasets_for_compound(compound_id, backend=backend)
        ],
        "parameter_evidence_matches": [
            match_summary(m)
            for m in match_parameter_evidence(compound_id=compound_id, backend=backend)
        ],
    }


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


# ================= Guided Model Onboarding (Studio v0.4) =================
#
# Turns a PKML discovery into a reviewed, provenance-bearing, live-verified
# model registration. Every function here is a thin translation over
# ``sdk.onboarding`` -- the checklist/registration gate logic lives there,
# never here, so it cannot be bypassed by a client that only calls some of
# these endpoints.


def start_model_draft(pkml_path: str, *, model_id: str, root: str | None = None) -> dict[str, Any]:
    """Inspect a PKML file once and start a fresh onboarding draft for it."""
    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Model inspection unavailable: set R_LIBS_USER, or r_libs_user in a config "
            "file, for the local ospsuite R library."
        )
    try:
        draft = sdk_onboarding.start_draft(
            pkml_path,
            model_id=model_id,
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
            root=root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Could not start onboarding draft: {error}") from error
    return draft.model_dump(mode="json")


def list_model_drafts(*, root: str | None = None) -> list[dict[str, Any]]:
    return [draft.model_dump(mode="json") for draft in sdk_onboarding.list_drafts(root=root)]


def get_model_draft(draft_id: str, *, root: str | None = None) -> dict[str, Any]:
    try:
        draft = sdk_onboarding.load_draft(draft_id, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return draft.model_dump(mode="json")


def set_model_draft_metadata(
    draft_id: str, *, model_version: str, license: str, root: str | None = None
) -> dict[str, Any]:
    try:
        draft = sdk_onboarding.set_model_metadata(
            draft_id, model_version=model_version, license=license, root=root
        )
    except ValueError as error:
        raise StudioError(str(error)) from error
    return draft.model_dump(mode="json")


def select_model_draft_capability(
    draft_id: str,
    *,
    slot: str,
    value: dict[str, Any],
    source_record_id: str | None = None,
    evidence_class: str | None = None,
    unit: str | None = None,
    context: str | None = None,
    provenance_ids: tuple[str, ...] = (),
    root: str | None = None,
) -> dict[str, Any]:
    """Record one researcher decision for one onboarding slot.

    ``evidence_class`` is accepted as a plain string at this JSON boundary
    (a candidate picked from a Registry match, or hand-typed by the
    researcher) and converted to the real enum here -- an invalid value
    fails loudly rather than being silently accepted.
    """
    try:
        resolved_evidence_class = EvidenceClass(evidence_class) if evidence_class else None
        draft = sdk_onboarding.select_capability(
            draft_id,
            slot=slot,
            value=value,
            source_record_id=source_record_id,
            evidence_class=resolved_evidence_class,
            unit=unit,
            context=context,
            provenance_ids=provenance_ids,
            root=root,
        )
    except ValueError as error:
        raise StudioError(str(error)) from error
    return draft.model_dump(mode="json")


def set_model_draft_unsupported_capabilities(
    draft_id: str, *, items: list[dict[str, str]], root: str | None = None
) -> dict[str, Any]:
    try:
        draft = sdk_onboarding.set_unsupported_capabilities(draft_id, items=items, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return draft.model_dump(mode="json")


def get_model_draft_checklist(draft_id: str, *, root: str | None = None) -> dict[str, Any]:
    try:
        draft = sdk_onboarding.load_draft(draft_id, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return sdk_onboarding.checklist(draft)


def start_model_draft_verification_run(
    draft_id: str, *, path: str, output_root: str = "runs", root: str | None = None
) -> dict[str, Any]:
    """Execute a real trial against the draft's current (unregistered) profile.

    Builds a fresh, private ``ModelCapabilityRegistry`` containing only
    this one draft profile, so the researcher's project (whose
    ``model_id`` must match the draft's) executes for real without the
    draft ever needing to be a fully registered model first -- and
    without silently colliding with an already-registered model that
    happens to share the same id.
    """
    try:
        draft = sdk_onboarding.load_draft(draft_id, root=root)
        profile = sdk_onboarding.build_profile_from_draft(draft)
    except ValueError as error:
        raise StudioError(f"Cannot start a verification run yet: {error}") from error

    registry = default_model_registry()
    try:
        registry.register(profile)
    except DuplicateModelCapabilityError as error:
        raise StudioError(str(error)) from error

    result = start_run(path, output_root=output_root, registry=registry)
    result["draft_id"] = draft_id
    return result


def record_model_draft_verification(
    draft_id: str, *, run_id: str, root: str | None = None
) -> dict[str, Any]:
    """Promote a draft's MAPPED selections to VERIFIED from one real completed run."""
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None or state.status != "completed":
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    try:
        draft = sdk_onboarding.load_draft(draft_id, root=root)
        profile = sdk_onboarding.build_profile_from_draft(draft)
    except ValueError as error:
        raise StudioError(str(error)) from error
    if state.run_object.model.model_id != profile.package.manifest.id:
        raise StudioError(
            f"Run {run_id!r} was executed against {state.run_object.model.model_id!r}, "
            f"not this draft's model {profile.package.manifest.id!r}."
        )
    endpoint_types = sorted({endpoint.endpoint_type for endpoint in state.run_object.endpoints})
    try:
        updated = sdk_onboarding.record_verification_run(
            draft_id, run_id=run_id, endpoint_types=endpoint_types, root=root
        )
    except ValueError as error:
        raise StudioError(str(error)) from error
    return updated.model_dump(mode="json")


def register_model_from_draft(
    draft_id: str, *, draft_root: str | None = None, registry_root: str | None = None
) -> dict[str, Any]:
    """Register the draft's MODEL + MODEL_VERIFICATION records -- gated, no bypass.

    ``draft_root`` (where onboarding drafts live) and ``registry_root``
    (where the Registry itself lives) are deliberately separate
    parameters, even though both default to sibling XDG paths -- they are
    two different stores, and conflating them into one ``root`` would
    silently point draft lookups at the registry directory or vice versa.
    ``sdk.onboarding.register_model`` re-checks the checklist itself, so
    a client cannot register a model by skipping a step; this function
    only translates its result and errors.
    """
    backend = default_registry_backend(registry_root)
    try:
        result = sdk_onboarding.register_model(draft_id, backend=backend, root=draft_root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return {
        "model": _manifest_summary(result["model"]),
        "verification": _manifest_summary(result["verification"]),
    }


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


def attach_evidence_to_project(project_path: str, connector_id: str) -> dict[str, Any]:
    """Run a connector for real, persist its artifacts, and attach the result to a trial.

    Records the real, hash-chained ``OTCONN-*`` manifest ID in
    ``Trial.evidence_ids`` -- never the connector's own class identity --
    so the attachment is independently re-verifiable later, the same
    discipline every other artifact reference in this project follows.
    Evidence is persisted under ``<project directory>/evidence/``, kept
    alongside the project file rather than wherever the server happens to
    have been launched from.
    """
    resolved_project_path = Path(project_path)
    try:
        config = load_project(resolved_project_path)
    except ProjectConfigurationError as error:
        raise StudioError(str(error)) from error

    runtime = resolve_osp_runtime()
    connectors = {
        c.identity.connector_id: c
        for c in default_evidence_connectors(r_libs_user=runtime.r_libs_user)
    }
    connector = connectors.get(connector_id)
    if connector is None:
        raise StudioError(f"Unknown evidence connector: {connector_id!r}")

    try:
        manifest = ingest_and_persist(
            connector, evidence_root=resolved_project_path.parent / "evidence"
        )
    except IneligibleEvidenceCandidateError as error:
        raise StudioError(f"This candidate is ineligible, not attachable: {error}") from error
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Evidence ingestion failed: {error}") from error

    if manifest.run_id in config.trial.evidence_ids:
        return _project_summary(config, resolved_project_path)

    return save_project(
        project_path,
        {"trial": {"evidence_ids": [*config.trial.evidence_ids, manifest.run_id]}},
    )


# ================= Registry Curation Pipeline =================
#
# Turns one evidence-connector run into a reviewed, evidence-classed,
# provenance-bearing Registry DATASET record -- or, if the connector
# itself declines the candidate, a real, listable IneligibleCandidateRecord
# instead of the silent code-level omission ``sdk.registry_seed`` uses
# today. Every function here is a thin translation over ``sdk.curation``;
# the checklist/acceptance gate logic lives there, never here.


def run_connector_for_curation(connector_id: str, *, root: str | None = None) -> dict[str, Any]:
    runtime = resolve_osp_runtime()
    if runtime.r_libs_user is None:
        raise StudioError(
            "Curation ingestion unavailable: set R_LIBS_USER, or r_libs_user in a config "
            "file, for the local ospsuite R library."
        )
    connectors = {
        c.identity.connector_id: c
        for c in default_evidence_connectors(r_libs_user=runtime.r_libs_user)
    }
    connector = connectors.get(connector_id)
    if connector is None:
        raise StudioError(f"Unknown evidence connector: {connector_id!r}")

    try:
        result = sdk_curation.create_candidate_from_connector(connector, root=root)
    except (OSError, ValueError, RuntimeError) as error:
        raise StudioError(f"Curation ingestion failed: {error}") from error

    if isinstance(result, sdk_curation.IneligibleCandidateRecord):
        return {"eligible": False, **result.model_dump(mode="json")}
    return {"eligible": True, **result.model_dump(mode="json")}


def list_curation_candidates(*, root: str | None = None) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in sdk_curation.list_candidates(root=root)]


def list_ineligible_curation_candidates(*, root: str | None = None) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in sdk_curation.list_ineligible(root=root)]


def get_curation_candidate(candidate_id: str, *, root: str | None = None) -> dict[str, Any]:
    try:
        candidate = sdk_curation.load_candidate(candidate_id, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


def set_curation_candidate_identity(
    candidate_id: str, *, logical_id: str, evidence_class: str, root: str | None = None
) -> dict[str, Any]:
    try:
        candidate = sdk_curation.set_candidate_identity(
            candidate_id,
            logical_id=logical_id,
            evidence_class=EvidenceClass(evidence_class),
            root=root,
        )
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


def set_curation_candidate_compatibility(
    candidate_id: str,
    *,
    model_ids: tuple[str, ...] = (),
    route: str | None = None,
    species: tuple[str, ...] = (),
    notes: str | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    try:
        candidate = sdk_curation.set_candidate_compatibility(
            candidate_id, model_ids=model_ids, route=route, species=species, notes=notes, root=root
        )
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


def mark_curation_license_reviewed(candidate_id: str, *, root: str | None = None) -> dict[str, Any]:
    try:
        candidate = sdk_curation.mark_license_reviewed(candidate_id, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


def acknowledge_curation_identity(candidate_id: str, *, root: str | None = None) -> dict[str, Any]:
    try:
        candidate = sdk_curation.acknowledge_identity(candidate_id, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


def get_curation_checklist(
    candidate_id: str, *, curation_root: str | None = None, registry_root: str | None = None
) -> dict[str, Any]:
    try:
        candidate = sdk_curation.load_candidate(candidate_id, root=curation_root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    backend = default_registry_backend(registry_root)
    return sdk_curation.checklist(candidate, backend=backend)


def accept_curation_candidate(
    candidate_id: str, *, curation_root: str | None = None, registry_root: str | None = None
) -> dict[str, Any]:
    backend = default_registry_backend(registry_root)
    try:
        manifest = sdk_curation.accept_candidate(candidate_id, backend=backend, root=curation_root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return _manifest_summary(manifest)


def reject_curation_candidate(
    candidate_id: str, *, reason: str, root: str | None = None
) -> dict[str, Any]:
    try:
        candidate = sdk_curation.reject_candidate(candidate_id, reason=reason, root=root)
    except ValueError as error:
        raise StudioError(str(error)) from error
    return candidate.model_dump(mode="json")


# ================= Run history =================
#
# A past run needs no in-memory ``Run`` object to inspect: the reporting
# module already re-derives everything from a run directory + population
# root on disk (``reporting.build``, the same functions ``opentrials
# report`` uses), so browsing history is pure filesystem listing plus the
# exact same report-building call the live Results pane already makes --
# no new verification/analysis logic, and no need to reconstruct a live
# ``PopulationRun``/``TrialRun`` object for a run this process didn't start.


def list_runs(output_root: str) -> list[dict[str, Any]]:
    """List every run directory found under ``output_root``, most recent first."""
    root = Path(output_root)
    if not root.is_dir():
        return []
    runs = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("OTR-"):
            continue
        is_trial = (entry / "trial_run").is_dir()
        runs.append(
            {
                "run_directory": str(entry),
                "run_id": entry.name,
                "kind": "trial" if is_trial else "population",
                "modified_at": datetime.fromtimestamp(entry.stat().st_mtime, tz=UTC).isoformat(),
            }
        )
    runs.sort(key=lambda r: r["modified_at"], reverse=True)
    return runs


def _build_historical_report_data(run_directory: str, population_root: str | None) -> ReportData:
    """Mirrors ``opentrials report``'s own logic exactly (``cli/main.py``'s ``_report``):
    detect trial vs. population by the presence of a ``trial_run`` subdirectory,
    re-verify from disk. Defaults ``population_root`` to ``<output_root>/populations``,
    matching where ``Project.run()`` itself puts a freshly generated population
    unless a project explicitly declares an existing one to reuse.
    """
    resolved_run_directory = Path(run_directory)
    resolved_population_root = (
        Path(population_root)
        if population_root
        else resolved_run_directory.parent / "populations"
    )
    is_trial = (resolved_run_directory / "trial_run").is_dir()
    try:
        return (
            build_trial_report(resolved_run_directory, resolved_population_root)
            if is_trial
            else build_population_report(resolved_run_directory, resolved_population_root)
        )
    except (OSError, ValueError, KeyError) as error:
        raise StudioError(f"Could not verify this run: {error}") from error


def get_historical_run_report_html(
    run_directory: str, *, population_root: str | None = None
) -> str:
    """Render the same self-contained HTML report for any past run directory."""
    return render_html(_build_historical_report_data(run_directory, population_root))


def get_historical_run_report_markdown(
    run_directory: str, *, population_root: str | None = None
) -> str:
    """Render the same Markdown report for any past run directory."""
    return render_markdown(_build_historical_report_data(run_directory, population_root))


def get_historical_run_result_data(
    run_directory: str, *, population_root: str | None = None
) -> dict[str, Any]:
    """Return the same re-verified ``ReportData`` a report renders from, as JSON.

    For Studio's native (non-iframe) results views -- concentration-time
    series, endpoint summary rows, pairwise comparisons -- so the frontend
    can render its own presentation of numbers that already came from a
    verified artifact, without a second analysis pass.
    """
    return _build_historical_report_data(run_directory, population_root).model_dump(mode="json")


def get_run_result_data(run_id: str) -> dict[str, Any]:
    """Same as ``get_historical_run_result_data``, for a run this process just executed."""
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None:
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    return state.run_object.report().model_dump(mode="json")


# ================= Registry =================
#
# Every function here is pure translation over ``registry.store``'s
# already-verifying backend (``get``/``verify`` re-derive hashes from
# disk, exactly like every other store in this project) -- no scientific
# computation, and no second copy of the "what is a valid Registry
# record" rule, which lives entirely in ``registry.schema``.


def _manifest_summary(manifest: Any) -> dict[str, Any]:
    return {
        "record_id": manifest.record_id,
        "logical_id": manifest.logical_id,
        "kind": manifest.kind.value,
        "version": manifest.version,
        "evidence_class": manifest.evidence_class.value,
        "license": manifest.license,
        "source": {"kind": manifest.source.kind, "identifier": manifest.source.identifier},
        "applies_to_model_ids": (
            list(manifest.compatibility.model_ids) if manifest.compatibility else []
        ),
        "superseded_id": manifest.superseded_id,
        "created_at": manifest.created_at.isoformat(),
    }


def list_registry_records(
    kind: str | None = None, *, root: str | None = None
) -> list[dict[str, Any]]:
    """List every registered record, optionally filtered by kind, most recent first."""
    backend = default_registry_backend(root)
    kind_enum = RegistryRecordKind(kind.upper()) if kind else None
    return [_manifest_summary(m) for m in backend.list(kind_enum)]


def get_registry_record(logical_id: str, *, root: str | None = None) -> dict[str, Any]:
    """Return one record's manifest and full payload, re-verified from disk."""
    backend = default_registry_backend(root)
    try:
        latest_manifest, _ = backend.get_latest(logical_id)
        manifest = backend.verify(latest_manifest.record_id)
        _, payload = backend.get(manifest.record_id)
    except RegistryError as error:
        raise StudioError(str(error)) from error
    return {"manifest": _manifest_summary(manifest), "payload": payload.model_dump(mode="json")}


def register_run_as_experiment(
    run_id: str, *, title: str, summary: str | None = None, license: str, root: str | None = None
) -> dict[str, Any]:
    """Register a completed run's trial as a real Registry EXPERIMENT record.

    Always ``evidence_class=SIMULATED`` -- enforced structurally by
    ``RegistryEntryManifest`` itself (see ``registry.schema``), not left
    to this function's own discipline: a simulated outcome can never be
    registered as MEASURED/CURATED/DERIVED evidence of the real world.
    """
    state = _RUNS.get(run_id)
    if state is None or state.run_object is None or state.trial is None:
        raise StudioError(f"Run {run_id!r} has not completed successfully.")
    run = state.run_object
    trial = state.trial

    experiment = ExperimentRecord(
        trial_id=trial.trial_id,
        trial=trial,
        trial_sha256=sha256(trial),
        model_id=run.model.model_id,
        run_id=run.run_id,
        title=title,
        summary=summary,
    )
    backend = default_registry_backend(root)
    manifest = backend.put(
        RegistryRecordKind.EXPERIMENT,
        experiment,
        logical_id=f"{trial.trial_id}-{run.run_id}",
        evidence_class=EvidenceClass.SIMULATED,
        license=license,
        source=RegistrySource(kind="experiment_run", identifier=run.run_id),
        compatibility=RegistryCompatibility(model_ids=(run.model.model_id,)),
    )
    return _manifest_summary(manifest)


def fork_experiment(
    logical_id: str, *, output_path: str, root: str | None = None
) -> dict[str, Any]:
    """Write a new project.yaml from a registered experiment's trial protocol.

    The new project's trial keeps an explicit ``provenance_ids`` pointer
    back to the exact experiment record it was forked from -- "preserving
    exact provenance of what changed" means the origin is never lost,
    even after the researcher edits arms/doses/endpoints locally through
    the normal Trial Builder save path.
    """
    backend = default_registry_backend(root)
    try:
        manifest, payload = backend.get_latest(logical_id)
    except RegistryError as error:
        raise StudioError(str(error)) from error
    if manifest.kind is not RegistryRecordKind.EXPERIMENT:
        raise StudioError(f"{logical_id!r} is not an experiment record (kind={manifest.kind!r}).")
    if not isinstance(payload, ExperimentRecord):
        raise StudioError(f"Unexpected payload type for experiment {logical_id!r}.")

    forked_trial = payload.trial.model_copy(
        update={"provenance_ids": (*payload.trial.provenance_ids, manifest.record_id)}
    )
    resolved_output_path = Path(output_path)
    if resolved_output_path.exists():
        raise StudioError(f"Refusing to overwrite an existing file: {resolved_output_path}")
    config = ProjectConfig(trial=forked_trial, model_id=payload.model_id)
    resolved_output_path.write_text(dump_project(config), encoding="utf-8")
    return _project_summary(config, resolved_output_path)
