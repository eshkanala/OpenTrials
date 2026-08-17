"""Solver-adapter protocol and standardized non-biological result contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from opentrials.models.manifest import ModelType
from opentrials.models.package import ModelPackage
from opentrials.trials.trial import Trial


class EngineCapabilities(BaseModel):
    """Declared capabilities of an isolated simulation adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_id: str = Field(min_length=1)
    supported_model_types: tuple[ModelType, ...]
    supports_population_simulation: bool
    supports_parallel_execution: bool


class EngineValidation(BaseModel):
    """Result of validating an engine/model/trial combination before execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class PreparedRun(BaseModel):
    """Validated engine input, ready to be sent to an external worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    trial: Trial
    model_packages: tuple[ModelPackage, ...] = Field(min_length=1)
    seed: int


class RawSimulationResult(BaseModel):
    """Engine-owned raw output retained before OpenTrials normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    engine_id: str = Field(min_length=1)
    generated_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class SimulationResult(BaseModel):
    """Normalized run result metadata, separate from large result artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    engine_id: str = Field(min_length=1)
    generated_at: datetime
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class SimulationEngine(Protocol):
    """Boundary every external solver adapter must implement."""

    def capabilities(self) -> EngineCapabilities: ...

    def validate(self, packages: tuple[ModelPackage, ...], trial: Trial) -> EngineValidation: ...

    def prepare(
        self, run_id: str, packages: tuple[ModelPackage, ...], trial: Trial
    ) -> PreparedRun: ...

    def run(self, prepared_run: PreparedRun) -> RawSimulationResult: ...

    def extract(self, raw_result: RawSimulationResult) -> SimulationResult: ...

    def version_info(self) -> dict[str, str]: ...


class MockSimulationEngine:
    """Contract-test engine that never calculates a biological prediction."""

    engine_id = "mock"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            engine_id=self.engine_id,
            supported_model_types=tuple(ModelType),
            supports_population_simulation=False,
            supports_parallel_execution=False,
        )

    def validate(self, packages: tuple[ModelPackage, ...], trial: Trial) -> EngineValidation:
        if not packages:
            return EngineValidation(
                is_valid=False, errors=("At least one model package is required.",)
            )
        unsupported = tuple(
            package.manifest.id for package in packages if package.manifest.engine != self.engine_id
        )
        if unsupported:
            return EngineValidation(
                is_valid=False,
                errors=(f"Mock engine cannot execute: {', '.join(unsupported)}.",),
            )
        return EngineValidation(is_valid=True)

    def prepare(self, run_id: str, packages: tuple[ModelPackage, ...], trial: Trial) -> PreparedRun:
        validation = self.validate(packages, trial)
        if not validation.is_valid:
            raise ValueError(
                "Cannot prepare an invalid mock-engine run: " + "; ".join(validation.errors)
            )
        return PreparedRun(run_id=run_id, trial=trial, model_packages=packages, seed=trial.seed)

    def run(self, prepared_run: PreparedRun) -> RawSimulationResult:
        return RawSimulationResult(
            run_id=prepared_run.run_id,
            engine_id=self.engine_id,
            generated_at=datetime.now(UTC),
            payload={"kind": "mock", "seed": prepared_run.seed},
        )

    def extract(self, raw_result: RawSimulationResult) -> SimulationResult:
        if raw_result.engine_id != self.engine_id:
            raise ValueError("Mock engine cannot extract a result from another engine.")
        return SimulationResult(
            run_id=raw_result.run_id,
            engine_id=self.engine_id,
            generated_at=raw_result.generated_at,
            warnings=("Mock engine produced no biological simulation output.",),
        )

    def version_info(self) -> dict[str, str]:
        return {"engine": self.engine_id, "version": "0.1.0"}
