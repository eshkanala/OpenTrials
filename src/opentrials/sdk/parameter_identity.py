"""A small, hand-curated canonical vocabulary for reusable PK parameter concepts.

Registry v0.2's own research pass confirmed there is no existing "canonical
parameter name" concept anywhere in this project: ``compound.CompoundIdentity``
already has ``synonyms``/``external_identifiers`` for *compounds*, but nothing
analogous exists for *parameters* (a source might report "CLr", "renal CL",
or "Renal Clearance" for the same underlying concept). This module is that
missing piece -- deliberately small and hand-curated (mirroring
``sdk.registry.default_model_registry()``'s own "the one place a new X
becomes reachable" composition pattern), not a general free-text taxonomy:
every canonical identity this project recognizes is listed here explicitly,
with a reference unit used only to validate that a reported value's unit is
*dimensionally compatible* -- never to silently convert or overwrite what a
source actually reported (see ``core.scientific_value.ScientificValue.to()``,
reused as-is for any conversion a caller explicitly asks for).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from opentrials.core.units import unit_registry


class ParameterIdentity(BaseModel):
    """One canonical PK/PD parameter concept and every alias it is known by."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_id: str = Field(min_length=1, description="e.g. 'renal_clearance'.")
    aliases: tuple[str, ...] = Field(
        default=(), description="Case-insensitive alternate names, e.g. ('CLr', 'renal CL')."
    )
    reference_unit: str = Field(
        min_length=1, description="A unit dimensionally representative of this concept."
    )
    description: str = Field(min_length=1)


PARAMETER_IDENTITIES: tuple[ParameterIdentity, ...] = (
    ParameterIdentity(
        canonical_id="renal_clearance",
        aliases=("CLr", "renal CL", "renal clearance", "CL_renal"),
        reference_unit="L/hour",
        description="Renal (kidney-mediated) clearance of a compound from plasma.",
    ),
    ParameterIdentity(
        canonical_id="hepatic_clearance",
        aliases=("CLh", "hepatic CL", "hepatic clearance", "CL_hepatic"),
        reference_unit="L/hour",
        description="Hepatic (liver-mediated) clearance of a compound from plasma.",
    ),
    ParameterIdentity(
        canonical_id="total_clearance",
        aliases=("CL", "CL_total", "systemic clearance", "total body clearance"),
        reference_unit="L/hour",
        description="Total systemic clearance of a compound from plasma.",
    ),
    ParameterIdentity(
        canonical_id="volume_of_distribution",
        aliases=("Vd", "Vss", "volume of distribution", "apparent volume of distribution"),
        reference_unit="L",
        description="The apparent volume a compound would need to occupy to account for "
        "the observed plasma concentration, given the total amount in the body.",
    ),
    ParameterIdentity(
        canonical_id="volume_of_distribution_per_kg",
        aliases=("Vd/kg", "VDss", "volume of distribution per kg", "weight-normalized Vd"),
        reference_unit="L/kg",
        description="Volume of distribution normalized to body weight -- a distinct "
        "canonical concept from absolute Vd, not interconvertible without a specific "
        "subject's body weight.",
    ),
    ParameterIdentity(
        canonical_id="total_clearance_per_kg",
        aliases=("CL/kg", "weight-normalized clearance", "clearance per kg"),
        reference_unit="L/hour/kg",
        description="Total systemic clearance normalized to body weight -- a distinct "
        "canonical concept from absolute clearance, not interconvertible without a "
        "specific subject's body weight.",
    ),
    ParameterIdentity(
        canonical_id="elimination_half_life",
        aliases=("t1/2", "half-life", "elimination half-life", "terminal half-life"),
        reference_unit="hour",
        description="The time for plasma concentration to fall by half during elimination.",
    ),
    ParameterIdentity(
        canonical_id="plasma_protein_binding_fraction",
        aliases=("protein binding", "fraction bound", "plasma protein binding", "fu"),
        reference_unit="dimensionless",
        description="The fraction of a compound bound to plasma proteins (0-1, or reported "
        "as a percent and convertible to a fraction).",
    ),
    ParameterIdentity(
        canonical_id="oral_bioavailability",
        aliases=("F", "bioavailability", "oral bioavailability", "fraction absorbed"),
        reference_unit="dimensionless",
        description="The fraction of an orally administered dose that reaches systemic "
        "circulation unchanged.",
    ),
)

_BY_CANONICAL_ID = {identity.canonical_id: identity for identity in PARAMETER_IDENTITIES}
_BY_ALIAS = {
    alias.strip().lower(): identity
    for identity in PARAMETER_IDENTITIES
    for alias in (identity.canonical_id, *identity.aliases)
}


def parameter_identity(canonical_id: str) -> ParameterIdentity:
    """Look up a known canonical identity by its own id -- raises if unrecognized."""
    try:
        return _BY_CANONICAL_ID[canonical_id]
    except KeyError as error:
        raise ValueError(f"Unknown canonical parameter identity: {canonical_id!r}.") from error


def resolve_parameter_alias(raw_name: str) -> ParameterIdentity | None:
    """Resolve a source-reported parameter name to a known canonical identity, if any.

    Case-insensitive, exact-alias matching only -- deliberately no fuzzy
    string matching, matching this project's "no fuzzy inference" discipline
    already established for Registry candidate matching (see
    ``sdk.registry_match``'s own module docstring).
    """
    return _BY_ALIAS.get(raw_name.strip().lower())


def check_unit_compatible(canonical_id: str, unit: str) -> None:
    """Raise ``ValueError`` if ``unit`` is not dimensionally compatible with this concept.

    Never converts or overwrites the reported unit -- only confirms a
    reported value could not possibly be this concept (e.g. rejects a
    volume unit reported for a clearance).
    """
    identity = parameter_identity(canonical_id)
    reference_dimensionality = unit_registry.Unit(identity.reference_unit).dimensionality
    reported_dimensionality = unit_registry.Unit(unit).dimensionality
    if reported_dimensionality != reference_dimensionality:
        raise ValueError(
            f"Unit {unit!r} is not dimensionally compatible with "
            f"{canonical_id!r} (expected dimensionality of {identity.reference_unit!r})."
        )
