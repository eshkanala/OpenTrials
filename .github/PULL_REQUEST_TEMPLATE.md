## What this changes and why

## Scope

What's covered, and — just as important — what's deliberately **not**
covered by this PR. This project's own history (`HANDOFF.md`) treats an
honest scope boundary as more valuable than an overclaimed one; do the
same here.

## Checks run

- [ ] `uv run ruff check src tests`
- [ ] `uv run mypy src`
- [ ] `uv run pytest`
- [ ] Opt-in live OSP suite (`OPENTRIALS_RUN_OSP_INTEGRATION=1 ... pytest -m
      osp_integration`), if this touches `adapters/osp/`, `orchestration/`,
      or a model capability profile — or note here that you don't have a
      local OSP install and a maintainer should run it.

## Documentation

- [ ] `HANDOFF.md` and/or `README.md` updated, if this changes what the
      project can do.
- [ ] `docs/` updated, if this changes a researcher-facing workflow.

## Anything a reviewer should look at closely

