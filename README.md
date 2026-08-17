# OpenTrials

OpenTrials is an open-source, reproducible computational-medicine platform for virtual clinical-trial research. It is **for research and educational use only** and is not a clinical decision-making system.

## Current phase

**v0.1 — Execution credibility** is functionally complete for one deliberately narrow, local OSP engineering workflow: a single virtual individual receiving aciclovir 250 mg IV over 10 minutes through the package-bundled `Vergin 1995 IV` model. OpenTrials hash-pins the model, verifies the structural IV target and parameter read-back before solver execution, preserves raw output, creates canonical PK artifacts, and reports Cmax, Tmax, and AUC₀-last.

This is not scientific or clinical validation. **v0.2 — Scientific credibility** begins with observed-data ingestion, experiment compatibility checks, and held-out/external comparison against human evidence.

The founding architecture is documented in [`OpenTrials — Founding Product & Technical Specification.md`](OpenTrials%20%E2%80%94%20Founding%20Product%20%26%20Technical%20Specification.md). Ongoing project context is maintained in [`HANDOFF.md`](HANDOFF.md).

## Development setup

```bash
uv sync --all-extras
uv run pytest
```

### Supported IV engineering run

The local OSP path requires the official framework R installation, `ospsuite`, .NET, and the R package library described in [`HANDOFF.md`](HANDOFF.md). On the verified macOS environment:

```bash
R_LIBS_USER=/Users/eshkanala/Library/R/arm64/4.6/library \
uv run opentrials run examples/aciclovir_iv/trial.yaml --output-root runs
```

This command supports only the explicitly labeled IV engineering example. The original oral aciclovir example remains blocked pending a compatible, rights-cleared oral model.

## Scope guardrails

- Every important scientific quantity carries units and provenance-capable metadata.
- Simulation is not treated as truth; validation against observation is central.
- The core package remains independent of OSP, R, databases, web servers, and GPU tooling.
- OSP and other external solvers are optional adapters; the current OSP workflow is deliberately local and constrained.
- No clinical-use, patient-specific, diagnostic, or safety claims are supported.
