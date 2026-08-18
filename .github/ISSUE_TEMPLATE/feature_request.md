---
name: Feature / capability request
about: Propose a new OpenTrials capability, model, or workflow
title: ""
labels: enhancement
---

## What you're trying to do

The research question or workflow this would support — be concrete; "add
model X" or "support Y kind of trial design" is more actionable than a
general capability wish.

## What exists today

Have you checked `opentrials models list`, `docs/sdk.md`, and
`HANDOFF.md`'s dated entries for something close to this already? Link
whatever's closest, and explain the gap.

## Proposed shape

If you have one: what would the SDK/CLI surface for this look like? Does
it fit the existing layering (`docs/architecture.md`) — e.g. does it
belong in `orchestration/` as a new verified execution capability, or is
it a view/report over existing artifacts (`reporting/`)?

## Scientific verification needed

Most new capabilities in this project require a live-OSP capability probe
before any code is written (see e.g. `HANDOFF.md`'s v0.6-A entry). What
would need to be verified against real OSP before this could be built
honestly, rather than assumed?

## Are you willing to work on this

Let us know if you'd like to submit a PR yourself.
