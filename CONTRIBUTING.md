# Contributing to OpenTrials

Thank you for considering contributing. OpenTrials is a research
infrastructure project — for research and educational use only, not for
clinical decision support — and this document covers how to get set up,
what we expect from a change, and how the project is put together.

## Development setup

```bash
git clone <this repository>
cd OpenTrials
uv sync --all-extras
```

You need Python 3.11+ and [`uv`](https://docs.astral.sh/uv/). Most of the
project's own tests do not require OSP itself — only the opt-in live
integration suite does (see below).

## Running the checks CI runs

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest
```

All three must pass before a PR is merged; CI (`.github/workflows/ci.yml`)
runs exactly these three commands. `mypy` is strict (`[tool.mypy]` in
`pyproject.toml`) and scoped to `src/` only — tests are checked more
loosely, matching the rest of this project's convention.

### The opt-in live OSP integration suite

A second test suite (`tests/integration/`, marked `osp_integration`) runs
real trials against a local `ospsuite` R installation and is **not** run
by default or in CI (it depends on an external, licensed runtime this
project cannot install for you). If your change touches anything under
`adapters/osp/`, `orchestration/`, or the model capability profiles, run
it locally before opening a PR:

```bash
OPENTRIALS_RUN_OSP_INTEGRATION=1 OPENTRIALS_OSP_R_LIBS_USER=/path/to/your/ospsuite/library \
  uv run pytest -m osp_integration
```

See `HANDOFF.md`'s "external-runtime reminder" for the exact OSP/R/.NET
versions this project has been verified against. If you don't have a
local OSP install, say so explicitly in your PR rather than skipping this
silently — a maintainer can run it for you.

## Architecture

Read [`docs/architecture.md`](docs/architecture.md) before making a
nontrivial change — in particular, the "core domain objects never depend
on OSP" rule and the "public SDK is the canonical interface, the CLI is a
thin renderer" rule. Both are load-bearing: violating either has real,
project-specific consequences that later milestones depended on.

## What we expect from a change

- **Reuse this project's existing verification discipline.** Every
  immutable artifact type has a `create_*`/`write_*`/`read_manifest`/
  `verify_*` shape (see any file in `storage/`) — new artifact types
  should follow it, not invent a new one.
- **Reuse shared analysis, don't recompute.** `reporting/` and any future
  view/report code must never compute a new statistic — only read what an
  artifact's own verification already confirmed, or call an existing
  shared function (`analysis.descriptive.calculate_descriptive_summary`,
  etc.). See `reporting/build.py`'s own module docstring.
- **Report honest findings, including blockers.** This project's own
  `HANDOFF.md` documents multiple cases where a milestone was stopped
  honestly rather than weakened to a false completion (see the v0.7-C and
  v0.8-B/C entries) — do the same rather than working around a real gap
  silently.
- **No invented scientific values.** If a parameter, unit, or dose can't
  be verified against a real execution or a real source, it doesn't
  belong in committed code — leave it as an explicit `TODO`/gap instead
  (see how `models/profiles/aciclovir_iv.py` and
  `sdk.model_onboarding.generate_profile_scaffold` handle this).
- **Tests that actually exercise the change.** Unit tests should use the
  same monkeypatched-execution pattern already established throughout
  `tests/unit/` (search for `_execute_osp_population` in any existing
  orchestration test for the pattern). If your change touches live OSP
  behavior, add a live test under `tests/integration/` too.

## Commit and PR conventions

- Keep commits coherent — one capability or fix per commit, not a mix.
- PR descriptions should state what changed and why, and call out
  explicitly what was *not* covered if the change is scoped narrower than
  the issue that prompted it.
- Update `HANDOFF.md` and/or `README.md` for anything that changes what
  the project can do — this project treats its handoff log as load-bearing
  documentation, not an afterthought.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Scientific and scope discipline

OpenTrials is for research and educational use only — it does not provide
clinical decision support, diagnostic conclusions, or patient-specific
advice. Contributions must not introduce language, defaults, or examples
that could be read as clinical guidance. See
[`docs/limitations.md`](docs/limitations.md) for the project's current,
honestly-stated scope.
