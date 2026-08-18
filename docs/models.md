# Models

OpenTrials executes trials against a *registered model* — a
`ModelCapabilityProfile` declaring what one specific, hash-pinned model
file actually supports: compounds, administration routes and their
mutable parameters, verified physiology targets, canonical output
mappings, and explicit reasoned gaps (`unsupported_capabilities`). This
page covers what's registered today, and the path from "I have a PKML
file" to "it's registered and trustworthy."

## What's registered right now

```bash
uv run opentrials models list
uv run opentrials models show osp.aciclovir.vergin-1995-iv
```

As of this writing, exactly one model is registered: the pinned
Aciclovir IV model bundled with `ospsuite` (`models/profiles/aciclovir_iv.py`).
`opentrials models show` prints its full declared capability — compounds,
administration routes, physiology targets, outputs, and what it
explicitly does *not* support and why (e.g. repeated dosing — `ospsuite`'s
R API has no dosing-protocol-authoring function at all, confirmed by
enumerating every exported function; see `HANDOFF.md`'s v0.5 entry).

If `project.yaml` doesn't declare a `model_id`, OpenTrials resolves it
automatically *only* when exactly one model is registered — with more
than one, you must be explicit.

## Bringing in a new model: discover, then scaffold, then verify

This is a deliberately three-step, human-in-the-loop process. Nothing
here auto-registers a model — see `HANDOFF.md`'s v0.7-C entry for why
that discipline matters (a second-model proof failed for months on an
external tooling blocker, and the project chose to stay blocked rather
than fake a proof).

### 1. Inspect

```bash
uv run opentrials model inspect path/to/your-model.pkml --r-libs-user /path/to/ospsuite
```

Reads the real PKML file through OSP and reports what it can discover:
molecule/compound names, administration event containers and their
mutable dose/timing parameter paths, candidate output paths, a total
mutable-parameter count, and whether the model looks population-compatible.

**This is discovery, not verification.** The tool tells you what OSP
*could* let you touch — not that a given parameter is scientifically
appropriate to touch, or that a candidate output path is the right one to
report. The report ends with `OpenTrials verified mappings: 0` for
exactly this reason: nothing has been reviewed yet.

### 2. Scaffold

```bash
uv run opentrials model init path/to/your-model.pkml --model-id your.model.id --r-libs-user /path/to/ospsuite
```

Runs the same discovery pass and writes a `ModelCapabilityProfile`
scaffold — a Python file, not a registration. It pre-fills only what
discovery found genuinely unambiguous (a single discovered dose/
start-time/infusion-duration path, the file's own SHA-256), and marks
everything requiring real scientific judgment with `# TODO REQUIRED
REVIEW` — units, which compound a discovered molecule maps to, which of
possibly hundreds of candidate output paths is correct, which doses are
actually worth trusting.

The generated file **refuses to import** — it raises `NotImplementedError`
at the top — until you delete that line. You can't accidentally skip the
review step; the file won't even load.

### 3. Verify and register

Open the scaffold. For every `REQUIRED REVIEW` item: execute the model
live with that parameter, read back what OSP actually did, and only keep
the value once you've watched it work — the same discipline every
already-registered profile in this project was built under (see
`models/profiles/aciclovir_iv.py` for a finished example, and its own
drift-guard/live tests for what "verified" looks like in practice).

Once reviewed, add your profile to `sdk/registry.py`'s
`default_model_registry()` so it's reachable from the SDK and CLI.

## Where this is headed

`sdk/registry.py`'s `default_model_registry()` is deliberately the *only*
place a new profile needs to be added today — a local, in-process
registry backed by hand-verified Python modules. The generic
`ModelCapabilityRegistry` type it uses (`models/registry.py`) knows
nothing about specific profiles by design, so this local registry can
later be swapped for a networked one (a shared OpenTrials registry
serving verified compound properties, model profiles, and parameter
mappings other labs have already validated) without redesigning the
interface. That shared registry does not exist yet, and building it is
explicitly out of scope for now — this local one is what makes it
possible to add later without a rewrite.
