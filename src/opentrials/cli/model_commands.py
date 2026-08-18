"""`opentrials model ...` / `opentrials models ...` command implementations.

Deliberately thin, same rule as the rest of the CLI: parse arguments, call
the SDK (``sdk.registry``, ``sdk.model_onboarding``), render the result.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from opentrials.config.runtime import resolve_osp_runtime
from opentrials.models.registry import UnknownModelCapabilityError
from opentrials.sdk.model_onboarding import (
    ModelInspectionReport,
    generate_profile_scaffold,
    inspect_model,
)
from opentrials.sdk.registry import default_model_registry


def models_list(_arguments: argparse.Namespace) -> int:
    registry = default_model_registry()
    model_ids = registry.model_ids()
    if not model_ids:
        print("No models are registered.")
        return 0
    print("Registered models\n")
    for model_id in model_ids:
        profile = registry.get(model_id)
        manifest = profile.package.manifest
        print(f"  {model_id}")
        print(f"    engine   {manifest.engine}")
        print(f"    version  {manifest.version}")
        print(f"    routes   {', '.join(a.route.value for a in profile.administrations)}")
    print(f"\n{len(model_ids)} model(s). See `opentrials models show <model_id>` for detail.")
    return 0


def models_show(arguments: argparse.Namespace) -> int:
    registry = default_model_registry()
    try:
        profile = registry.get(arguments.model_id)
    except UnknownModelCapabilityError as error:
        print(f"Unknown model: {error}")
        return 1

    manifest = profile.package.manifest
    print(f"Model: {manifest.id}\n")
    print(f"Engine           {manifest.engine}")
    print(f"Version          {manifest.version}")
    print(f"License          {manifest.license}")
    print(f"Applicability    {', '.join(manifest.applicability.species)}")
    print(f"Artifact hash    {profile.package.artifact_hash}")

    print("\nCompounds")
    for compound in profile.compounds:
        print(f"  {compound.compound_id}  (engine molecule: {compound.engine_molecule_id})")

    print("\nAdministrations")
    for administration in profile.administrations:
        doses = ", ".join(f"{d:g}" for d in administration.supported_doses) or "(none declared)"
        print(f"  [{administration.target_id}] {administration.route.value}")
        print(f"    compound          {administration.compound_id}")
        print(f"    dose path         {administration.dose_parameter_path}")
        print(f"    supported doses   {doses} {administration.supported_dose_unit or ''}")

    print("\nPhysiology targets")
    if not profile.physiology_targets:
        print("  (none declared)")
    for target in profile.physiology_targets:
        print(f"  {target.target}  ({target.parameter_path})")

    print("\nOutputs")
    for output in profile.outputs:
        print(f"  {output.output_id}: {output.analyte} {output.measurement} ({output.unit})")
        print(f"    {output.parameter_path}")

    if profile.unsupported_capabilities:
        print("\nExplicitly unsupported")
        for item in profile.unsupported_capabilities:
            print(f"  {item.capability}: {item.reason}")
    return 0


def model_inspect(arguments: argparse.Namespace) -> int:
    runtime = resolve_osp_runtime(
        rscript_path=arguments.rscript_path,
        dotnet_root=arguments.dotnet_root,
        r_libs_user=arguments.r_libs_user,
    )
    try:
        report = inspect_model(
            arguments.pkml_path,
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Inspection failed: {error}")
        return 1

    _print_inspection_report(report)
    print(f"\nNext:\n  opentrials model init {arguments.pkml_path}")
    return 0


def model_init(arguments: argparse.Namespace) -> int:
    runtime = resolve_osp_runtime(
        rscript_path=arguments.rscript_path,
        dotnet_root=arguments.dotnet_root,
        r_libs_user=arguments.r_libs_user,
    )
    try:
        report = inspect_model(
            arguments.pkml_path,
            r_libs_user=runtime.r_libs_user,
            rscript_path=runtime.rscript_path,
            dotnet_root=runtime.dotnet_root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Inspection failed: {error}")
        return 1

    scaffold = generate_profile_scaffold(report, model_id=arguments.model_id)
    output_path: Path = arguments.output or Path(f"{_slug(report.name)}_profile.py")
    output_path.write_text(scaffold, encoding="utf-8")

    print(f"Scaffold written: {output_path}\n")
    print("This is a starting point, not a registered model. Open the file, read every")
    print("REQUIRED REVIEW comment, verify each value against a real execution, then")
    print("delete the NotImplementedError guard at the top before using it.")
    return 0


def _print_inspection_report(report: ModelInspectionReport) -> None:
    print("OpenTrials Model Inspection\n")
    print(f"File             {report.pkml_path}")
    print(f"Hash             {report.pkml_sha256}")
    print(f"Simulation name  {report.name}\n")

    print("Compound(s) discovered")
    for name in report.molecule_names:
        print(f"  {name}")

    print("\nAdministration candidates")
    for administration in report.administrations:
        print(f"  {administration.container}")
        for role, path in administration.roles.items():
            print(f"    {role:<20} {path}")
        unclassified = [
            path
            for path in administration.parameter_paths
            if path not in administration.roles.values()
        ]
        if unclassified:
            print(f"    ({len(unclassified)} other parameter path(s) in this container)")

    print(f"\nOutputs               {len(report.output_paths)} candidate path(s) discovered")
    for path in report.output_paths[:5]:
        print(f"  {path}")
    if len(report.output_paths) > 5:
        print(f"  ... and {len(report.output_paths) - 5} more")

    print(f"\nMutable parameters    {report.mutable_parameter_count} discovered")
    print(
        "Population support    "
        + ("detected" if report.population_support_detected else "not detected")
    )
    print("OpenTrials verified mappings   0 (nothing here has been reviewed yet)")
    print("\n⚠ Discovery does not imply OpenTrials capability verification.")


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
