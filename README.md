# OpenTrials

OpenTrials is an open-source, reproducible computational-medicine platform for virtual clinical-trial research. It is **for research and educational use only** and is not a clinical decision-making system.

## Current phase

This repository is beginning **Phase 0 — Foundation**. The current work establishes typed, unit-aware scientific domain objects, evidence/provenance foundations, reproducibility contracts, and solver adapter boundaries before any medical simulation is implemented.

The founding architecture is documented in [`OpenTrials — Founding Product & Technical Specification.md`](OpenTrials%20%E2%80%94%20Founding%20Product%20%26%20Technical%20Specification.md). Ongoing project context is maintained in [`HANDOFF.md`](HANDOFF.md).

## Development setup

```bash
python -m pip install -e ".[dev]"
pytest
```

## Scope guardrails

- Every important scientific quantity carries units and provenance-capable metadata.
- Simulation is not treated as truth; validation against observation is central.
- The core package remains independent of OSP, R, databases, web servers, and GPU tooling.
- OSP and other external solvers will be optional adapters.
- No clinical-use, patient-specific, diagnostic, or safety claims are supported.
