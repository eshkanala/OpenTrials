"""Deterministic, reproducible population allocation across trial arms.

Two explicit, named, deterministic steps -- never an implicit rounding or
shuffling convention:

1. Largest-remainder (Hare-quota) apportionment converts each arm's
   fractional allocation into an exact integer headcount summing to the
   full population, with remainder ties broken by declared arm order.
2. A seeded shuffle (``random.Random(trial.seed)``, the same primitive
   already used for uncertainty-draw materialization) assigns specific
   individuals to those headcounts.

Every subject is assigned to exactly one arm.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from opentrials.storage.row_identity import source_row_sha256
from opentrials.trials.trial import RandomizationType, Trial, TrialArm

APPORTIONMENT_METHOD = "largest_remainder"


@dataclass(frozen=True)
class ArmAllocationEntry:
    """One subject's deterministic assignment to exactly one trial arm."""

    subject_id: str
    source_row_index: int
    source_row_sha256: str
    arm_id: str


@dataclass(frozen=True)
class ArmAllocationResult:
    """The complete deterministic partition of one population across arms."""

    trial_id: str
    requested_seed: int
    total_population: int
    apportionment_method: str
    arm_counts: dict[str, int]
    entries: tuple[ArmAllocationEntry, ...]


def allocate_population_to_arms(
    trial: Trial,
    population_columns: Sequence[str],
    population_rows: Sequence[Mapping[str, object]],
    subject_id_column: str,
) -> ArmAllocationResult:
    """Deterministically partition every population row into exactly one arm."""
    if trial.randomization is not RandomizationType.PARALLEL:
        raise ValueError("Arm allocation requires a PARALLEL-randomized trial design.")
    total = len(population_rows)
    if total == 0:
        raise ValueError("Allocation requires at least one population row.")

    arm_counts = _largest_remainder_apportionment(trial.arms, total)

    indices = list(range(total))
    random.Random(trial.seed).shuffle(indices)

    entries: list[ArmAllocationEntry] = []
    cursor = 0
    for arm in trial.arms:
        count = arm_counts[arm.arm_id]
        for row_index in indices[cursor : cursor + count]:
            row = population_rows[row_index]
            entries.append(
                ArmAllocationEntry(
                    subject_id=str(row[subject_id_column]),
                    source_row_index=row_index,
                    source_row_sha256=source_row_sha256(population_columns, row),
                    arm_id=arm.arm_id,
                )
            )
        cursor += count

    entries.sort(key=lambda entry: entry.source_row_index)
    return ArmAllocationResult(
        trial_id=trial.trial_id,
        requested_seed=trial.seed,
        total_population=total,
        apportionment_method=APPORTIONMENT_METHOD,
        arm_counts=arm_counts,
        entries=tuple(entries),
    )


def _largest_remainder_apportionment(arms: Sequence[TrialArm], total: int) -> dict[str, int]:
    """Convert fractional allocations into exact integer counts via Hare quota."""
    quotas = {arm.arm_id: arm.allocation * total for arm in arms}
    floors = {arm_id: int(quota) for arm_id, quota in quotas.items()}
    remainder = total - sum(floors.values())
    ranked_by_remainder = sorted(
        (
            (quotas[arm.arm_id] - floors[arm.arm_id], declared_order, arm.arm_id)
            for declared_order, arm in enumerate(arms)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    counts = dict(floors)
    for _, _, arm_id in ranked_by_remainder[:remainder]:
        counts[arm_id] += 1
    return counts
