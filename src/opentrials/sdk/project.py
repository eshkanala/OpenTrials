"""The researcher-facing entry point: load a project, run it, get a Run back.

``Project`` is deliberately the *only* thing most researchers should need
to import. It resolves which registered model to execute against, decides
whether the declared trial needs population-only execution (one arm) or
full multi-arm trial execution (two or more arms), generates or reuses the
population, and returns the appropriate ``sdk.run.Run``. Every decision it
makes is one already made explicitly, by hand, in this project's own live
integration tests -- this is that decision-making, done once, generically.
"""

from __future__ import annotations

from pathlib import Path

from opentrials.adapters.osp.engine import DEFAULT_DOTNET_ROOT, DEFAULT_FRAMEWORK_RSCRIPT
from opentrials.compound.intervention import Dose
from opentrials.config.project import ProjectConfig, load_project
from opentrials.events import EventSink
from opentrials.models.capability import ModelCapabilityProfile
from opentrials.models.registry import ModelCapabilityRegistry
from opentrials.sdk.population import generate_population, run_population
from opentrials.sdk.registry import default_model_registry
from opentrials.sdk.run import PopulationRun, TrialRun
from opentrials.sdk.trial import run_trial
from opentrials.trials.trial import Trial


class Project:
    """A trial protocol bound to the registered model that will execute it."""

    def __init__(
        self, config: ProjectConfig, *, registry: ModelCapabilityRegistry | None = None
    ) -> None:
        self.config = config
        self._registry = registry if registry is not None else default_model_registry()

    @classmethod
    def load(
        cls, path: str | Path, *, registry: ModelCapabilityRegistry | None = None
    ) -> Project:
        """Load and validate a project YAML document without executing it."""
        return cls(load_project(path), registry=registry)

    @property
    def trial(self) -> Trial:
        return self.config.trial

    def model(self) -> ModelCapabilityProfile:
        """Resolve the registered model this project will execute through."""
        if self.config.model_id is not None:
            return self._registry.get(self.config.model_id)
        model_ids = self._registry.model_ids()
        if len(model_ids) != 1:
            raise ValueError(
                "This project does not declare model_id, and the registry has "
                f"{len(model_ids)} registered models ({model_ids!r}) -- set model_id "
                "explicitly to remove the ambiguity."
            )
        return self._registry.get(model_ids[0])

    def resolve_population(
        self,
        *,
        output_root: str | Path,
        r_libs_user: str,
        rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
        dotnet_root: str = DEFAULT_DOTNET_ROOT,
        events: EventSink | None = None,
    ) -> tuple[str, Path]:
        """Return a verified ``(generation_id, population_root)`` for this project.

        Generates a fresh population (under ``output_root/populations``)
        unless the project explicitly declares an existing
        ``population_generation_id``/``population_root`` to reuse instead.
        Extracted from ``run()`` so any execution mode this project needs
        beyond plain population/trial execution (e.g. ``sdk.physiology``'s
        physiology-state trials) resolves a population the exact same way,
        rather than reimplementing this decision.
        """
        output_root = Path(output_root)
        if self.config.population_generation_id is not None:
            if self.config.population_root is None:
                raise ValueError(
                    "population_root is required when population_generation_id is set."
                )
            return self.config.population_generation_id, self.config.population_root
        population_root = output_root / "populations"
        manifest = generate_population(
            self.config.trial.population,
            population_root=population_root,
            r_libs_user=r_libs_user,
            rscript_path=rscript_path,
            dotnet_root=dotnet_root,
            events=events,
        )
        return manifest.generation_id, population_root

    def run(
        self,
        *,
        output_root: str | Path = Path("runs"),
        r_libs_user: str,
        rscript_path: Path = DEFAULT_FRAMEWORK_RSCRIPT,
        dotnet_root: str = DEFAULT_DOTNET_ROOT,
        events: EventSink | None = None,
    ) -> PopulationRun | TrialRun:
        """Execute this project's trial and return its result.

        ``output_root`` defaults to ``runs/`` in the current working
        directory, matching the CLI's own ``--output-root`` default -- the
        SDK is the canonical interface the CLI is built on, so the two
        should never diverge on a default.

        Routes to ``sdk.trial.run_trial`` for two or more declared arms, or
        ``sdk.population.run_population`` for exactly one -- the two
        existing orchestration capabilities this project actually has, not
        an SDK-invented distinction.

        ``rscript_path``/``dotnet_root`` default to OpenTrials' own
        compiled-in macOS layout; pass ``config.runtime.resolve_osp_runtime()``
        (or your own values) to run against a different machine.
        """
        output_root = Path(output_root)
        model = self.model()
        trial = self.config.trial
        generation_id, population_root = self.resolve_population(
            output_root=output_root,
            r_libs_user=r_libs_user,
            rscript_path=rscript_path,
            dotnet_root=dotnet_root,
            events=events,
        )

        # Trial.arms already requires at least one arm (see trials.trial.Trial),
        # so this is a genuine two-way choice, not a three-way one with an
        # unreachable "zero arms" case.
        if len(trial.arms) >= 2:
            return run_trial(
                trial,
                model_capability_profile=model,
                population_generation_id=generation_id,
                population_root=population_root,
                output_root=output_root,
                r_libs_user=r_libs_user,
                rscript_path=rscript_path,
                dotnet_root=dotnet_root,
                observation_schedule=trial.observation_schedule,
                events=events,
            )
        if trial.observation_schedule is not None:
            raise ValueError(
                "This trial declares an observation_schedule, but single-arm "
                "population-only execution does not yet support a declared "
                "sample-collection timeline -- only multi-arm (two or more "
                "declared arms) execution does. Remove observation_schedule or "
                "declare a second arm."
            )
        dose_mg = dose_mg_for_model(trial.arms[0].intervention.regimen.doses[0], model)
        return run_population(
            model_capability_profile=model,
            population_generation_id=generation_id,
            population_root=population_root,
            dose_mg=dose_mg,
            output_root=output_root,
            r_libs_user=r_libs_user,
            rscript_path=rscript_path,
            dotnet_root=dotnet_root,
            events=events,
        )


def load(path: str | Path, *, registry: ModelCapabilityRegistry | None = None) -> Project:
    """Load a project YAML document -- the one function most researchers need."""
    return Project.load(path, registry=registry)


def dose_mg_for_model(dose: Dose, model: ModelCapabilityProfile) -> float:
    """Convert a declared dose to the numeric amount a model's own unit expects.

    Pure unit conversion via ``ScientificValue.to()`` -- no scientific
    computation, just translation -- shared by ``Project.run()``'s
    single-arm path and any other execution mode (e.g. ``sdk.physiology``)
    that needs "the dose this model should be executed at" from a
    declared ``Dose``.
    """
    unit = model.administrations[0].supported_dose_unit or "mg"
    return dose.amount.to(unit).value
