# Architecture overview

```text
Scientific core (core/, compound/, patient/, trials/, physiology/, ...)
        v
Adapters (adapters/osp/ -- the one place engine-specific knowledge lives)
        v
Orchestration (orchestration/ -- verified execution, one workflow per capability)
        v
Public SDK (sdk/ -- the canonical researcher-facing interface)
        v
   +---------+------------------+
   |   CLI   |   Future GUI     |
   +---------+------------------+
```

## The rule this project is built around

**Core domain objects never depend on OSP.** Anything under `core/`,
`compound/`, `patient/`, `trials/`, `physiology/`, or `models/capability.py`
imports only from each other — never from `adapters.*`. All OSP-specific
translation (turning a generic `Intervention`/`ModelCapabilityProfile`
into OSP paths and parameter assignments) lives entirely in `adapters/osp/`.
This is what let v0.7 generalize the execution pipeline away from a single
hard-coded compound without touching the domain model at all, and it's
the constraint every new adapter (a future non-OSP engine, a future
shared registry client) should be built under.

**The public SDK is the canonical programmatic interface.** `sdk/` is the
only thing the CLI (`cli/`) is allowed to depend on for behavior — the
CLI parses arguments, calls the SDK, and renders the result, with no
scientific logic of its own (`cli/main.py`'s own module docstring states
this explicitly). A future GUI is expected to be a second such client of
the exact same SDK, not a parallel implementation.

**Every artifact is immutable and independently re-verifiable.** Nothing
in `storage/` ever overwrites a persisted artifact; every store's
`verify_*()` method re-derives a content hash from the actual persisted
bytes and compares it against what a manifest claims, rather than
trusting the manifest. Higher-level provenance records (`OTTRIAL`,
`OTPHYTRIAL`, `OTCONN`) compute nothing themselves — they reference every
sub-artifact's own id and hash, and their own `verify_*()` re-verifies the
whole chain from each sub-artifact's own store. `reporting/` extends this
same discipline one layer further: a report is built by re-deriving and
re-verifying the whole artifact chain from disk, never by trusting a live
object.

## Where each layer lives

| Layer | Path | What it owns |
|---|---|---|
| Domain/core | `core/`, `compound/`, `patient/`, `trials/`, `physiology/`, `models/capability.py` | Engine-agnostic scientific types. Never imports `adapters.*`. |
| Model registry | `models/registry.py`, `models/profiles/` | What models are registered and what they declare they support. |
| Adapters | `adapters/osp/` | The only place OSP-specific paths, R workers, and translation logic live. |
| Orchestration | `orchestration/` | One module per verified execution capability (population execution, trial execution, physiology runs, uncertainty, evidence ingestion). Each composes storage + adapters + domain types into one immutable, re-verifiable run. |
| Storage | `storage/` | Immutable artifact persistence and verification, one store per artifact family. |
| Analysis | `analysis/` | Shared, reused statistics (PK endpoints, descriptive summaries, arm comparisons). `reporting/` calls these directly rather than recomputing anything. |
| SDK | `sdk/` | The public, researcher-facing interface (`Project`, `run_trial`, `run_population`, `Run`, model onboarding, reporting convenience methods). |
| Reporting | `reporting/` | Human-readable views over already-verified artifacts. Never a second analysis engine. |
| CLI | `cli/` | A thin renderer over `sdk/`. No scientific logic. |

## Schema versioning and compatibility

Every persisted artifact and configuration document carries its own
`schema`/`schema_version` (see `core.serialization.SchemaDocument`), and
every loader that reads one — `config.project.load_project`,
`config.trial.load_trial`, every OSP worker request/response, every
artifact manifest — checks it with an exact-match comparison and raises
if it doesn't match exactly. There is currently no tolerant/partial
reader and no migration tooling: **a future schema version bump will make
existing artifacts and configuration files written under the current
version unreadable by the new code, with no automated upgrade path.**

This is a deliberate, stated tradeoff for this stage of the project, not
an oversight: strict-match rejection is what makes "verified" mean
something (a manifest is either exactly what the code that reads it
expects, or the read fails loudly) — silently tolerating a drifted schema
would be a correctness risk, not a convenience. As OpenTrials' schemas
stabilize toward a real 1.0 compatibility guarantee, this should become
an explicit, tested migration policy (old-version readers, or versioned
upgrade scripts) rather than staying an open question. Until then: do not
assume a `runs/` or `populations/` directory produced by one tagged
version will still validate against a later one, and pin your OpenTrials
version if you need a persisted artifact tree to keep validating over
time.

## Reading the codebase for the first time

Start at `docs/quickstart.md`, run it, then read (in this order):
`models/capability.py` (what a model declares), one orchestration module
that interests you (`orchestration/trial_execution.py` is the most
complete), its corresponding `storage/` artifact type, and finally
`sdk/project.py`/`sdk/run.py` to see how they compose. `HANDOFF.md`'s
dated entries are the authoritative record of *why* each capability is
shaped the way it is — read the entry for whatever module you're looking
at before changing it.
