from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def fully_mapped_translation() -> object:
    specification = PopulationSpec(
        id="female-adults",
        size=10,
        seed=42,
        generator_version="0.1.0",
        age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
        sexes=(Sex.FEMALE,),
    )
    translator = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    )
    return translator.translate(specification)


def test_population_generator_rejects_unverified_osp_defaults() -> None:
    translation = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    ).translate(
        PopulationSpec(
            id="unconstrained-adults",
            size=10,
            seed=42,
            generator_version="0.1.0",
        )
    )

    with pytest.raises(ValueError, match="unverified OSP defaults"):
        OspPopulationGenerator().generate(translation)


def test_population_generator_preserves_raw_worker_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rscript_path = tmp_path / "Rscript"
    rscript_path.touch()
    worker_path = tmp_path / "generate_population.R"
    worker_path.touch()

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "schema": "opentrials.osp.population-worker-response",
                    "schema_version": "1.0.0",
                    "payload": {
                        "status": "SUCCEEDED",
                        "population_id": "female-adults",
                        "requested_seed": 42,
                        "engine_seed": 42,
                        "determinism_level": "STRICT",
                        "r_version": "R version 4.6.1",
                        "ospsuite_version": "12.4.4",
                        "column_names": ["IndividualId", "Gender", "Organism|Age"],
                        "raw_rows": [{"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 31.2}]
                        * 10,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("opentrials.adapters.osp.generation.subprocess.run", fake_run)
    result = OspPopulationGenerator(rscript_path=rscript_path, worker_path=worker_path).generate(
        fully_mapped_translation()
    )

    assert result.engine_seed == 42
    assert result.determinism_level is OspDeterminismLevel.STRICT
    assert len(result.raw_rows) == 10
    assert result.raw_rows[0]["Gender"] == "FEMALE"
