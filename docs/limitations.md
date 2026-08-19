# Limitations and scope

OpenTrials is for research and educational use only. It does not provide
clinical decision support, diagnostic conclusions, or patient-specific
advice, and nothing it produces should be interpreted as a clinical or
regulatory claim. Every result is a computational simulation.

This page states what the project honestly does not yet do, stated
plainly rather than left to be discovered by using it.

## No independent scientific validation exists yet

Every PK result this project produces comes from one pinned model
(the Aciclovir IV PBPK model bundled with `ospsuite`), exercised through
real, verified OSP execution — but **no claim has been made, or can yet
be made, that this model's predictions match independent human data.**
The founding specification's 0.2-D requirement (an independent,
rights-cleared human validation dataset) remains open:

- The one genuinely independent candidate found in this project's search
  (a second bundled observed-PK dataset from a different 1982 study)
  cannot be represented in OpenTrials at all — its dose is reported per
  body weight with no recoverable subject weight, and the domain model
  correctly refuses to accept an invented one.
- A live query against PK-DB's real API and a broader search of open data
  repositories found no independently-deposited, open-licensed, point-level
  aciclovir IV dataset to validate against instead.

See [`docs/project-status.md`](project-status.md) for a summary of that
search.

## Only two models are registered, both from one engine

`opentrials models list` shows two registered models: the aciclovir IV
model (renal clearance) and a Midazolam oral tablet model (hepatic/gut
CYP3A4+UGT1A4 clearance), deliberately chosen to differ from aciclovir on
compound, clearance mechanism, and administration route. Registering the
second model is real, live evidence that the execution pipeline
generalizes, not just that it was refactored to look generic: it
surfaced and fixed one real hard-coded assumption (an intravenous-only
infusion duration silently applied to every dose) that the aciclovir-only
path had never exposed. Both models currently come from the same engine
(`ospsuite`/OSP) — no second simulation engine has ever been integrated,
so the `SimulationEngine` interface's generality across *engines* (as
opposed to models within one engine) remains architecture-only. The
Midazolam snapshot's upstream conversion (`ospsuite`'s PK-Sim
snapshot-conversion backend does not work on macOS) was resolved by
running the conversion on Linux via a temporary GitHub Actions workflow
rather than a manually-provisioned machine — see
[`docs/project-status.md`](project-status.md) for that record.

## Repeated/multi-dose regimens are not supported

`ospsuite`'s R API has no function to author or edit a dosing protocol —
confirmed by enumerating all of its exported functions — only to mutate
parameters on a protocol already built elsewhere (PK-Sim's GUI, which is
unavailable in this project's headless toolchain). Every trial arm is
exactly one verified single administration.

## Uncertainty analysis is an engineering demonstration, not a biological claim

The v0.3 uncertainty/sensitivity capabilities use dose as a verified
perturbation variable to prove the execution/persistence machinery works
end to end. They are not a parameter-uncertainty or biological-variability
claim about aciclovir itself.

## Physiological-state overrides model one verified mechanism, not a disease

The renal glomerular-filtration-rate override is a real, verified
perturbation of one physiological parameter (`Organism|Kidney|GFRmat`) —
it is explicitly **not** a disease-state claim (e.g. chronic kidney
disease). Tubular secretion, renal blood flow, and other renal-clearance
mechanisms are unmodeled; every artifact this capability produces carries
a `PhysiologyCoverageReport` stating this explicitly, and no "CKD"/
"disease" vocabulary appears anywhere in the code.

## Not everything is reachable from the SDK/CLI yet

`Project`/the CLI cover population execution and multi-arm trial
execution. Physiology-state runs, uncertainty scenarios, cohort/extreme-
responder analysis, and evidence-connector ingestion remain Python-API-only
(their own orchestration modules), not yet wired into `Project` or
`opentrials run`. See [`docs/sdk.md`](sdk.md#whats-not-sdk-wired-yet).

## Known precision/scale notes

- The optional CSV transport path (`transport="csv"`) agrees with the
  default JSON path within `exportResultsToCSV()`'s own ~7-significant-
  figure text precision (observed max relative difference 7.58e-09) —
  reported as a bounded approximation, not asserted as byte-identical.
- Python-side row-list processing becomes the dominant cost at very large
  population sizes (~63% of total runtime at N=10,000) — a known,
  explicitly out-of-scope-for-now bottleneck, not a silent one.

## No schema migration path yet

Every persisted artifact and configuration schema is checked with strict
exact-version matching, not tolerant reading — there is no migration
tooling for moving an existing `runs/`/`populations/` directory to a
newer OpenTrials version's schemas. See
[`docs/architecture.md`'s "Schema versioning and compatibility"](architecture.md#schema-versioning-and-compatibility)
for the full policy statement.

## Oral aciclovir is not supported

No rights-cleared, locally available oral aciclovir PBPK model exists;
the registered profile explicitly declares this as an
`unsupported_capabilities` entry, with the reason stated.
