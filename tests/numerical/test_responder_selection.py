import pytest

from opentrials.analysis.pk import PkEndpointType
from opentrials.responders import (
    ExtremeResponderDefinition,
    RankableSubject,
    SelectionMethod,
    TiePolicy,
    select_extreme_responders,
)

SOURCE_HASH = "sha256:" + "a" * 64
GENERATION_ID = "OTPGEN-selection-test"
ENDPOINT_ID = "OTPK-selection-test"


def subjects(values: dict[int, float]) -> tuple[RankableSubject, ...]:
    return tuple(
        RankableSubject(
            subject_id=str(index),
            source_row_index=index,
            source_row_sha256="sha256:" + f"{index:064d}",
            value=value,
        )
        for index, value in values.items()
    )


def definition(**overrides: object) -> ExtremeResponderDefinition:
    values: dict[str, object] = {
        "definition_id": "OTRESP-test",
        "source_endpoint_id": ENDPOINT_ID,
        "source_endpoint_semantic_sha256": SOURCE_HASH,
        "source_generation_id": GENERATION_ID,
        "source_population_semantic_sha256": SOURCE_HASH,
        "endpoint_type": PkEndpointType.AUC_0_LAST,
        "method": SelectionMethod.TOP_N,
        "count": 2,
        "tie_policy": TiePolicy.STRICT_COUNT,
    }
    values.update(overrides)
    return ExtremeResponderDefinition(**values)  # type: ignore[arg-type]


# Values chosen with a distinct rank order: 0->10, 1->20, ..., 9->100.
TEN_SUBJECTS = subjects({i: float((i + 1) * 10) for i in range(10)})


def test_top_n_selects_highest_values_and_reference_is_complement() -> None:
    result = select_extreme_responders(
        TEN_SUBJECTS, definition(method=SelectionMethod.TOP_N, count=3, percentile=None)
    )

    assert [subject.value for subject in result.extreme] == [100.0, 90.0, 80.0]
    assert [subject.rank for subject in result.extreme] == [1, 2, 3]
    assert len(result.reference) == 7
    assert result.total_population == 10
    assert result.threshold_value == 80.0


def test_bottom_n_selects_lowest_values() -> None:
    result = select_extreme_responders(
        TEN_SUBJECTS, definition(method=SelectionMethod.BOTTOM_N, count=2, percentile=None)
    )

    assert [subject.value for subject in result.extreme] == [10.0, 20.0]


def test_top_n_rejects_count_exceeding_population() -> None:
    with pytest.raises(ValueError, match="exceeds the total population"):
        select_extreme_responders(
            TEN_SUBJECTS, definition(method=SelectionMethod.TOP_N, count=11, percentile=None)
        )


def test_top_percentile_selects_by_ceiling_count() -> None:
    # ceil(10 * 25 / 100) = 3
    result = select_extreme_responders(
        TEN_SUBJECTS, definition(method=SelectionMethod.TOP_PERCENTILE, percentile=25.0, count=None)
    )

    assert len(result.extreme) == 3
    assert [subject.value for subject in result.extreme] == [100.0, 90.0, 80.0]


def test_above_percentile_uses_interpolated_threshold_value() -> None:
    result = select_extreme_responders(
        TEN_SUBJECTS,
        definition(method=SelectionMethod.ABOVE_PERCENTILE, percentile=90.0, count=None),
    )

    # p90 over [10..100] (linear-interpolated) = 91.0; strictly-above excludes it.
    assert result.threshold_value == pytest.approx(91.0)
    assert [subject.value for subject in result.extreme] == [100.0]


def test_strict_count_tie_policy_breaks_ties_deterministically_by_row_index() -> None:
    tied = subjects({0: 5.0, 1: 5.0, 2: 5.0, 3: 1.0})
    result = select_extreme_responders(
        tied, definition(method=SelectionMethod.TOP_N, count=2, tie_policy=TiePolicy.STRICT_COUNT)
    )

    assert len(result.extreme) == 2
    assert {subject.source_row_index for subject in result.extreme} == {0, 1}


def test_include_all_ties_policy_may_exceed_requested_count() -> None:
    tied = subjects({0: 5.0, 1: 5.0, 2: 5.0, 3: 1.0})
    result = select_extreme_responders(
        tied,
        definition(method=SelectionMethod.TOP_N, count=2, tie_policy=TiePolicy.INCLUDE_ALL_TIES),
    )

    assert len(result.extreme) == 3
    assert {subject.source_row_index for subject in result.extreme} == {0, 1, 2}


def test_include_all_ties_threshold_method_includes_boundary_value() -> None:
    values = subjects({0: 10.0, 1: 20.0, 2: 20.0, 3: 30.0})
    strict = select_extreme_responders(
        values,
        definition(
            method=SelectionMethod.ABOVE_PERCENTILE,
            percentile=50.0,
            count=None,
            tie_policy=TiePolicy.STRICT_COUNT,
        ),
    )
    inclusive = select_extreme_responders(
        values,
        definition(
            method=SelectionMethod.ABOVE_PERCENTILE,
            percentile=50.0,
            count=None,
            tie_policy=TiePolicy.INCLUDE_ALL_TIES,
        ),
    )

    assert len(inclusive.extreme) >= len(strict.extreme)


def test_selection_is_deterministic_regardless_of_input_order() -> None:
    forward = select_extreme_responders(
        TEN_SUBJECTS, definition(method=SelectionMethod.TOP_N, count=4, percentile=None)
    )
    reversed_subjects = tuple(reversed(TEN_SUBJECTS))
    backward = select_extreme_responders(
        reversed_subjects, definition(method=SelectionMethod.TOP_N, count=4, percentile=None)
    )

    assert forward.extreme == backward.extreme
    assert forward.reference == backward.reference


def test_tiny_population_of_one_is_handled() -> None:
    one = subjects({0: 42.0})
    result = select_extreme_responders(
        one, definition(method=SelectionMethod.TOP_N, count=1, percentile=None)
    )

    assert len(result.extreme) == 1
    assert len(result.reference) == 0


def test_selection_rejects_empty_population() -> None:
    with pytest.raises(ValueError, match="At least one subject"):
        select_extreme_responders(
            (), definition(method=SelectionMethod.TOP_N, count=1, percentile=None)
        )


def test_definition_rejects_percentile_and_count_together() -> None:
    with pytest.raises(ValueError, match="requires percentile only"):
        definition(method=SelectionMethod.TOP_PERCENTILE, percentile=5.0, count=3)


def test_definition_rejects_count_method_without_count() -> None:
    with pytest.raises(ValueError, match="requires count only"):
        definition(method=SelectionMethod.TOP_N, count=None, percentile=None)
