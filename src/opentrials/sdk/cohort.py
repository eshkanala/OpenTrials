"""Researcher-facing cohort/subgroup definition and PK comparison.

Thin wrappers over ``cohort.storage``/``cohort.comparison`` -- every
scientific decision (predicate evaluation, strict lineage-based endpoint
matching) still happens there, unchanged. Cohort membership needs no OSP
execution at all: it is a pure filter over an already-generated, verified
population, using the standard registered field catalog for raw OSP
population tables (``adapters.osp.osp_population_field_catalog``) rather
than requiring a caller to hand-build one.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from opentrials.adapters.osp import osp_population_field_catalog
from opentrials.cohort import (
    CohortDefinition,
    CohortKind,
    CohortMembershipArtifactManifest,
    CohortMembershipArtifactStore,
    CohortPkComparisonResult,
    OverlapPolicy,
    compare_cohort_pk_endpoints,
)
from opentrials.cohort.definitions import Predicate
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.populations import PopulationArtifactStore


def define_and_persist_cohort(
    *,
    predicates: tuple[Predicate, ...],
    population_generation_id: str,
    population_root: str | Path,
    membership_root: str | Path,
    kind: CohortKind = CohortKind.COHORT,
    parent_membership_id: str | None = None,
    cohort_id: str | None = None,
    membership_id: str | None = None,
) -> CohortMembershipArtifactManifest:
    """Define a cohort/subgroup against a verified population and persist its membership.

    Binds the definition to the population's own re-verified hash and the
    standard OSP field catalog automatically -- a caller only supplies the
    predicates, not the provenance plumbing.
    """
    resolved_population_root = Path(population_root)
    population_store = PopulationArtifactStore(resolved_population_root)
    population_manifest = population_store.verify_population(population_generation_id)
    catalog = osp_population_field_catalog()

    definition = CohortDefinition(
        cohort_id=cohort_id or f"OTCOH-{uuid.uuid4().hex}",
        kind=kind,
        predicates=predicates,
        source_generation_id=population_generation_id,
        source_population_semantic_sha256=(
            population_manifest.individuals.semantic_content_sha256
        ),
        field_catalog_sha256=catalog.canonical_sha256(),
        parent_membership_id=parent_membership_id,
    )

    membership_store = CohortMembershipArtifactStore(
        Path(membership_root), population_store=population_store
    )
    resolved_membership_id = membership_id or f"OTMEM-{uuid.uuid4().hex}"
    membership_store.create_membership(resolved_membership_id)
    return membership_store.write_membership(
        resolved_membership_id, definition=definition, field_catalog=catalog
    )


def compare_cohorts(
    *,
    group_a_membership_id: str,
    group_b_membership_id: str,
    group_a_label: str,
    group_b_label: str,
    endpoint_id: str,
    membership_root: str | Path,
    population_root: str | Path,
    endpoint_root: str | Path,
    overlap_policy: OverlapPolicy = OverlapPolicy.ALLOWED_AND_REPORTED,
) -> CohortPkComparisonResult:
    """Compare two persisted cohort memberships' PK endpoint outcomes.

    Both memberships and the endpoint artifact must already exist --
    membership from ``define_and_persist_cohort``, the endpoint artifact
    from a completed ``sdk.population.run_population``/``sdk.trial.run_trial``
    execution. Every subject match is strict lineage identity, never
    ``subject_id`` text (see ``cohort.comparison``'s own module docstring).
    """
    population_store = PopulationArtifactStore(Path(population_root))
    membership_store = CohortMembershipArtifactStore(
        Path(membership_root), population_store=population_store
    )
    endpoint_store = PkEndpointArtifactStore(Path(endpoint_root))
    return compare_cohort_pk_endpoints(
        group_a_membership_id=group_a_membership_id,
        group_b_membership_id=group_b_membership_id,
        group_a_label=group_a_label,
        group_b_label=group_b_label,
        endpoint_id=endpoint_id,
        membership_store=membership_store,
        endpoint_store=endpoint_store,
        overlap_policy=overlap_policy,
    )
