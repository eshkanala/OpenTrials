"""Bind OSP population-execution IndividualIds to verified OTPGEN row lineage.

This is the one place raw OSP execution identity crosses into OpenTrials
population provenance. It never trusts row position: every ``IndividualId``
returned by the solver is resolved by exact VALUE lookup against the already
population-verified table, and any ID absent from either side is a hard
failure rather than a silent partial join.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from opentrials.cohort.evaluator import source_row_sha256
from opentrials.storage.endpoints import PkEndpointSubjectLineage
from opentrials.storage.populations import PopulationArtifactManifest


def resolve_population_execution_lineage(
    population_manifest: PopulationArtifactManifest,
    population_columns: Sequence[str],
    population_rows: Sequence[Mapping[str, object]],
    result_individual_ids: Sequence[int],
) -> dict[str, PkEndpointSubjectLineage]:
    """Return one ``PkEndpointSubjectLineage`` per OSP result IndividualId.

    ``population_columns``/``population_rows`` must already be the exact,
    verified table backing ``population_manifest`` (for example from
    ``PopulationArtifactStore.verify_population()`` plus a Parquet read of
    that same artifact); this function performs no population verification
    of its own. It requires the OSP result's IndividualId set to equal the
    population table's IndividualId set exactly -- no extra IDs, none
    missing -- since a partial population execution result would otherwise
    silently under-represent the population in any later cohort comparison.
    """
    if "IndividualId" not in population_columns:
        raise ValueError(
            "Population table has no IndividualId column to resolve lineage against."
        )

    id_to_row_index: dict[int, int] = {}
    for row_index, row in enumerate(population_rows):
        raw_id = row.get("IndividualId")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int):
            raise ValueError(f"Population row {row_index} has a non-integer IndividualId.")
        if raw_id in id_to_row_index:
            raise ValueError(f"Population table has a duplicate IndividualId: {raw_id}.")
        id_to_row_index[raw_id] = row_index

    result_ids = list(result_individual_ids)
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("OSP population execution result has duplicate IndividualId values.")
    result_id_set = set(result_ids)
    population_id_set = set(id_to_row_index)

    unmatched = sorted(result_id_set - population_id_set)
    if unmatched:
        raise ValueError(
            "OSP execution result contains IndividualId(s) absent from the verified population "
            f"table: {unmatched!r}."
        )
    missing = sorted(population_id_set - result_id_set)
    if missing:
        raise ValueError(
            "Population row IndividualId(s) are missing from the OSP execution result: "
            f"{missing!r}."
        )

    lineage: dict[str, PkEndpointSubjectLineage] = {}
    for individual_id in result_ids:
        row_index = id_to_row_index[individual_id]
        row_hash = source_row_sha256(population_columns, population_rows[row_index])
        lineage[str(individual_id)] = PkEndpointSubjectLineage(
            source_generation_id=population_manifest.generation_id,
            source_population_semantic_sha256=(
                population_manifest.individuals.semantic_content_sha256
            ),
            source_population_row_index=row_index,
            source_population_row_sha256=row_hash,
        )
    return lineage
