"""Join independently-executed physiology states' endpoint artifacts for comparison.

Unlike ``trials.arm_comparison`` (different subjects across arms, tied
together by one shared OTALLOC), every physiology state here is executed
against the *same* underlying OTPGEN individuals -- what differs is one
declared physiological-state override. Every subject's lineage is required
to be byte-identical across every state before any statistic is computed:
that is what makes the resulting deltas genuinely paired (subject 17 vs.
themselves) rather than merely two independent summaries compared side by
side.
"""

from __future__ import annotations

from collections.abc import Mapping

from opentrials.analysis.descriptive import calculate_descriptive_summary
from opentrials.analysis.physiology_comparison import (
    PhysiologyComparisonMissingness,
    PhysiologyStateEndpointSummary,
    PhysiologyTrialComparisonResult,
    SubjectPhysiologyDelta,
)
from opentrials.analysis.pk import PkEndpointType
from opentrials.storage.endpoints import PkEndpointArtifactStore
from opentrials.storage.physiology import PhysiologyPopulationArtifactStore


def compare_physiology_states(
    *,
    baseline_state_id: str,
    state_physiology_population_ids: Mapping[str, str],
    state_endpoint_ids: Mapping[str, str],
    physiology_store: PhysiologyPopulationArtifactStore,
    endpoint_stores: Mapping[str, PkEndpointArtifactStore],
) -> PhysiologyTrialComparisonResult:
    """Strictly join every declared state's verified OTPHYS and OTPK artifacts.

    Every state must independently verify, must declare the same source
    OTPGEN generation and the same override target (only the scale factor
    may differ between states), and every subject compared must carry
    byte-identical population-row lineage across every state. Subjects
    present in some states but not all are excluded from paired deltas and
    recorded in ``missingness`` rather than silently dropped.
    """
    state_ids = set(state_physiology_population_ids)
    if state_ids != set(state_endpoint_ids) or state_ids != set(endpoint_stores):
        raise ValueError(
            "state_physiology_population_ids, state_endpoint_ids, and endpoint_stores must "
            "cover the same set of state IDs."
        )
    if len(state_ids) < 2:
        raise ValueError("Comparing physiology states requires at least two declared states.")
    if baseline_state_id not in state_ids:
        raise ValueError("baseline_state_id must be one of the declared states.")

    ordered_state_ids = sorted(state_ids)
    physiology_manifests = {
        state_id: physiology_store.verify_physiology_population(
            state_physiology_population_ids[state_id]
        )
        for state_id in ordered_state_ids
    }
    reference = physiology_manifests[ordered_state_ids[0]]
    for state_id in ordered_state_ids[1:]:
        manifest = physiology_manifests[state_id]
        if manifest.source_generation_id != reference.source_generation_id:
            raise ValueError("Every physiology state must share the same source OTPGEN.")
        if (
            manifest.source_population_semantic_sha256
            != reference.source_population_semantic_sha256
        ):
            raise ValueError("Every physiology state must share the same source population hash.")
        if manifest.override.target != reference.override.target:
            raise ValueError(
                "Every physiology state in one comparison must perturb the same target; "
                f"{state_id!r} uses {manifest.override.target!r}, expected "
                f"{reference.override.target!r}."
            )
        if manifest.coverage != reference.coverage:
            raise ValueError("Every physiology state must carry an identical coverage statement.")

    endpoint_manifest_hashes: dict[str, str] = {}
    rows_by_state: dict[str, tuple[dict[str, object], ...]] = {}
    for state_id in ordered_state_ids:
        endpoint_store = endpoint_stores[state_id]
        endpoint_id = state_endpoint_ids[state_id]
        endpoint_manifest = endpoint_store.verify_endpoints(endpoint_id)
        if (
            not endpoint_manifest.population_lineage_present
            or endpoint_manifest.source_generation_id != reference.source_generation_id
            or endpoint_manifest.source_population_semantic_sha256
            != reference.source_population_semantic_sha256
        ):
            raise ValueError(
                f"State {state_id!r} endpoint artifact lacks lineage matching the shared "
                "source population."
            )
        endpoint_manifest_hashes[state_id] = endpoint_manifest.endpoints.semantic_content_sha256
        rows_by_state[state_id] = endpoint_store.read_rows(endpoint_id)

    all_endpoint_types: set[PkEndpointType] = set()
    for rows in rows_by_state.values():
        for row in rows:
            raw_endpoint_type = row["endpoint_type"]
            assert isinstance(raw_endpoint_type, str)
            all_endpoint_types.add(PkEndpointType(raw_endpoint_type))
    endpoint_types = sorted(all_endpoint_types, key=lambda endpoint_type: endpoint_type.value)

    # Per-subject lineage identity, keyed by state -> subject_id -> (row_index, row_sha256).
    # Every subject present in a state must appear at most once per endpoint
    # type, and its lineage must be identical across every state it appears in.
    lineage_by_state: dict[str, dict[str, tuple[int, str]]] = {}
    value_by_state: dict[str, dict[tuple[str, PkEndpointType], tuple[float, str]]] = {}
    subjects_by_state: dict[str, set[str]] = {}
    for state_id in ordered_state_ids:
        lineage: dict[str, tuple[int, str]] = {}
        values: dict[tuple[str, PkEndpointType], tuple[float, str]] = {}
        for row in rows_by_state[state_id]:
            subject_id = str(row["subject_id"])
            raw_endpoint_type = row["endpoint_type"]
            assert isinstance(raw_endpoint_type, str)
            endpoint_type = PkEndpointType(raw_endpoint_type)
            key = (subject_id, endpoint_type)
            if key in values:
                raise ValueError(
                    f"State {state_id!r} has a duplicate {endpoint_type.value} row for "
                    f"subject {subject_id!r}."
                )
            raw_value = row["value"]
            assert isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
            values[key] = (float(raw_value), str(row["unit"]))
            raw_row_index = row["source_population_row_index"]
            assert isinstance(raw_row_index, int) and not isinstance(raw_row_index, bool)
            row_lineage = (raw_row_index, str(row["source_population_row_sha256"]))
            if subject_id in lineage and lineage[subject_id] != row_lineage:
                raise ValueError(
                    f"State {state_id!r} has inconsistent lineage across endpoint rows for "
                    f"subject {subject_id!r}."
                )
            lineage[subject_id] = row_lineage
        lineage_by_state[state_id] = lineage
        value_by_state[state_id] = values
        subjects_by_state[state_id] = set(lineage)

    complete_subject_ids = set.intersection(*subjects_by_state.values())
    all_subject_ids = set.union(*subjects_by_state.values())
    excluded_subject_ids = sorted(all_subject_ids - complete_subject_ids)

    for subject_id in complete_subject_ids:
        reference_lineage = lineage_by_state[ordered_state_ids[0]][subject_id]
        for state_id in ordered_state_ids[1:]:
            if lineage_by_state[state_id][subject_id] != reference_lineage:
                raise ValueError(
                    f"Subject {subject_id!r} does not carry identical population-row lineage "
                    "across every physiology state."
                )

    expected_subject_count = physiology_manifests[baseline_state_id].individuals.rows
    missingness = PhysiologyComparisonMissingness(
        expected_subject_count=expected_subject_count,
        complete_subject_count=len(complete_subject_ids),
        excluded_subject_ids=tuple(excluded_subject_ids),
    )

    summaries: list[PhysiologyStateEndpointSummary] = []
    for state_id in ordered_state_ids:
        for endpoint_type in endpoint_types:
            matching = [
                value for (subject, etype), value in value_by_state[state_id].items()
                if etype == endpoint_type
            ]
            if not matching:
                continue
            units = {unit for _, unit in matching}
            if len(units) > 1:
                raise ValueError(
                    f"State {state_id!r} has inconsistent units for {endpoint_type.value}: "
                    f"{sorted(units)!r}."
                )
            summaries.append(
                PhysiologyStateEndpointSummary(
                    state_id=state_id,
                    endpoint_type=endpoint_type,
                    unit=next(iter(units)),
                    n=len(matching),
                    summary=calculate_descriptive_summary([value for value, _ in matching]),
                )
            )

    deltas: list[SubjectPhysiologyDelta] = []
    comparison_state_ids = [
        state_id for state_id in ordered_state_ids if state_id != baseline_state_id
    ]
    for endpoint_type in endpoint_types:
        for subject_id in sorted(complete_subject_ids):
            baseline_entry = value_by_state[baseline_state_id].get((subject_id, endpoint_type))
            if baseline_entry is None:
                continue
            baseline_value, baseline_unit = baseline_entry
            for comparison_state_id in comparison_state_ids:
                comparison_entry = value_by_state[comparison_state_id].get(
                    (subject_id, endpoint_type)
                )
                if comparison_entry is None:
                    continue
                comparison_value, comparison_unit = comparison_entry
                if baseline_unit != comparison_unit:
                    raise ValueError(
                        f"Subject {subject_id!r} has inconsistent units for "
                        f"{endpoint_type.value} between states {baseline_state_id!r} and "
                        f"{comparison_state_id!r}."
                    )
                absolute_difference = comparison_value - baseline_value
                relative_difference = (
                    absolute_difference / baseline_value if baseline_value != 0.0 else None
                )
                deltas.append(
                    SubjectPhysiologyDelta(
                        subject_id=subject_id,
                        endpoint_type=endpoint_type,
                        unit=baseline_unit,
                        baseline_state_id=baseline_state_id,
                        comparison_state_id=comparison_state_id,
                        baseline_value=baseline_value,
                        comparison_value=comparison_value,
                        absolute_difference=absolute_difference,
                        relative_difference=relative_difference,
                    )
                )

    return PhysiologyTrialComparisonResult(
        source_generation_id=reference.source_generation_id,
        source_population_semantic_sha256=reference.source_population_semantic_sha256,
        baseline_state_id=baseline_state_id,
        state_physiology_population_ids=dict(state_physiology_population_ids),
        state_endpoint_ids=dict(state_endpoint_ids),
        state_endpoint_semantic_sha256=endpoint_manifest_hashes,
        state_summaries=tuple(summaries),
        subject_deltas=tuple(deltas),
        missingness=missingness,
        coverage=reference.coverage,
    )
