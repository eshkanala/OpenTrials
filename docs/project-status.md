# Project status

This document tracks the current release state of OpenTrials without turning the main README into a changelog.

## Current release

**Current release candidate:** `v1.0.0-rc.1`

OpenTrials is feature-complete enough for a release-candidate cycle, but two external scientific/generalization proofs remain intentionally open before a final `v1.0.0` release is considered.

## Release progression

| Release | Primary capability | Status |
| --- | --- | --- |
| v0.1 | Verified mechanistic execution, canonical PK results, immutable run artifacts | Complete |
| v0.2 | Observed-evidence contracts, compatibility gating, validation engine | Core complete; independent human proof still open |
| v0.3 | Deterministic uncertainty draws, verified propagation, sensitivity artifacts | Complete |
| v0.4 | Batched population PBPK, cohorts, subgroup comparisons, extreme responders | Complete |
| v0.5 | Prospective multi-arm trials, deterministic allocation, verified observation schedules | Complete |
| v0.6 | Physiological-state overrides, paired state trials, 10,000-person execution path | Complete |
| v0.7 | Generic model capability profiles and model-independent orchestration | Architecture complete; second live model externally blocked |
| v0.8 | Evidence connector framework and immutable source provenance | Connector framework complete; independent validation evidence externally blocked |
| v0.9 | Public SDK, thin CLI, verified reports, model onboarding, OSS readiness | Complete |
| v1.0.0-rc.1 | Release-readiness fixes: license, runtime configuration, versioning, audits | Tagged |

## What is live-proven today

The strongest end-to-end path is the registered OSP aciclovir IV model. Through that path OpenTrials has live-proven:

- deterministic virtual-population generation and immutable population artifacts;
- hash-pinned model identity and capability registration;
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
- SDK, CLI, self-contained HTML/Markdown reporting, and conservative OSP model inspection/scaffolding.

These are software and simulation-behavior claims. They are **not** claims of clinical accuracy.

## External blocker 1 — second live model

The generic model architecture no longer contains aciclovir-specific logic in the paths intended to be model-independent, but only one real model has been live-proven through the full stack.

The selected second model is the official GPL-2.0 Open Systems Pharmacology Midazolam model. It is intentionally a difficult generalization test because it differs from aciclovir in compound, clearance mechanism, protocols, route/formulation coverage, and upstream model packaging.

The upstream model is distributed as a PK-Sim snapshot rather than a ready `.pkml`. On the currently verified macOS OSP runtime, snapshot conversion is externally blocked: the supported snapshot-run path refuses Darwin and the lower-level project-loading path was empirically observed to segfault. A reproducible Windows/Linux conversion procedure is stored in [`scripts/convert_midazolam_snapshot.R`](../scripts/convert_midazolam_snapshot.R) and is ready to run.

No second-model capability is claimed until that converted model is inspected, registered, and live-proven through the existing generic path.

## External blocker 2 — independent human validation evidence

OpenTrials has an observed-evidence model, strict trial/study compatibility checks, prediction/observation alignment, residual/endpoint metrics, and immutable validation artifacts. What it does not yet have is a rights-cleared, scientifically compatible, genuinely independent human PK dataset for the currently registered model.

The bundled Vergin observations are correctly treated as calibration evidence, not validation evidence. The independently sourced Laskin candidate cannot be represented honestly from the available record because dosing is weight-normalized without recoverable subject weight, and no substitute open-licensed point-level aciclovir IV dataset was found in the documented search.

The full search record is maintained internally.

## Important current limitations

See [`limitations.md`](limitations.md) for the maintained list. The most important current boundaries are:

- research and educational use only; no clinical decision support;
- no independent human validation claim yet;
- only one live-proven registered mechanistic model;
- repeated/multi-dose protocol authoring is not supported by the current headless OSP toolchain;
- some advanced workflows remain Python-API-only rather than exposed through the top-level `Project` SDK/CLI path;
- persisted schemas currently use strict exact-version matching and have no migration toolchain yet.

## Why the project remains conservative

OpenTrials deliberately distinguishes **what was requested**, **what the external engine actually executed**, **what evidence supports a value**, and **what a result does not prove**. Unsupported or ambiguous model capabilities are rejected rather than guessed. This policy is why several roadmap items remain explicitly blocked instead of being represented as completed features.
