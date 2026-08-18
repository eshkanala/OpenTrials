---
name: Bug report
about: Something in OpenTrials didn't behave the way its own documentation/tests say it should
title: ""
labels: bug
---

## What happened

A clear description of the incorrect behavior.

## What you expected

What should have happened instead, and (if relevant) which existing test,
docs page, or `HANDOFF.md` entry led you to expect that.

## Steps to reproduce

```bash
# The exact commands you ran, including any project.yaml/model file content
# needed to reproduce this.
```

## Environment

- OpenTrials commit/version:
- Python version:
- OS:
- Did this involve real OSP execution? If so: `ospsuite` version, R
  version, .NET version (`opentrials models show <model_id>` and your
  `ospsuite::sessionInfo()` output are both useful here).

## Relevant output

```text
Paste the full error/traceback, or the relevant portion of a report/
run manifest, here.
```

## Anything else

Is this reproducible with the opt-in live OSP suite
(`OPENTRIALS_RUN_OSP_INTEGRATION=1 ... pytest -m osp_integration`), or only
in your own workflow?
