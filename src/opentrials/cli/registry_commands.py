"""`opentrials registry ...` command implementations.

Deliberately thin, same rule as the rest of the CLI: parse arguments, call
the SDK (``sdk.registry``, ``sdk.registry_seed``), render the result.
"""

from __future__ import annotations

import argparse

from opentrials.config.runtime import resolve_osp_runtime
from opentrials.registry import RegistryError, RegistryRecordKind
from opentrials.sdk.parameter_evidence_seed import seed_parameter_evidence
from opentrials.sdk.registry import default_registry_backend
from opentrials.sdk.registry_seed import seed_default_registry


def registry_seed(arguments: argparse.Namespace) -> int:
    runtime = resolve_osp_runtime(
        rscript_path=arguments.rscript_path,
        dotnet_root=arguments.dotnet_root,
        r_libs_user=arguments.r_libs_user,
    )
    backend = default_registry_backend(arguments.root)
    registered = seed_default_registry(backend, r_libs_user=runtime.r_libs_user)
    registered_parameters = seed_parameter_evidence(backend)
    total = registered + registered_parameters
    if not total:
        print("Registry already seeded -- nothing new to register.")
        return 0
    if registered:
        print(f"Registered {len(registered)} record(s):")
        for logical_id in registered:
            print(f"  {logical_id}")
    if registered_parameters:
        print(f"\nRegistered {len(registered_parameters)} real, cited parameter value(s):")
        for logical_id in registered_parameters:
            print(f"  {logical_id}")
    if runtime.r_libs_user is None:
        print(
            "\nNote: skipped the Vergin 1995 dataset (needs real OSP) -- set "
            "--r-libs-user, R_LIBS_USER, or r_libs_user in a config file, and re-run."
        )
    return 0


def registry_list(arguments: argparse.Namespace) -> int:
    backend = default_registry_backend(arguments.root)
    kind = RegistryRecordKind(arguments.kind.upper()) if arguments.kind else None
    manifests = backend.list(kind)
    if not manifests:
        print("No registry records found.")
        return 0
    print("Registered records\n")
    for manifest in manifests:
        print(f"  {manifest.logical_id}")
        print(f"    kind            {manifest.kind.value}")
        print(f"    record_id       {manifest.record_id}")
        print(f"    version         {manifest.version}")
        print(f"    evidence_class  {manifest.evidence_class.value}")
        print(f"    license         {manifest.license}")
    print(f"\n{len(manifests)} record(s). See `opentrials registry show <logical_id>` for detail.")
    return 0


def registry_show(arguments: argparse.Namespace) -> int:
    backend = default_registry_backend(arguments.root)
    try:
        manifest, payload = backend.get_latest(arguments.logical_id)
        backend.verify(manifest.record_id)
    except RegistryError as error:
        print(f"Unknown or unverifiable registry entry: {error}")
        return 1

    print(f"Registry entry: {manifest.logical_id}\n")
    print(f"Record ID        {manifest.record_id}")
    print(f"Kind             {manifest.kind.value}")
    print(f"Version          {manifest.version}")
    print(f"Evidence class   {manifest.evidence_class.value}")
    print(f"License          {manifest.license}")
    print(f"Source           {manifest.source.kind}: {manifest.source.identifier}")
    if manifest.compatibility is not None and manifest.compatibility.model_ids:
        print(f"Applies to       {', '.join(manifest.compatibility.model_ids)}")
    if manifest.superseded_id:
        print(f"Supersedes       {manifest.superseded_id}")
    print(f"Created          {manifest.created_at.isoformat()}")
    print("\nPayload (verified against re-derived hash):")
    print(payload.model_dump_json(indent=2, exclude_none=True))
    return 0
