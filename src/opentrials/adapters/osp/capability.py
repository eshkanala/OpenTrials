"""Translate a generic ``ModelCapabilityProfile`` into OSP-specific shapes.

The one place this project is allowed to bridge the generic
``models.capability`` types and OSP's own ``adapters.osp.intervention``
types -- an adapter, unlike ``models``, is allowed to know about both. This
keeps every other OSP module (``engine.py``, orchestration) working from
the profile rather than reaching back into ``models.profiles.*`` constants
directly.
"""

from __future__ import annotations

from opentrials.adapters.osp.intervention import (
    OspAdministrationTarget,
    OspCompoundMapping,
    OspInterventionProfile,
)
from opentrials.models.capability import ModelCapabilityProfile


def osp_intervention_profile_from_capability(
    profile: ModelCapabilityProfile,
) -> OspInterventionProfile:
    """Build the OSP intervention-translation profile from a capability profile.

    Every compound and administration route the model declares is carried
    over unchanged; this performs no capability decision of its own.
    """
    return OspInterventionProfile(
        compound_mappings=tuple(
            OspCompoundMapping(
                opentrials_compound_id=compound.compound_id,
                osp_molecule_id=compound.engine_molecule_id,
            )
            for compound in profile.compounds
        ),
        administration_targets=tuple(
            OspAdministrationTarget(
                target_id=administration.target_id,
                osp_molecule_id=_engine_molecule_id_for(profile, administration.compound_id),
                route=administration.route,
                dose_parameter_path=administration.dose_parameter_path,
                dose_unit=administration.dose_unit,
                administration_time_parameter_path=(
                    administration.administration_time_parameter_path
                ),
                administration_time_unit=administration.administration_time_unit,
                infusion_duration_parameter_path=administration.infusion_duration_parameter_path,
                infusion_duration_unit=administration.infusion_duration_unit,
            )
            for administration in profile.administrations
        ),
    )


def _engine_molecule_id_for(profile: ModelCapabilityProfile, compound_id: str) -> str:
    for compound in profile.compounds:
        if compound.compound_id == compound_id:
            return compound.engine_molecule_id
    raise ValueError(
        f"Administration target references compound_id {compound_id!r}, which is not "
        f"declared in this profile's compounds."
    )
