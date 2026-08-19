# Converting OSP snapshot models when working on macOS

OpenTrials can execute registered OSP models on macOS when they are available as directly loadable simulation files such as `.pkml`. A separate limitation applies to **PK-Sim snapshot projects** (`.json` snapshots): the snapshot-conversion path in the currently verified `ospsuite` stack is not usable on macOS.

This page documents the workaround that was used to convert the official Open Systems Pharmacology Midazolam model for OpenTrials' second-model proof.

## The limitation

The official OSP compound-model repositories commonly distribute PK-Sim models as snapshot `.json` files rather than ready-to-run `.pkml` simulations.

On the macOS environment used to develop OpenTrials, two snapshot-loading paths were tested directly:

- `runSimulationsFromSnapshot()` explicitly refuses to run on Darwin/macOS.
- `loadProjectFromSnapshot()` reaches the native backend but crashed with exit code `139` when exercised against the real Midazolam snapshot.

This is an upstream runtime/tooling limitation, not an OpenTrials model-registration rule. OpenTrials does not attempt to bypass or emulate the unsupported snapshot backend on macOS.

## Supported workaround

Perform the snapshot-to-PKML conversion in a supported Linux or Windows OSP environment, then bring the resulting immutable `.pkml` simulation into the normal OpenTrials model-inspection and registration workflow.

For the Midazolam proof, OpenTrials used an **ephemeral GitHub Actions Linux runner** rather than requiring a dedicated second machine:

```text
Official OSP snapshot (.json)
        │
        ▼
GitHub Actions / Ubuntu 24.04
        │
        ▼
OSP snapshot conversion
        │
        ▼
exported .pkml simulations
        │
        ▼
SHA-256 verification
        │
        ▼
OpenTrials model inspect
        │
        ▼
reviewed ModelCapabilityProfile
        │
        ▼
generic OpenTrials execution
```

The temporary conversion workflow was removed after the conversion completed so it would not become permanent CI infrastructure for a one-time model-preparation task. The workflow remains recoverable from repository history if needed.

## What the conversion environment needs

Use a Linux or Windows environment that can run the OSP snapshot conversion stack. For the successful Linux conversion, the environment was based on `ubuntu-24.04` and installed the required R, `ospsuite`, .NET, and rSharp/runtime dependencies before invoking the snapshot conversion.

Three environment issues were discovered empirically during the Midazolam conversion:

1. **Ubuntu/.NET package compatibility matters.** The initial runner choice did not match the available .NET package path; the final successful job used Ubuntu 24.04.
2. **Verify the .NET runtime actually requested by rSharp.** Published setup guidance and observed runtime behavior did not initially agree. Treat the runtime's own error/output as authoritative and install the version it actually requires.
3. **Allow enough workflow time.** Converting a complete snapshot may export many simulations. The Midazolam snapshot contained 37 declared simulations, so the conversion job needed a longer timeout than the initial attempt.

Do not weaken model verification simply to make a conversion job pass. A successful conversion should produce an independently hashable output that can be inspected by OpenTrials afterward.

## Provenance requirements

Treat the converted `.pkml` as a **derived execution artifact**, not as though it were the upstream-distributed model.

Record at minimum:

```text
upstream repository / publisher
upstream release or tag
upstream model filename
upstream model license
input snapshot SHA-256
conversion date
conversion operating system
R version
ospsuite version
.NET/rSharp runtime versions
conversion command or script revision
selected exported simulation
output PKML SHA-256
```

This preserves the relationship:

```text
upstream scientific model
        ↓
reproducible format conversion
        ↓
derived executable PKML
        ↓
OpenTrials capability registration
```

A format conversion does **not** itself establish that an administration target, output path, population capability, or other model feature is scientifically appropriate for OpenTrials. Those mappings must still be inspected and verified.

## After conversion

Once the `.pkml` file is available on the macOS development machine, return to the standard OpenTrials onboarding flow.

Inspect the converted simulation:

```bash
uv run opentrials model inspect path/to/model.pkml \
  --r-libs-user /path/to/ospsuite
```

Generate a review scaffold if appropriate:

```bash
uv run opentrials model init path/to/model.pkml \
  --model-id your.model.id \
  --r-libs-user /path/to/ospsuite
```

Then verify the discovered mappings live before registration. See [`models.md`](models.md) for the complete model-onboarding process.

## Midazolam precedent

OpenTrials' second-model generalization proof followed this exact route with the official GPL-2.0 Open Systems Pharmacology Midazolam model:

- the upstream snapshot was converted on an ephemeral Ubuntu GitHub Actions runner;
- all 37 declared simulations were exported successfully;
- the target oral tablet simulation was selected and hash-verified;
- the resulting `.pkml` was inspected live rather than populated with assumed paths;
- its capability profile was registered through the existing generic model architecture;
- the model executed through the same generic OpenTrials pipeline used by the aciclovir reference model;
- the second model exposed one real hidden generic assumption, which was corrected generically rather than with Midazolam-specific branching.

This precedent demonstrates that a macOS researcher does not need to abandon OpenTrials when an upstream OSP model is distributed only as a snapshot. The conversion can be isolated to a supported environment while day-to-day OpenTrials execution and model work remain on macOS.

## Future direction

A future shared OpenTrials model registry could distribute provenance-pinned, rights-compatible execution packages derived from upstream models so individual researchers do not need to repeat format conversion. Until that infrastructure exists, the supported-environment conversion plus explicit provenance record is the recommended workflow.
