"""Conservative model onboarding: discover, scaffold, never auto-certify.

``inspect_model()`` reports exactly what OSP itself can discover about a
PKML file -- nothing here decides whether a discovered path is scientifically
appropriate to use. ``generate_profile_scaffold()`` turns one inspection
into a *starting point* for a ``ModelCapabilityProfile``, not a finished,
registered one: the generated file refuses to import until a researcher
has reviewed it and removed an explicit guard, mirroring how every other
registered profile in this project (``models/profiles/aciclovir_iv.py``)
was built from hand-verified facts, never assumed ones.

    PKML file
        v
    inspect_model()          -- read-only discovery
        v
    generate_profile_scaffold() -- a file to review, not a registration
        v
    researcher edits + verifies
        v
    registered via sdk.registry
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from opentrials.adapters.osp.inspect_model import inspect_model_pkml


class AdministrationDiscovery(BaseModel):
    """One discovered ``Events|...|`` container and its own parameter paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    container: str = Field(min_length=1)
    parameter_paths: tuple[str, ...] = Field(min_length=1)
    roles: dict[str, str] = Field(default_factory=dict)


class ModelInspectionReport(BaseModel):
    """Everything discovered about one PKML file -- facts, not conclusions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pkml_path: Path
    pkml_sha256: str = Field(min_length=1)
    name: str = Field(min_length=1)
    molecule_names: tuple[str, ...] = ()
    administrations: tuple[AdministrationDiscovery, ...] = ()
    output_paths: tuple[str, ...] = ()
    mutable_parameter_count: int = Field(ge=0)
    population_support_detected: bool = False
    ospsuite_version: str = Field(min_length=1)
    r_version: str = Field(min_length=1)


def inspect_model(pkml_path: Path, *, r_libs_user: str | None = None) -> ModelInspectionReport:
    """Discover a PKML file's structure through real OSP -- no interpretation."""
    pkml_path = Path(pkml_path)
    payload = inspect_model_pkml(pkml_path, r_libs_user=r_libs_user)
    pkml_sha256 = "sha256:" + hashlib.sha256(pkml_path.read_bytes()).hexdigest()

    administrations = tuple(
        AdministrationDiscovery(
            container=str(item["container"]),
            parameter_paths=tuple(str(p) for p in item["parameter_paths"]),
            roles={str(k): str(v) for k, v in item.get("roles", {}).items()},
        )
        for item in payload.get("administrations", [])
    )

    return ModelInspectionReport(
        pkml_path=pkml_path,
        pkml_sha256=pkml_sha256,
        name=str(payload["name"]),
        molecule_names=tuple(str(m) for m in payload.get("molecule_names", [])),
        administrations=administrations,
        output_paths=tuple(str(p) for p in payload.get("output_paths", [])),
        mutable_parameter_count=int(payload["mutable_parameter_count"]),
        population_support_detected=bool(payload.get("population_support_detected", False)),
        ospsuite_version=str(payload["ospsuite_version"]),
        r_version=str(payload["r_version"]),
    )


def generate_profile_scaffold(
    report: ModelInspectionReport,
    *,
    model_id: str,
    variable_name: str | None = None,
) -> str:
    """Render a reviewable ``ModelCapabilityProfile`` scaffold from a discovery report.

    Deliberately not directly usable: the generated module raises
    ``NotImplementedError`` at import time until a researcher deletes that
    guard, which only makes sense after they have actually reviewed every
    ``# TODO`` below -- discovered facts are pre-filled where they are
    genuinely unambiguous (a single discovered dose/time/duration path,
    the file's own hash), and left as placeholders everywhere real
    scientific judgment is required (units, which compound a discovered
    molecule name maps to, which of possibly many candidate output paths
    is the right one, dose values actually worth trusting).
    """
    variable_name = variable_name or "MODEL_CAPABILITY_PROFILE"
    administration = report.administrations[0] if report.administrations else None
    dose_path = administration.roles.get("dose") if administration else None
    start_time_path = administration.roles.get("start_time") if administration else None
    infusion_path = administration.roles.get("infusion_duration") if administration else None

    compound_candidates = ", ".join(report.molecule_names) or "(none discovered)"
    output_candidates = "\n".join(f"#   - {path}" for path in report.output_paths[:15])
    if len(report.output_paths) > 15:
        output_candidates += f"\n#   ... and {len(report.output_paths) - 15} more"

    container_literal = (
        repr(administration.container) if administration else '"TODO_container_path"'
    )
    dose_path_literal = repr(dose_path) if dose_path else '"TODO_dose_parameter_path"'
    start_time_literal = (
        repr(start_time_path) if start_time_path else '"TODO_administration_time_parameter_path"'
    )
    infusion_literal = repr(infusion_path) if infusion_path else "None"

    return f'''"""Capability profile scaffold for {report.name!r} -- REVIEW BEFORE USE.

Generated by `opentrials model init` from a live discovery pass against:
    {report.pkml_path}
    sha256: {report.pkml_sha256}
    ospsuite {report.ospsuite_version}, R {report.r_version}

This is a starting point, not a finished profile. Every value below came
from automatic discovery except where marked REQUIRED REVIEW -- discovery
finds *candidates*, it does not verify that they are scientifically
appropriate to use. Follow the same discipline every other profile in
this project was built under: execute this model live, read back what
OSP actually did, and only keep a value here once you have watched it
work. See models/profiles/aciclovir_iv.py for a finished example.
"""

from __future__ import annotations

raise NotImplementedError(
    "This is a generated scaffold, not a reviewed profile. Read every "
    "REQUIRED REVIEW comment below, verify each value against a real "
    "execution, then delete this line."
)

from opentrials.compound.intervention import Route  # noqa: E402
from opentrials.models.capability import (  # noqa: E402
    AdministrationCapability,
    CompoundCapability,
    ModelCapabilityProfile,
    OutputCapability,
)
from opentrials.models.manifest import Applicability, ModelManifest, ModelType  # noqa: E402
from opentrials.models.package import ModelPackage  # noqa: E402

# Discovered molecule names in this file: {compound_candidates}
# REQUIRED REVIEW: which one is the compound you intend to simulate, and
# what is OpenTrials' own compound_id for it (lowercase, e.g. "aciclovir")?
COMPOUND_ID = "TODO_compound_id"
ENGINE_MOLECULE_ID = "TODO_engine_molecule_name"

{variable_name} = ModelCapabilityProfile(
    package=ModelPackage(
        manifest=ModelManifest(
            id={model_id!r},
            version="TODO_model_version",
            model_type=ModelType.PBPK,
            engine="osp",
            inputs=("intervention",),
            outputs=("plasma_concentration",),  # TODO REQUIRED REVIEW: match your chosen output
            units={{"plasma_concentration": "TODO_unit"}},
            applicability=Applicability(species=("human",)),  # TODO REQUIRED REVIEW
            license="TODO_license",  # REQUIRED REVIEW: what rights do you actually have?
        ),
        artifact_uri="file://{report.pkml_path}",
        artifact_hash={report.pkml_sha256!r},
        parameter_set_id="TODO_parameter_set_id",
        parameter_hash={report.pkml_sha256!r},
        package_hash={report.pkml_sha256!r},
    ),
    compounds=(
        CompoundCapability(compound_id=COMPOUND_ID, engine_molecule_id=ENGINE_MOLECULE_ID),
    ),
    administrations=(
        AdministrationCapability(
            target_id="TODO_target_id",
            compound_id=COMPOUND_ID,
            route=Route.INTRAVENOUS,  # TODO REQUIRED REVIEW: confirm the actual route
            administration_container_path={container_literal},
            dose_parameter_path={dose_path_literal},
            dose_unit="TODO_unit",  # REQUIRED REVIEW: read this back from a real execution
            administration_time_parameter_path={start_time_literal},
            administration_time_unit="TODO_unit",
            infusion_duration_parameter_path={infusion_literal},
            infusion_duration_unit="TODO_unit",  # or None if no infusion_duration_parameter_path
            supported_doses=(),  # TODO REQUIRED REVIEW: only doses you have actually verified
            supported_dose_unit="TODO_unit",
        ),
    ),
    physiology_targets=(),  # Not discovered automatically -- see physiology/overrides.py
    outputs=(
        OutputCapability(
            output_id="TODO_output_id",
            parameter_path="TODO_output_parameter_path",  # REQUIRED REVIEW: pick one from below
            analyte=COMPOUND_ID,
            matrix="TODO_matrix",
            fraction="TODO_fraction",
            measurement="concentration",
            unit="TODO_unit",
            time_unit="TODO_unit",
        ),
    ),
    unsupported_capabilities=(),
)

# Candidate output paths discovered ({len(report.output_paths)} total, first 15 shown):
{output_candidates}
'''
