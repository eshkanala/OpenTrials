"""Opt-in integration proof for the installed local OSP population generator."""

from __future__ import annotations

import os

import pytest

from opentrials.adapters.osp import (
    OspDeterminismLevel,
    OspHumanPopulation,
    OspPopulationGenerator,
    OspPopulationProfile,
    OspPopulationTranslator,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.patient import AgeRange, PopulationSpec, Sex

pytestmark = pytest.mark.osp_integration


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def translation(seed: int):
    specification = PopulationSpec(
        id="osp-reproducibility-proof",
        size=10,
        seed=seed,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    return OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(specification)


def test_osp_population_seed_is_exactly_reproducible() -> None:
    if os.environ.get("OPENTRIALS_RUN_OSP_INTEGRATION") != "1":
        pytest.skip("Set OPENTRIALS_RUN_OSP_INTEGRATION=1 to run against local OSP.")
    r_libs_user = os.environ.get("OPENTRIALS_OSP_R_LIBS_USER")
    if r_libs_user is None:
        pytest.skip("Set OPENTRIALS_OSP_R_LIBS_USER to the ospsuite R library path.")

    generator = OspPopulationGenerator(r_libs_user=r_libs_user)
    first = generator.generate(translation(42))
    second = generator.generate(translation(42))
    different_seed = generator.generate(translation(43))

    assert first.engine_seed == second.engine_seed == 42
    assert different_seed.engine_seed == 43
    assert first.determinism_level is OspDeterminismLevel.STRICT
    assert first.raw_rows == second.raw_rows
    assert first.raw_rows != different_seed.raw_rows
