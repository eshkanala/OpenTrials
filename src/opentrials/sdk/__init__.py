"""The public, researcher-facing OpenTrials SDK.

``Project``/``load`` is the canonical entry point; the CLI (``opentrials.cli``)
is a thin renderer built exclusively on top of this package and contains no
scientific logic of its own. A future GUI is expected to be a second such
client of this same package.
"""

from opentrials.events import Event, EventSink, EventStatus
from opentrials.sdk.population import generate_population, run_population
from opentrials.sdk.project import Project, load
from opentrials.sdk.registry import default_model_registry
from opentrials.sdk.run import (
    EndpointRecord,
    ModelSummary,
    PopulationArtifacts,
    PopulationRun,
    PopulationSummary,
    TrialArtifacts,
    TrialRun,
)
from opentrials.sdk.trial import run_trial

__all__ = [
    "EndpointRecord",
    "Event",
    "EventSink",
    "EventStatus",
    "ModelSummary",
    "PopulationArtifacts",
    "PopulationRun",
    "PopulationSummary",
    "Project",
    "TrialArtifacts",
    "TrialRun",
    "default_model_registry",
    "generate_population",
    "load",
    "run_population",
    "run_trial",
]
