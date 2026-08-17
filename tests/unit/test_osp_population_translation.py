from __future__ import annotations

import pytest

from opentrials.adapters.osp import (
    OspDeterminismLevel,
    OspHumanPopulation,
    OspPopulationProfile,
    OspPopulationTranslator,
    PopulationFeatureStatus,
    UnsupportedPopulationFeatureError,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.patient import AgeRange, PopulationSpec, Sex


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def translator() -> OspPopulationTranslator:
    return OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    )


def test_translator_maps_a_female_age_constrained_population() -> None:
    specification = PopulationSpec(
        id="healthy-female-adults",
        size=10,
        seed=42,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
        provenance_ids=("population-source",),
    )

    translation = translator().translate(specification)

    assert translation.request.number_of_individuals == 10
    assert translation.request.requested_seed == 42
    assert translation.request.reference_population is OspHumanPopulation.EUROPEAN_ICRP_2002
    assert translation.request.age_minimum_years == 18
    assert translation.request.age_maximum_years == 65
    assert translation.request.proportion_female_percent == 100
    assert not translation.report.unsupported
    assert not translation.report.defaulted
    assert translation.report.determinism_level is OspDeterminismLevel.STRICT
    assert translation.report.assumptions[0].assumption_id == "osp-generated-physiology"


def test_translator_reports_unconstrained_age_and_sex_as_defaults() -> None:
    specification = PopulationSpec(
        id="unconstrained-adults",
        size=10,
        seed=42,
        generator_version="0.1.0",
    )

    translation = translator().translate(specification)

    assert translation.request.age_minimum_years is None
    assert translation.request.age_maximum_years is None
    assert translation.request.proportion_female_percent is None
    assert {item.source_field for item in translation.report.defaulted} == {"age_range", "sexes"}


def test_translator_rejects_mixed_sex_without_a_distribution() -> None:
    specification = PopulationSpec(
        id="mixed-adults",
        size=10,
        seed=42,
        generator_version="0.1.0",
        sexes=(Sex.FEMALE, Sex.MALE),
    )

    with pytest.raises(UnsupportedPopulationFeatureError) as error:
        translator().translate(specification)

    assert error.value.translation.request.proportion_female_percent is None
    assert error.value.translation.report.unsupported[0].source_field == "sexes"
    assert (
        error.value.translation.report.unsupported[0].status is PopulationFeatureStatus.UNSUPPORTED
    )


def test_translator_rejects_free_text_criteria_and_enrichment() -> None:
    specification = PopulationSpec(
        id="enriched-adults",
        size=10,
        seed=42,
        generator_version="0.1.0",
        inclusion_criteria=("healthy",),
        enrichment={"renal-impairment": 2},
    )

    with pytest.raises(UnsupportedPopulationFeatureError) as error:
        translator().translate(specification)

    assert {item.source_field for item in error.value.translation.report.unsupported} == {
        "inclusion_criteria",
        "enrichment",
    }
