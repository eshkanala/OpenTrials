# OpenTrials

**Open, reproducible infrastructure for mechanistic virtual clinical-trial research.**

OpenTrials is an open-source Python platform for defining, executing, verifying, analyzing, and reporting virtual clinical trials against compatible mechanistic models. It is designed for researchers who want simulation workflows that are **inspectable, reproducible, provenance-aware, and difficult to misrepresent accidentally**.

OpenTrials does not replace a PBPK/QSP engine. It sits around one: it turns a mechanistic model, a virtual population, a declared intervention, and an analysis plan into a traceable research workflow with immutable artifacts and explicit verification at the boundaries where silent mistakes are most dangerous.

> **Research and educational use only.** OpenTrials is not a clinical decision-support system, medical device, diagnostic tool, or source of patient-specific treatment advice. A successful simulation is not evidence of clinical validity.

**Current release candidate:** `v1.0.0-rc.1`  
**License:** Apache-2.0  
**Current live solver integration:** Open Systems Pharmacology (`ospsuite` / PK-Sim-compatible simulations)

---

## Why OpenTrials exists

Mechanistic simulation tools can answer sophisticated pharmacology questions, but a complete research workflow involves more than calling a solver. Researchers also need to know:

- exactly which model and model version ran;
- what population was simulated;
- which intervention values actually reached the solver;
- whether the executed protocol matched the declared protocol;
- how subjects were allocated to arms or subgroups;
- which output series became the scientific result;
- which transformations and endpoint rules were applied;
- where observed evidence came from and what it was originally used for;
- whether a result can be independently reloaded and verified later;
- and, just as importantly, what the workflow **does not prove**.

OpenTrials makes those concerns first-class parts of the system rather than conventions left to notebooks and memory.

The intended workflow is:

```text
experiment definition
        +
registered mechanistic model
        +
virtual population / evidence
        │
        ▼
capability + compatibility checks
        │
        ▼
verified engine translation
        │
        ▼
mechanistic simulation
        │
        ▼
immutable raw + canonical artifacts
        │
        ▼
PK / cohort / trial / sensitivity analysis
        │
        ▼
re-verifiable provenance record
        │
        ▼
human-readable research report
```

The solver remains responsible for the mechanistic mathematics. OpenTrials is responsible for making the experiment around that solver explicit and reproducible.

---

## What you can do today

OpenTrials currently provides working infrastructure for:

| Capability | What OpenTrials does |
| --- | --- |
| **Virtual populations** | Generate, persist, hash, reload, and verify populations while preserving stable subject lineage. |
| **Mechanistic execution** | Run compatible OSP simulations with model-hash checks, target resolution, assignment read-back, and execution verification. |
| **Population PBPK** | Execute a complete population in batched OSP runs; a 10,000-person path has been live-proven. |
| **Prospective trial arms** | Deterministically allocate participants across declared arms and execute each intervention only against its allocated subjects. |
| **Observation schedules** | Declare solver sampling times and verify that the executed output grid matches them. |
| **Canonical PK results** | Preserve concentration-time results and derive sampled Cmax, earliest Tmax, and linear-trapezoidal AUC0-last under explicit rules. |
| **Cohorts & subgroups** | Define reproducible cohort membership and compare PK outcomes using immutable population-row lineage rather than name-only joins. |
| **Extreme responders** | Select transparent rank/percentile response tails with explicit tie behavior and compare descriptive baseline characteristics. |
| **Uncertainty workflows** | Materialize deterministic uncertainty draws, execute verified perturbations, and persist first-order sensitivity results. |
| **Physiological-state experiments** | Apply typed, evidence-attached physiological overrides and compare the same virtual subjects across states. |
| **Observed evidence** | Capture source identity, licensing/provenance, raw snapshots, transformations, observed datasets, and intended dataset roles. |
| **Validation infrastructure** | Gate prediction-vs-observation comparison on declared compatibility and persist alignments, residuals, endpoints, and metrics. |
| **Research reports** | Produce self-contained Markdown/HTML reports from already-verified artifacts without creating a second analysis engine. |
| **Model onboarding** | Inspect OSP models, discover candidate administration/output paths, and scaffold capability profiles that still require human verification. |

This list describes **implemented software capability**, not scientific validation of every possible model or experiment.

For the release-by-release state and the two remaining external proof gaps, see [`docs/project-status.md`](docs/project-status.md).

---

## The trust model

OpenTrials is built around a simple principle:

> **Do not trust a scientific claim merely because an earlier stage said it happened. Re-verify the artifact that proves it.**

Important boundaries therefore carry explicit identities and verification evidence. Depending on the workflow, OpenTrials records and re-checks things such as:

```text
model file hash
population semantic hash
trial/configuration hash
requested intervention
executed parameter value
solver read-back evidence
raw result hash
canonical result hash
endpoint artifact hash
allocation identity
subject population-row lineage
observation schedule
source evidence identity
transformation provenance
software identity
```

Higher-level artifacts do not simply copy lower-level claims. Their verification paths reopen and verify the underlying artifacts through the corresponding stores. Reports follow the same rule: they render verified results; they are not an alternate source of scientific truth.

This is why OpenTrials has many small immutable artifacts instead of one convenient mutable results object.

---

## Quickstart

### 1. Requirements

You need:

- Python 3.11+;
- [`uv`](https://docs.astral.sh/uv/) for the documented development workflow;
- R with the Open Systems Pharmacology `ospsuite` package;
- the .NET runtime required by `ospsuite`;
- a compatible registered model.

The OpenTrials configuration layer can resolve `Rscript`, `.NET`, and the R library path through CLI flags, environment variables, or `.opentrials.yaml`. The repository has been live-verified on Apple Silicon macOS; other runtime layouts are configurable but have not yet received the same end-to-end platform verification.

See [`docs/quickstart.md`](docs/quickstart.md) for the complete runtime/configuration guide.

### 2. Install for development

```bash
git clone https://github.com/eshkanala/OpenTrials.git
cd OpenTrials
uv sync --all-extras
```

Confirm the CLI:

```bash
uv run opentrials --version
```

### 3. Create a runnable project

```bash
uv run opentrials init
```

This creates a commented `project.yaml` with a runnable reference experiment. Validate it without invoking OSP:

```bash
uv run opentrials validate project.yaml
```

### 4. Run the experiment

```bash
uv run opentrials run project.yaml \
  --r-libs-user /path/to/your/ospsuite/library \
  --verbose
```

Or configure the runtime once in `.opentrials.yaml`:

```yaml
rscript_path: /path/to/Rscript
dotnet_root: /path/to/dotnet
r_libs_user: /path/to/R/library
```

OpenTrials reports real orchestration stages rather than inventing a percentage-complete estimate for work the solver does not expose.

### 5. Generate a report

After a run:

```bash
uv run opentrials report runs/<run-id> \
  --population-root runs/populations \
  --format html
```

The resulting report is self-contained and can include concentration-time figures, PK endpoint summaries, arm comparisons, execution verification, limitations, provenance, and reproducibility information.

A live-tested two-arm example is available at [`examples/aciclovir_dose_comparison.yaml`](examples/aciclovir_dose_comparison.yaml).

---

## Python SDK

The Python SDK is the canonical researcher-facing interface. The CLI is intentionally a thin client over the same layer so a future GUI, notebook integration, or service does not need to reimplement scientific behavior.

```python
import opentrials

project = opentrials.load("project.yaml")
run = project.run(r_libs_user="/path/to/ospsuite/library")

print(run.summary())
print(run.endpoints)

run.verify()
run.report(format="html")
```

For the SDK contract, artifact access, and advanced workflows, see [`docs/sdk.md`](docs/sdk.md).

---

## Model support: registration, not a giant drug database

OpenTrials is intentionally **not** a database containing every drug, every parameter, and every possible biological mechanism.

A mechanistic model remains the source of compound- and physiology-specific behavior. OpenTrials registers what a particular model can safely expose through a `ModelCapabilityProfile`:

```text
ModelCapabilityProfile
├── model identity + hash
├── compound(s)
├── engine
├── supported administration routes
├── mutable intervention targets
├── mutable physiology targets
├── population compatibility
├── available model outputs
├── output → canonical measurement mappings
├── unit expectations
├── provenance
└── explicit capability limitations
```

Generic orchestration asks the profile what is supported rather than encoding drug names into the execution pipeline.

### Inspecting a model

```bash
uv run opentrials model inspect path/to/model.pkml
```

This performs conservative OSP-backed discovery of candidate compounds, administration parameters, and outputs.

To create a profile scaffold:

```bash
uv run opentrials model init path/to/model.pkml
```

The generated scaffold deliberately contains a review guard. Automated discovery is **not** treated as scientific verification.

List registered models with:

```bash
uv run opentrials models list
uv run opentrials models show <model-id>
```

See [`docs/models.md`](docs/models.md) for the model-onboarding philosophy and workflow.

---

## Current reference model

The live-proven reference implementation is an **aciclovir IV PBPK model** bundled with the verified OSP environment. Aciclovir is an antiviral drug; it was useful as the first engineering model because it provided a complete locally executable simulation with inspectable administration parameters, concentration outputs, population support, and renal physiology parameters.

Aciclovir is **not intended to be the architecture**. The model-independent orchestration path consumes capability profiles rather than aciclovir constants.

A second model proof is deliberately still open. The selected candidate is the official OSP Midazolam model, chosen because it stresses the abstraction with a different drug, clearance mechanism, protocol set, and route/formulation behavior. Its upstream snapshot currently requires conversion on a supported Windows/Linux OSP environment before OpenTrials can complete that proof. Details are maintained in [`docs/project-status.md`](docs/project-status.md).

---

## Evidence and scientific validation

OpenTrials distinguishes several questions that are easy to collapse into one:

1. **Did the requested experiment execute reproducibly?**
2. **Did the solver execute what OpenTrials claims it executed?**
3. **Is the observed dataset scientifically compatible with the simulated experiment?**
4. **Was that evidence used for calibration, held-out testing, or external validation?**
5. **Do predictions actually agree with independent human observations?**

The software infrastructure for observed evidence, compatibility gating, exact-time alignment, residuals, endpoint comparison, and immutable validation artifacts exists.

What does **not** exist yet is a qualifying, rights-cleared, genuinely independent human dataset that permits a scientific validation claim for the current reference model. The bundled literature observations used to build/calibrate the model are explicitly treated as calibration evidence rather than recycled as "validation."

That distinction is intentional. OpenTrials would rather report **validation evidence unavailable** than turn convenient data into a misleading validation claim.

See [`docs/limitations.md`](docs/limitations.md) and [`scripts/V0.8_VALIDATION_DATASET_SEARCH.md`](scripts/V0.8_VALIDATION_DATASET_SEARCH.md).

---

## Artifact architecture

A run produces more than a table of numbers. OpenTrials persists an evidence chain.

Representative artifact families include:

```text
population generation
    ↓
OTPGEN   generated population
OTPHYS   derived physiological-state population

trial execution
    ↓
OTALLOC  deterministic arm allocation
OTRES    canonical concentration-time result
OTPK     PK endpoints
OTACMP   cross-arm descriptive comparison
OTTRIAL  top-level prospective-trial provenance

population analysis
    ↓
OTCOH / OTMEM    cohort definitions + membership
OTCPK            cohort PK comparison
OTXMEM / OTXCMP  extreme-response membership + comparison

uncertainty
    ↓
OTUSC    uncertainty scenario
OTUDR    immutable materialized draws
OTUEX    verified draw executions
OTSENS   persisted sensitivity analysis

evidence / validation
    ↓
OTRAW    raw source snapshot
OTOBS    canonical observed dataset
OTCONN   connector provenance
OTVAL    prediction-vs-observation validation result
```

The exact schemas and verification contracts live in code and in [`docs/architecture.md`](docs/architecture.md). The diagram above is an orientation aid, not a replacement for those contracts.

---

## Reproducibility by design

OpenTrials uses several complementary mechanisms rather than relying on a single random seed:

- deterministic population and allocation seeds where applicable;
- immutable content-addressed/identity-bearing artifacts;
- source and semantic SHA-256 hashes;
- model hash pinning;
- explicit units;
- stable subject lineage back to immutable population rows;
- solver parameter read-back before results are accepted;
- declared observation-grid verification;
- source/evidence provenance;
- explicit transformation records;
- strict schema-version matching;
- independently re-verifiable top-level manifests.

A reproducible workflow therefore means more than "the code ran twice." It means OpenTrials can establish what inputs, model, subjects, intervention, outputs, transformations, and software identities produced a result.

---

## Performance

OpenTrials is not limited to toy populations. The optimized OSP CSV transport path has been live-proven on a **10,000-person population**, including result persistence, in approximately **421 seconds** on the development machine used for that benchmark.

The optimization was based on profiling rather than assumptions: OSP's JSON result serialization was the dominant transport cost, while CSV export substantially reduced it. At 10,000 subjects the dominant remaining cost moved to Python-side row processing, which scales approximately linearly and remains a documented optimization opportunity.

The CSV and JSON result transports are not claimed to be byte-identical: OSP's CSV export uses limited textual precision. Endpoint agreement has been empirically bounded within that representation's precision. See [`docs/limitations.md`](docs/limitations.md) for the maintained note.

---

## What OpenTrials does **not** claim

OpenTrials currently does **not** claim:

- clinical validity or patient-specific predictive accuracy;
- regulatory qualification;
- independent human validation of the reference model;
- arbitrary-model compatibility without model registration and verification;
- a second live-proven drug/model yet;
- general disease simulation from a single physiological override;
- support for authoring arbitrary repeated/multi-dose OSP protocols from the current headless R toolchain;
- that automatically discovered model parameters are automatically safe to expose;
- that all advanced capabilities are already available through the top-level CLI/`Project` API;
- schema migration across artifact versions.

The maintained and more detailed limitations page is [`docs/limitations.md`](docs/limitations.md).

---

## Documentation map

The README is intentionally the front door, not the entire project notebook.

| Document | Use it for |
| --- | --- |
| [`docs/quickstart.md`](docs/quickstart.md) | First installation, runtime configuration, first run, first report |
| [`docs/sdk.md`](docs/sdk.md) | Researcher-facing Python API and artifact access |
| [`docs/models.md`](docs/models.md) | Inspecting, registering, and verifying new mechanistic models |
| [`docs/architecture.md`](docs/architecture.md) | Layering, trust boundaries, artifacts, schema/versioning policy |
| [`docs/limitations.md`](docs/limitations.md) | Maintained scientific and engineering limitations |
| [`docs/project-status.md`](docs/project-status.md) | Release progression and current external blockers |
| [`CAPABILITY_AUDIT.md`](CAPABILITY_AUDIT.md) | Capability audit against the founding vision |
| [`V1_READINESS_AUDIT.md`](V1_READINESS_AUDIT.md) | Adoption/release-readiness audit |
| [`OpenTrials — Founding Product & Technical Specification.md`](OpenTrials%20%E2%80%94%20Founding%20Product%20%26%20Technical%20Specification.md) | Original product and technical vision |
| [`HANDOFF.md`](HANDOFF.md) | Detailed chronological engineering record and empirical findings |

---

## Development

Install all development dependencies:

```bash
uv sync --all-extras
```

Run the offline test suite:

```bash
uv run pytest
```

Static checks:

```bash
uv run ruff check src tests scripts
uv run mypy src
```

The OSP integration suite is intentionally opt-in because it requires a functioning local R/`ospsuite`/.NET environment. See the integration tests and contributor guide for the current invocation and runtime expectations.

For contribution workflow, architecture boundaries, and expectations around scientific claims, read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

---

## Design principles

OpenTrials development follows a few rules that matter more than any one feature:

1. **Simulation is not truth.** Execution credibility and scientific validity are separate milestones.
2. **No silent scientific fallbacks.** Unsupported routes, parameters, units, evidence, or model capabilities should fail explicitly.
3. **Preserve raw evidence.** Normalization and analysis create new artifacts; they do not erase the source representation.
4. **Verify at the solver boundary.** A requested parameter value is not accepted as executed merely because OpenTrials sent it.
5. **Preserve subject identity.** Population comparisons use immutable row lineage, not convenient string joins.
6. **Keep analysis descriptive unless the method explicitly supports more.** A difference is not automatically causal or inferential.
7. **Make limitations machine-adjacent.** Important caveats belong in capability profiles, evidence roles, coverage reports, and artifacts—not only prose.
8. **Keep the core solver-independent.** Engine-specific paths belong in adapters; generic orchestration consumes declared capabilities.
9. **Prefer an honest blocker to a fabricated capability.** Several roadmap items are intentionally open because the required model, evidence, rights, or upstream API does not yet exist.

---

## Contributing

OpenTrials is Apache-2.0 licensed and welcomes research, engineering, documentation, model-onboarding, reproducibility, and validation contributions.

Particularly valuable contributions include:

- additional rights-cleared mechanistic model registrations;
- reproducible model-conversion workflows;
- rights-cleared independent PK datasets and evidence connectors;
- cross-platform OSP runtime verification;
- SDK/CLI exposure for advanced existing capabilities;
- artifact migration tooling;
- performance work backed by profiling;
- documentation and reproducibility improvements.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

---

## License

OpenTrials is licensed under the [Apache License 2.0](LICENSE).

Third-party models, datasets, and solver components may have their own licenses and usage conditions. A source being publicly downloadable does not automatically make its model or numeric data redistributable; OpenTrials treats those rights as part of provenance rather than assuming them.

---

## Project maturity

`v1.0.0-rc.1` is a **research software release candidate**, not a declaration that every scientific objective in the founding specification has been achieved.

The internal release-readiness blockers identified by the v1 audit—project licensing, public runtime configurability, and stale capability documentation—have been addressed. Two high-value external proofs remain open: a second genuinely different live model and a qualifying independent human validation dataset.

That is the current boundary: OpenTrials has a substantial, live-tested virtual-trial engineering stack and a deliberately conservative scientific claim surface. Final `v1.0.0` should strengthen that evidence, not merely add more features.
