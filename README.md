# OpenTrials

**Open, reproducible infrastructure for mechanistic virtual clinical-trial research.**

OpenTrials is an open-source Python platform for defining, executing, verifying, analyzing, and reporting virtual clinical trials against compatible mechanistic models. It provides a reproducible research layer around simulation engines, with explicit model capabilities, verified execution, immutable artifacts, provenance, and researcher-facing reports.

> **Research and educational use only.** OpenTrials is not a clinical decision-support system, medical device, diagnostic tool, or source of patient-specific treatment advice. Simulation results do not establish clinical validity.

**Release:** `v1.0.0-rc.1` · **License:** Apache-2.0 · **Integration:** Open Systems Pharmacology (`ospsuite`)

## Overview

Mechanistic simulation workflows involve more than executing a solver. A reproducible study must establish which model ran, which population was simulated, which intervention reached the engine, how participants were allocated, which outputs were analyzed, how endpoints were calculated, and where observed evidence originated.

OpenTrials provides that infrastructure around compatible PBPK/QSP models:

```text
Experiment definition + registered model + virtual population
                              │
                              ▼
                 Capability validation
                              │
                              ▼
                  Verified translation
                              │
                              ▼
                Mechanistic simulation
                              │
                              ▼
             Immutable research artifacts
                              │
                              ▼
               Analysis and comparison
                              │
                              ▼
              Reproducible research report
```

The simulation engine remains responsible for the mechanistic model. OpenTrials manages the experiment, execution contract, provenance, analysis pipeline, and reproducibility layer around it.

## Features

| Capability | Description |
| --- | --- |
| **Virtual populations** | Deterministic generation, persistence, hashing, verification, and stable subject lineage. |
| **Verified execution** | Model-hash checks, parameter translation, solver-state read-back, and execution verification. |
| **Population PBPK** | Batched mechanistic simulation across virtual populations, including a live-tested 10,000-subject execution path. |
| **Multi-arm trials** | Deterministic participant allocation and arm-specific intervention execution. |
| **Observation schedules** | Declared sampling schedules verified against the executed solver output grid. |
| **PK endpoints** | Canonical concentration-time results with Cmax, Tmax, and AUC0-last. |
| **Cohorts and subgroups** | Reproducible membership definitions and descriptive PK comparisons with preserved subject lineage. |
| **Extreme responders** | Transparent rank/percentile response selection and descriptive baseline comparisons. |
| **Uncertainty analysis** | Deterministic perturbation draws, verified execution, and persisted sensitivity rankings. |
| **Physiological states** | Typed physiological overrides and paired within-subject comparisons across simulated states. |
| **Evidence ingestion** | Source metadata, raw snapshots, transformation provenance, observed datasets, and dataset-role tracking. |
| **Validation infrastructure** | Compatibility gating, prediction-observation alignment, residuals, endpoint comparison, and validation artifacts. |
| **Reports** | Self-contained Markdown and HTML research reports generated from verified artifacts. |
| **Model onboarding** | OSP model inspection and capability-profile scaffolding with explicit human verification. |

See [`docs/project-status.md`](docs/project-status.md) for current implementation status and remaining external validation/generalization work.

## Quickstart

### Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- R
- Open Systems Pharmacology [`ospsuite`](https://www.open-systems-pharmacology.org/)
- the .NET runtime required by `ospsuite`
- a compatible registered mechanistic model

The current OSP integration has been live-verified on Apple Silicon macOS. Runtime paths are configurable for other environments, but those platforms have not yet received equivalent end-to-end verification.

### Install

```bash
git clone https://github.com/eshkanala/OpenTrials.git
cd OpenTrials
uv sync --all-extras
```

### Create a project

```bash
uv run opentrials init
```

This creates a commented, runnable `project.yaml`.

Validate the project without executing OSP:

```bash
uv run opentrials validate project.yaml
```

### Run

```bash
uv run opentrials run project.yaml \
  --r-libs-user /path/to/ospsuite/library \
  --verbose
```

Runtime paths can also be configured in `.opentrials.yaml`:

```yaml
rscript_path: /path/to/Rscript
dotnet_root: /path/to/dotnet
r_libs_user: /path/to/R/library
```

### Generate a report

```bash
uv run opentrials report runs/<run-id> \
  --population-root runs/populations \
  --format html
```

A live-tested two-arm example is available at [`examples/aciclovir_dose_comparison.yaml`](examples/aciclovir_dose_comparison.yaml).

For full installation and runtime configuration, see [`docs/quickstart.md`](docs/quickstart.md).

## Python SDK

The Python SDK is the primary programmatic interface. The CLI is implemented as a thin client over the same researcher-facing layer.

```python
import opentrials

project = opentrials.load("project.yaml")
run = project.run(r_libs_user="/path/to/ospsuite/library")

print(run.summary())
print(run.endpoints)

run.verify()
run.report(format="html")
```

See [`docs/sdk.md`](docs/sdk.md) for the complete SDK guide.

## Model integration

OpenTrials does not maintain a database of drugs or biological parameters. Compound- and physiology-specific behavior remains defined by the underlying mechanistic model.

Each supported model is registered through a `ModelCapabilityProfile` describing its identity, supported compounds and administration routes, mutable intervention and physiology targets, canonical outputs, units, provenance, and unsupported capabilities.

Generic orchestration consumes this profile instead of embedding model-specific constants in the execution pipeline.

### Inspect a model

```bash
uv run opentrials model inspect path/to/model.pkml
```

### Create a capability-profile scaffold

```bash
uv run opentrials model init path/to/model.pkml
```

Generated profiles require explicit review before registration; automated discovery is not treated as scientific verification.

Registered models can be inspected with:

```bash
uv run opentrials models list
uv run opentrials models show <model-id>
```

See [`docs/models.md`](docs/models.md) for model registration and verification.

## Reference implementation

Two live-proven models are registered through the verified OSP environment: an aciclovir IV PBPK model (renal clearance) and a Midazolam oral tablet PBPK model (hepatic/gut CYP3A4+UGT1A4 clearance). The orchestration architecture is model-independent -- registering the second model required no changes to generic execution code beyond fixing one hard-coded assumption the first model's IV-only path had never exposed. See [`docs/models.md`](docs/models.md) and [`docs/project-status.md`](docs/project-status.md) for detail.

## Reproducibility and provenance

OpenTrials records and verifies the identities needed to reconstruct a simulation result, including model hashes, population identity, trial configuration, requested and executed intervention values, solver read-back evidence, result and endpoint artifacts, allocation identity, subject lineage, observation schedules, evidence provenance, transformations, and software identity.

Artifacts are immutable and independently verifiable. Higher-level artifacts verify their dependencies rather than relying solely on copied metadata. Reports are generated from verified artifacts and do not implement an independent scientific-analysis path.

Representative artifact families include:

```text
Population
  OTPGEN   generated population
  OTPHYS   physiological-state population

Trial execution
  OTALLOC  arm allocation
  OTRES    canonical concentration-time result
  OTPK     PK endpoints
  OTACMP   arm comparison
  OTTRIAL  trial provenance

Population analysis
  OTCOH / OTMEM    cohort definition and membership
  OTCPK            cohort PK comparison
  OTXMEM / OTXCMP  extreme-response analysis

Uncertainty
  OTUSC    uncertainty scenario
  OTUDR    materialized draws
  OTUEX    verified executions
  OTSENS   sensitivity analysis

Evidence and validation
  OTRAW    raw source snapshot
  OTOBS    observed dataset
  OTCONN   connector provenance
  OTVAL    validation result
```

See [`docs/architecture.md`](docs/architecture.md) for architecture and artifact contracts.

## Validation status

OpenTrials includes infrastructure for observed evidence, trial-study compatibility checks, prediction-observation alignment, residual analysis, endpoint comparison, and immutable validation artifacts.

The current reference model does **not** yet have a qualifying, rights-cleared independent human dataset that supports an external validation claim. Calibration data bundled with the model are tracked as calibration evidence rather than presented as independent validation.

See [`docs/limitations.md`](docs/limitations.md) for the maintained scientific and engineering limitations and [`docs/project-status.md`](docs/project-status.md) for current release status.

## Performance

The optimized OSP CSV transport path has been live-tested with a **10,000-subject virtual population**, including result persistence, in approximately **421 seconds** on the development system used for the benchmark.

The CSV transport substantially reduces OSP result-serialization overhead compared with the reference JSON path. CSV and JSON results are not claimed to be byte-identical because OSP's CSV export uses limited textual precision; endpoint agreement has been empirically bounded within that representation's precision.

## Limitations

Current limitations include:

- no clinical or patient-specific use;
- no independent human validation claim for the reference model;
- one live-proven registered mechanistic model;
- no arbitrary repeated/multi-dose protocol authoring through the current headless OSP R interface;
- selected advanced workflows remain Python-API-only rather than exposed through the top-level `Project`/CLI interface;
- persisted artifact schemas currently require exact version matches and do not yet have migration tooling.

See [`docs/limitations.md`](docs/limitations.md) for details.

## Documentation

| Document | Description |
| --- | --- |
| [`docs/quickstart.md`](docs/quickstart.md) | Installation, runtime configuration, first run, and reporting |
| [`docs/sdk.md`](docs/sdk.md) | Python SDK and artifact access |
| [`docs/models.md`](docs/models.md) | Model inspection, registration, and verification |
| [`docs/architecture.md`](docs/architecture.md) | Architecture, trust boundaries, artifacts, and versioning |
| [`docs/limitations.md`](docs/limitations.md) | Scientific and engineering limitations |
| [`docs/project-status.md`](docs/project-status.md) | Release status and outstanding work |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributor guide |

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests scripts
uv run mypy src
```

OSP integration tests are opt-in and require a functioning local R/`ospsuite`/.NET environment.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development and contribution guidance.

## License

OpenTrials is licensed under the [Apache License 2.0](LICENSE).

Third-party models, datasets, and simulation engines remain subject to their respective licenses and usage terms.
