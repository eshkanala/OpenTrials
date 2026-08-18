# OpenTrials

OpenTrials is an open-source, reproducible computational-medicine platform for virtual clinical-trial research. It is **for research and educational use only** and is not a clinical decision-making system.

## Current phase

**v0.1 — Execution credibility** is functionally complete for one deliberately narrow, local OSP engineering workflow: a single virtual individual receiving aciclovir 250 mg IV over 10 minutes through the package-bundled `Vergin 1995 IV` model. OpenTrials hash-pins the model, verifies the structural IV target and parameter read-back before solver execution, preserves raw output, creates canonical PK artifacts, and reports Cmax, Tmax, and AUC₀-last. This is not scientific or clinical validation.

**v0.2 — Scientific credibility** (0.2-A through 0.2-C complete) adds an immutable observed-evidence system, a strict trial/study compatibility gate, and a validation engine producing exact alignment/residual/endpoint/metric comparisons and immutable validation artifacts. **0.2-D — an independent rights-cleared human dataset — remains open**; no validation claim against real humans exists yet.

**v0.3 — Uncertainty** declares parameter-uncertainty scenarios, materializes deterministic draws, executes them through verified OSP with full solver-state read-back, and produces persisted sensitivity-ranking artifacts. This is an engineering demonstration using dose as a verified perturbation variable, not a biological/parameter-uncertainty claim.

**v0.4 — Population response** (tagged `v0.4.0-alpha.1`) executes a whole verified generated population through OSP PBPK in one batched, lineage-preserving call; supports immutable cohort/subgroup membership and descriptive PK comparisons between them; and identifies transparent percentile/rank extreme responders with descriptive baseline-characteristic comparisons against a reference group. No machine-learning selection, no causal language anywhere in a persisted artifact.

**v0.5 — Trial arms & protocol structure** (tagged `v0.5.0-alpha.1`) executes a real prospective multi-arm trial: a population is deterministically allocated across two or more declared arms (largest-remainder apportionment + seeded assignment), each arm's own verified intervention is executed against *only* its assigned participants, and an optional declared observation schedule controls the solver's actual output time grid (read back and verified, not merely requested). Per-arm outcomes are compared descriptively, and the complete run is recorded as one immutable, independently re-verifiable `OTTRIAL-*` provenance artifact. Repeated/multi-dose regimens remain an explicit `BLOCKED_EXTERNAL_CAPABILITY`: the installed `ospsuite` R API has no function to author or edit a dosing protocol, only to mutate parameters on one already built elsewhere (PK-Sim's GUI, unavailable in this headless toolchain), and no available rights-cleared model has a native multi-application protocol.

**None of v0.2 through v0.5's capabilities are wired into the CLI yet** — the `opentrials run`/`validate` commands below cover only the original v0.1 single-individual workflow. Everything from v0.2 onward (observed evidence, uncertainty, population execution, cohorts, extreme responders, multi-arm trials) is accessed through the Python API; see `HANDOFF.md`'s dated entries and `tests/integration/` for exact, live-verified usage examples.

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
