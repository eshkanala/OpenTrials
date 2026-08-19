# Project status

This document tracks the current release state of OpenTrials without turning the main README into a changelog.

## Current release

**Current release candidate:** `v1.0.0-rc.2`

OpenTrials is feature-complete enough for a release-candidate cycle. The second-model generalization proof (v0.7-C) is complete. The remaining scientific proof — independent human validation evidence — was actively re-searched using Midazolam's substantially larger published PK literature and remains open: no qualifying dataset was found. This is documented, not silently carried forward; see below.

## Release progression

| Release | Primary capability | Status |
| --- | --- | --- |
| v0.1 | Verified mechanistic execution, canonical PK results, immutable run artifacts | Complete |
| v0.2 | Observed-evidence contracts, compatibility gating, validation engine | Core complete; independent human proof still open |
| v0.3 | Deterministic uncertainty draws, verified propagation, sensitivity artifacts | Complete |
| v0.4 | Batched population PBPK, cohorts, subgroup comparisons, extreme responders | Complete |
| v0.5 | Prospective multi-arm trials, deterministic allocation, verified observation schedules | Complete |
| v0.6 | Physiological-state overrides, paired state trials, 10,000-person execution path | Complete |
| v0.7 | Generic model capability profiles and model-independent orchestration | Complete: second live model (Midazolam, oral) registered and live-proven |
| v0.8 | Evidence connector framework and immutable source provenance | Connector framework complete; independent validation evidence externally blocked |
| v0.9 | Public SDK, thin CLI, verified reports, model onboarding, OSS readiness | Complete |
| v1.0.0-rc.1 | Release-readiness fixes: license, runtime configuration, versioning, audits | Tagged |
| v1.0.0-rc.2 | Second live model (Midazolam, oral) registered and live-proven; generic-pipeline bug fixed | Tagged |

## What is live-proven today

Two registered models have been live-proven through the full execution stack: the aciclovir IV model (renal clearance) and a Midazolam oral tablet model (hepatic/gut CYP3A4+UGT1A4 clearance), sharing the same generic orchestration code. Through these paths OpenTrials has live-proven:

- deterministic virtual-population generation and immutable population artifacts;
- hash-pinned model identity and capability registration, across two independently sourced models;
- intervention parameter translation and solver-state read-back verification;
- whole-population batched PBPK execution with preserved subject lineage;
- prospective multi-arm allocation where allocation controls who is actually executed in each arm;
- declared observation schedules verified against the solver output grid;
- canonical concentration-time results plus Cmax, Tmax, and AUC0-last;
- cohort and subgroup comparisons;
- transparent extreme-responder selection and descriptive baseline comparisons;
- deterministic uncertainty-draw materialization, verified propagation, and persisted sensitivity rankings;
- typed physiological-state overrides with paired within-subject comparison across states;
- 10,000-person execution using the optimized CSV result-transport path;
- immutable, independently re-verifiable top-level trial/provenance artifacts;
- SDK, CLI, self-contained HTML/Markdown reporting, and conservative OSP model inspection/scaffolding;
- a real second-model generalization proof: registering an oral, hepatically-cleared model required no new aciclovir-specific branching, and surfaced and fixed one real hard-coded assumption in generic execution code (an intravenous-only infusion duration silently applied to every synthesized dose) that a second, sufficiently different model was needed to expose at all.

These are software and simulation-behavior claims. They are **not** claims of clinical accuracy.

## v0.7-C: second live model, complete

The generic model architecture no longer contains aciclovir-specific logic in the paths intended to be model-independent, and this is now backed by a second live-proven model, not architecture alone.

The selected second model is the official GPL-2.0 Open Systems Pharmacology Midazolam model — chosen deliberately as a difficult generalization test: a different compound, hepatic/gut CYP3A4+UGT1A4 clearance rather than renal filtration, and an oral tablet route rather than IV.

The upstream model is distributed as a PK-Sim snapshot rather than a ready `.pkml`; `ospsuite`'s snapshot-conversion backend does not work on macOS. Rather than provisioning a dedicated machine, the conversion ran on a temporary `ubuntu-24.04` GitHub Actions job using OSP's supported Linux toolchain. Three real environment issues were found and fixed from direct evidence rather than guessed: the wrong Ubuntu version for the available `.NET` apt package, an actual `.NET` runtime-version mismatch between rSharp's published docs and its real runtime behavior, and an insufficient job timeout. All 37 declared simulations converted successfully and the conversion's own verification confirmed the target file's hash.

The temporary workflow was removed after the job completed. The reusable macOS-to-Linux workaround, provenance expectations, and post-conversion onboarding steps are documented in [`macos-osp-snapshot-conversion.md`](macos-osp-snapshot-conversion.md).

The converted model was then inspected live (no invented values), registered as a new capability profile, and executed through the same generic orchestration code the aciclovir path already uses — no changes to that code were needed beyond the one hard-coded-assumption fix noted above, live-proven in `tests/integration/test_midazolam_po_pbpk.py`, with zero regression to the full existing live-OSP suite.

## External blocker: independent human validation evidence

OpenTrials has an observed-evidence model, strict trial/study compatibility checks, prediction/observation alignment, residual/endpoint metrics, and immutable validation artifacts. What it does not yet have is a rights-cleared, scientifically compatible, genuinely independent human PK dataset for either currently registered model.

For aciclovir: the bundled Vergin observations are correctly treated as calibration evidence, not validation evidence. The independently sourced Laskin candidate cannot be represented honestly from the available record because dosing is weight-normalized without recoverable subject weight, and no substitute open-licensed point-level aciclovir IV dataset was found in the documented search.

For Midazolam: the hoped-for wider literature was real (PK-DB alone returns 138 midazolam intervention records across roughly 50 studies, versus zero for aciclovir), but it did not close the gap. The official OSP Midazolam model's own published evaluation report explicitly lists the exact two studies used to verify the registered 10&nbsp;mg oral tablet protocol (Heizmann et al. 1983; Smith et al. 1981) — both directly circular, the same disqualifying pattern as aciclovir's Vergin 1995. The closest independent close-dose candidate found (Link et al. 2008, 7.5&nbsp;mg tablet) was checked in full and disqualified twice over: it is itself one of the model's own calibration studies for that dose, and it reports only aggregate summary statistics, not point-level concentration-time data. No qualifying alternative was found on Zenodo, Dryad, Figshare, or in recent PBPK-methods literature.

Both search records are maintained internally.

## Important current limitations

See [`limitations.md`](limitations.md) for the maintained list. The most important current boundaries are:

- research and educational use only; no clinical decision support;
- no independent human validation claim yet, for either registered model;
- both registered models come from the same simulation engine (OSP) — no second engine has been integrated;
- repeated/multi-dose protocol authoring is not supported by the current headless OSP toolchain;
- some advanced workflows remain Python-API-only rather than exposed through the top-level `Project` SDK/CLI path;
- persisted schemas currently use strict exact-version matching and have no migration toolchain yet.

## Why the project remains conservative

OpenTrials deliberately distinguishes **what was requested**, **what the external engine actually executed**, **what evidence supports a value**, and **what a result does not prove**. Unsupported or ambiguous model capabilities are rejected rather than guessed. This policy is why several roadmap items remain explicitly blocked instead of being represented as completed features.
