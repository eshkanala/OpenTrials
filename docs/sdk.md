# Using OpenTrials from Python

The CLI is a thin renderer over the public `opentrials.sdk` package (also
importable directly as `opentrials.load`/`Project`/`run_trial`/
`run_population`) — everything the CLI can do, the SDK can do, plus
unmediated access to every underlying artifact.

## The basic shape

```python
import opentrials

project = opentrials.load("project.yaml")
run = project.run(output_root="runs", r_libs_user="/path/to/ospsuite")

run.summary()        # printable text summary
run.endpoints         # flattened (arm_id, subject_id, endpoint_type, value, unit) records
run.population         # generation_id, participant_count
run.verify()           # re-verify the whole persisted chain from each artifact's own store
run.report()           # build a ReportData -- see reporting below
```

`project.run()` resolves the registered model, generates or reuses a
population, and routes automatically: two or more declared arms go
through `sdk.trial.run_trial` (a real allocated, multi-arm comparison);
exactly one arm goes through `sdk.population.run_population` (one dose,
the whole population). These are two genuinely different existing
capabilities, not an SDK-invented distinction — see
`orchestration/trial_execution.py` and `orchestration/population_execution.py`
for what each one actually verifies.

## Descending past the summary

`run.artifacts` exposes the full underlying orchestration result and
every raw artifact store — population manifests, per-arm endpoint stores,
comparison stores, the trial-run provenance record itself:

```python
run.artifacts.execution              # the raw TrialExecutionRun/PopulationExecutionRun
run.artifacts.population_store       # PopulationArtifactStore, rooted at this run's population_root
run.artifacts.endpoint_stores        # {arm_id: PkEndpointArtifactStore}
run.artifacts.trial_run_store        # TrialRunArtifactStore (trial runs only)
```

This is deliberate: "simple by default, transparent when requested."
Nothing about `.summary()`/`.endpoints` hides information — it's a
readable *view*, and the full typed, hash-verified artifacts are always
one attribute away.

## Interpreting artifacts vs. reports {#reports-vs-artifacts}

These serve different purposes and neither replaces the other:

- **Artifacts** (everything under `runs/<run-id>/`) are the *authoritative
  scientific record* — immutable, content-hashed, independently
  re-verifiable from each artifact's own store, and the only thing this
  project ever computes a new statistic against.
- **Reports** (`opentrials report`, or `run.report()`) are *views over
  already-verified artifacts* — Markdown or self-contained HTML, meant to
  be read by a human or handed to a colleague. A report never computes a
  new number: every value it shows was already produced and verified by
  an artifact store, or by the exact same shared analysis function
  (`analysis.descriptive.calculate_descriptive_summary`) every other
  comparison in this project already uses. See `reporting/build.py`'s own
  module docstring for the full discipline.

If a report and the artifacts it was built from ever disagree, the
artifacts are correct — `build_trial_report()`/`build_population_report()`
re-derive every value from disk, re-verifying the whole chain each time,
precisely so a report can never silently drift from what was actually
executed.

## Reproducibility

Every persisted run can be independently re-verified without trusting
anything the SDK claimed at the time:

```python
from opentrials.reporting import build_trial_report

# Works from just a run directory + population root -- no live Run object
# needed. Every artifact ID (OTTRIAL-*, OTALLOC-*, per-arm OTRES-*/OTPK-*)
# is re-derived deterministically from the run directory's own name, and
# the registered model is resolved from the manifest's own model_id, not
# a caller-supplied guess.
data = build_trial_report("runs/OTR-trial-...", "runs/populations")
```

This is exactly what `opentrials report <run_directory> --population-root
<path>` does — a report generated from disk today should be identical
(modulo its own generation timestamp) to one generated immediately after
the run finished. `tests/unit/test_reporting_build.py` proves this
directly.

## What's not SDK-wired yet

Physiology-state runs, uncertainty scenarios, cohort/extreme-responder
analysis, and evidence-connector ingestion are real, tested, live-proven
capabilities in this project — but they are reachable only through their
own orchestration modules directly (`orchestration.physiology_trial_execution`,
`orchestration.uncertainty_dose`, `cohort`, `evidence.connector`, etc.),
not yet through `Project`/the CLI. See `tests/integration/` for exact,
live-verified usage examples of each.
