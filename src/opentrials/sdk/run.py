"""The researcher-facing result of one SDK-level run.

Two concrete shapes exist -- ``PopulationRun`` (one dose, the whole
population) and ``TrialRun`` (two or more declared arms) -- because those
are two genuinely different existing orchestration capabilities
(``orchestration.population_execution``/``orchestration.trial_execution``),
not because the SDK invented a distinction. Both expose the same simple
surface (``summary()``, ``endpoints``, ``population``, ``verify()``) for
the common case, and both expose their full underlying orchestration
result and artifact stores through ``.artifacts`` for anyone who needs to
descend past the summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from opentrials.models.capability import ModelCapabilityProfile
from opentrials.orchestration.population_execution import PopulationExecutionRun
from opentrials.orchestration.trial_execution import ArmExecutionResult, TrialExecutionRun
from opentrials.reporting.data import ReportData
from opentrials.storage.allocation import TrialArmAllocationArtifactStore
from opentrials.storage.arm_comparison_artifacts import ArmComparisonArtifactStore
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore
from opentrials.storage.trial_run import TrialRunArtifactStore


class EndpointRecord(BaseModel):
    """One flattened, easy-to-read PK endpoint value.

    The simple view over ``analysis.pk.PkEndpointResult`` -- drops the
    provenance-hash fields a researcher does not need to read a result,
    while ``.artifacts`` still exposes the full typed record for anyone
    who does.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str | None
    subject_id: str
    endpoint_type: str
    value: float
    unit: str


class PopulationSummary(BaseModel):
    """The population this run actually executed against."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_id: str
    participant_count: int


class ModelSummary(BaseModel):
    """The registered model this run executed through."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    engine: str
    version: str


class Run(Protocol):
    """The common shape both ``PopulationRun`` and ``TrialRun`` satisfy."""

    run_id: str
    run_directory: Path
    endpoints: tuple[EndpointRecord, ...]
    population: PopulationSummary
    model: ModelSummary

    def summary(self) -> str: ...

    def verify(self) -> bool: ...

    def report(self) -> ReportData: ...


class PopulationArtifacts:
    """Advanced, unmediated access to a population run's underlying artifacts."""

    def __init__(self, execution: PopulationExecutionRun, *, population_root: Path) -> None:
        self.execution = execution
        self.population_store = PopulationArtifactStore(population_root)
        self.endpoint_store = PkEndpointArtifactStore(execution.endpoint_directory.parent)

    @property
    def endpoint_id(self) -> str:
        return self.execution.endpoint_directory.name


class PopulationRun:
    """The result of ``sdk.population.run_population`` -- one dose, the whole population."""

    def __init__(
        self,
        execution: PopulationExecutionRun,
        *,
        model_capability_profile: ModelCapabilityProfile,
        population_root: Path,
    ) -> None:
        self._execution = execution
        self._model = model_capability_profile
        self.artifacts = PopulationArtifacts(execution, population_root=population_root)

    @property
    def run_id(self) -> str:
        return self._execution.run_id

    @property
    def run_directory(self) -> Path:
        return self._execution.run_directory

    @property
    def population(self) -> PopulationSummary:
        return PopulationSummary(
            generation_id=self._execution.population_generation_id,
            participant_count=self._execution.population_count,
        )

    @property
    def model(self) -> ModelSummary:
        return _model_summary(self._model)

    @property
    def endpoints(self) -> tuple[EndpointRecord, ...]:
        return tuple(
            EndpointRecord(
                arm_id=None,
                subject_id=endpoint.subject_id,
                endpoint_type=endpoint.endpoint_type.value,
                value=endpoint.value,
                unit=endpoint.unit,
            )
            for endpoint in self._execution.endpoints
        )

    def summary(self) -> str:
        lines = [
            f"OpenTrials population run {self.run_id}",
            f"Model         {self._model.package.manifest.id}",
            f"Population    {self.population.participant_count} participants "
            f"({self.population.generation_id})",
            "",
        ]
        lines.extend(_endpoint_summary_lines(self.endpoints))
        return "\n".join(lines)

    def verify(self) -> bool:
        """Re-verify the population and endpoint artifacts from their own stores."""
        self.artifacts.population_store.verify_population(self.population.generation_id)
        self.artifacts.endpoint_store.verify_endpoints(self.artifacts.endpoint_id)
        return True

    def report(self) -> ReportData:
        """Build a report, re-verifying the whole chain from disk -- see reporting.build."""
        from opentrials.reporting.build import build_population_report

        return build_population_report(
            self.run_directory, self.artifacts.population_store.root
        )


class TrialArtifacts:
    """Advanced, unmediated access to a trial run's underlying artifacts."""

    def __init__(self, execution: TrialExecutionRun, *, population_root: Path) -> None:
        self.execution = execution
        self.population_store = PopulationArtifactStore(population_root)
        self.trial_run_store = TrialRunArtifactStore(execution.run_directory / "trial_run")
        self.comparison_store = ArmComparisonArtifactStore(execution.run_directory / "comparison")
        self.allocation_store = TrialArmAllocationArtifactStore(
            execution.run_directory / "allocation", population_store=self.population_store
        )
        self.endpoint_stores = {
            arm.arm_id: PkEndpointArtifactStore(
                execution.run_directory / "arms" / arm.arm_id / "endpoints"
            )
            for arm in execution.arms
        }


class TrialRun:
    """The result of ``sdk.trial.run_trial`` -- two or more declared arms."""

    def __init__(
        self,
        execution: TrialExecutionRun,
        *,
        model_capability_profile: ModelCapabilityProfile,
        population_root: Path,
    ) -> None:
        self._execution = execution
        self._model = model_capability_profile
        self.artifacts = TrialArtifacts(execution, population_root=population_root)

    @property
    def run_id(self) -> str:
        return self._execution.run_id

    @property
    def run_directory(self) -> Path:
        return self._execution.run_directory

    @property
    def arms(self) -> tuple[ArmExecutionResult, ...]:
        return self._execution.arms

    @property
    def population(self) -> PopulationSummary:
        return PopulationSummary(
            generation_id=self._execution.population_generation_id,
            participant_count=self._execution.population_count,
        )

    @property
    def model(self) -> ModelSummary:
        return _model_summary(self._model)

    @property
    def endpoints(self) -> tuple[EndpointRecord, ...]:
        records: list[EndpointRecord] = []
        for arm in self._execution.arms:
            records.extend(
                EndpointRecord(
                    arm_id=arm.arm_id,
                    subject_id=endpoint.subject_id,
                    endpoint_type=endpoint.endpoint_type.value,
                    value=endpoint.value,
                    unit=endpoint.unit,
                )
                for endpoint in arm.endpoints
            )
        return tuple(records)

    def summary(self) -> str:
        lines = [
            f"OpenTrials trial run {self.run_id}",
            f"Trial         {self._execution.trial_id}",
            f"Model         {self._model.package.manifest.id}",
            f"Population    {self.population.participant_count} participants "
            f"({self.population.generation_id})",
            f"Arms          {', '.join(arm.arm_id for arm in self._execution.arms)}",
            "",
        ]
        lines.extend(_endpoint_summary_lines(self.endpoints, group_by_arm=True))
        return "\n".join(lines)

    def verify(self) -> bool:
        """Re-verify the whole chain from each sub-artifact's own store."""
        self.artifacts.trial_run_store.verify_trial_run(
            self._execution.trial_run_id,
            population_store=self.artifacts.population_store,
            allocation_store=self.artifacts.allocation_store,
            endpoint_stores=self.artifacts.endpoint_stores,
            comparison_store=self.artifacts.comparison_store,
        )
        return True

    def report(self) -> ReportData:
        """Build a report, re-verifying the whole chain from disk -- see reporting.build."""
        from opentrials.reporting.build import build_trial_report

        return build_trial_report(self.run_directory, self.artifacts.population_store.root)


def _model_summary(profile: ModelCapabilityProfile) -> ModelSummary:
    return ModelSummary(
        model_id=profile.package.manifest.id,
        engine=profile.package.manifest.engine,
        version=profile.package.manifest.version,
    )


def _endpoint_summary_lines(
    endpoints: tuple[EndpointRecord, ...], *, group_by_arm: bool = False
) -> list[str]:
    if not endpoints:
        return ["No endpoints."]
    if not group_by_arm:
        return _mean_by_type_lines(endpoints)
    lines: list[str] = []
    arm_ids = sorted({endpoint.arm_id for endpoint in endpoints if endpoint.arm_id is not None})
    for arm_id in arm_ids:
        lines.append(f"[{arm_id}]")
        lines.extend(
            "  " + line
            for line in _mean_by_type_lines(
                tuple(endpoint for endpoint in endpoints if endpoint.arm_id == arm_id)
            )
        )
    return lines


def _mean_by_type_lines(endpoints: tuple[EndpointRecord, ...]) -> list[str]:
    by_type: dict[str, list[EndpointRecord]] = {}
    for endpoint in endpoints:
        by_type.setdefault(endpoint.endpoint_type, []).append(endpoint)
    lines = []
    for endpoint_type in sorted(by_type):
        group = by_type[endpoint_type]
        mean = sum(record.value for record in group) / len(group)
        lines.append(f"{endpoint_type:<12} mean={mean:g} {group[0].unit} (n={len(group)})")
    return lines
