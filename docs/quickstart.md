# Quickstart

A 5-minute path from a fresh checkout to your first executed virtual trial
and a report you can hand to someone else. Every command below is real and
has been run against actual OSP output — this page is not aspirational.

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).
- A local installation of `ospsuite` for R, and the .NET runtime it
  requires. OpenTrials does not bundle or install OSP for you — see
  `HANDOFF.md`'s "external-runtime reminder" section for the exact
  versions this project has been verified against.
- The path to your `ospsuite` R library (you'll pass this as
  `--r-libs-user`, or set it once as the `R_LIBS_USER` environment
  variable).

**Platform note**: this project has only actually been run and verified on
macOS (Apple Silicon). OpenTrials' own defaults for the `Rscript` binary
and the .NET runtime root are compiled in against that one macOS layout.
If yours differs — a different macOS install location, Linux, Windows, or
an HPC module system — three overrides exist, checked in this order
(most specific wins): a CLI flag, an environment variable, then a config
file:

| Setting        | CLI flag         | Environment variable      |
| -------------- | ---------------- | -------------------------- |
| Rscript path   | `--rscript-path` | `OPENTRIALS_RSCRIPT_PATH`  |
| .NET root      | `--dotnet-root`  | `OPENTRIALS_DOTNET_ROOT`   |
| R library path | `--r-libs-user`  | `R_LIBS_USER`               |

For a setting you want to stop passing every time, put it in a config
file: `.opentrials.yaml` in your working directory, `~/.config/opentrials/config.yaml`,
or any path named by `OPENTRIALS_CONFIG`:

```yaml
rscript_path: /usr/lib/R/bin/Rscript
dotnet_root: /usr/lib/dotnet
r_libs_user: /home/researcher/R/library
```

These overrides are new and unit-tested (`config.runtime.resolve_osp_runtime`),
but the resulting non-macOS *execution* path through real OSP has not
itself been re-verified on Linux or Windows — if you hit a platform-specific
OSP/R issue after pointing these at a real install, that is an OSP/R
environment problem this project has not yet reproduced, not a silent
failure of the override mechanism itself.

## Install

```bash
git clone <this repository>
cd OpenTrials
uv sync
```

Everything below assumes commands run through `uv run`, or with
`.venv/bin/` on your `PATH`.

## 1. Create a project

```bash
uv run opentrials init
```

This writes a working `project.yaml` in the current directory — a single
arm, 10-person population, 250 mg IV aciclovir, one PK endpoint. Open it;
every field is commented. Nothing here is a placeholder you must fill in
before it runs — it already does.

## 2. Validate it

```bash
uv run opentrials validate project.yaml
```

Prints a pass/fail summary of the trial, the model it resolves to, the
population, and the endpoints — without touching OSP or executing
anything.

## 3. Run it

```bash
uv run opentrials run project.yaml --r-libs-user /path/to/your/ospsuite/library
```

This generates a real population through OSP, immutably persists it,
executes the declared intervention, and prints a live stage-by-stage
progress transcript followed by a summary of the resulting PK endpoints.
Add `--verbose` to see the concrete facts behind each stage (population
counts, verified hashes, read-back doses) as they happen, not just
checkmarks.

The run's artifacts land under `runs/<run-id>/` — immutable, hash-verified,
and independently re-checkable (see [`sdk.md`](sdk.md) for what "verified"
actually means here).

## 4. Get a report

```bash
uv run opentrials report runs/<run-id> --population-root runs/populations --format html
```

Produces a single, self-contained `report.html` — concentration-time
curves, PK endpoint tables, execution-verification status, provenance,
and the exact command to reproduce it — that you can open in a browser,
email, or archive with nothing else needed. See
[`interpreting reports vs. artifacts`](sdk.md#reports-vs-artifacts) for
why the report and the underlying `runs/` directory serve different
purposes and neither replaces the other.

## Try a real two-arm comparison

`examples/aciclovir_dose_comparison.yaml` is a live-tested, two-arm
(125 mg vs. 250 mg IV) dose comparison — the same file this project's own
live test suite runs against real OSP. Run it the same way:

```bash
uv run opentrials run examples/aciclovir_dose_comparison.yaml --r-libs-user /path/to/ospsuite --verbose
```

## Next

- [`docs/models.md`](models.md) — what models are registered, and how to
  bring a new one in.
- [`docs/sdk.md`](sdk.md) — using OpenTrials from Python directly, and
  what the immutable artifacts under `runs/` actually mean.
- [`docs/limitations.md`](limitations.md) — what this project does not
  yet do, stated plainly.
