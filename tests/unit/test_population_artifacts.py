from pathlib import Path

import pyarrow.parquet as pq
import pytest

from opentrials.core.serialization import document
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)


def generator() -> PopulationGeneratorProvenance:
    return PopulationGeneratorProvenance(
        engine_id="osp",
        population_model="European_ICRP_2002",
        software_versions={"ospsuite": "12.4.4", "r": "4.6.1"},
    )


def generation() -> PopulationGenerationProvenance:
    return PopulationGenerationProvenance(
        requested_seed=42,
        engine_seed=42,
        determinism_level="STRICT",
    )


def request():
    return document(
        "opentrials.osp.population-worker-request",
        {
            "population_id": "female-adults",
            "number_of_individuals": 2,
            "requested_seed": 42,
        },
    )


def rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 31.2},
        {"IndividualId": 1, "Gender": "FEMALE", "Organism|Age": 42.7},
    )


def test_population_artifact_preserves_raw_table_and_distinguishes_identities(
    tmp_path: Path,
) -> None:
    store = PopulationArtifactStore(tmp_path / "populations")
    first_directory = store.create_generation("OTPGEN-001")
    second_directory = store.create_generation("OTPGEN-002")

    first = store.write_population(
        "OTPGEN-001",
        population_id="female-adults",
        source_request=request(),
        generator=generator(),
        generation=generation(),
        requested_count=2,
        column_names=("IndividualId", "Gender", "Organism|Age"),
        rows=rows(),
        generated_physiology_provenance=("osp-generated-physiology",),
    )
    second = store.write_population(
        "OTPGEN-002",
        population_id="female-adults",
        source_request=request(),
        generator=generator(),
        generation=generation(),
        requested_count=2,
        column_names=("IndividualId", "Gender", "Organism|Age"),
        rows=rows(),
        generated_physiology_provenance=("osp-generated-physiology",),
    )

    table = pq.read_table(first_directory / "individuals.parquet")

    assert first.generation_id != second.generation_id
    assert first.individuals.semantic_content_sha256 == second.individuals.semantic_content_sha256
    assert table.column_names == ["IndividualId", "Gender", "Organism|Age"]
    assert table.num_rows == 2
    assert (
        '"schema":"opentrials.population-artifact"'
        in (first_directory / "manifest.json").read_text()
    )
    assert (second_directory / "manifest.json").is_file()


def test_population_artifact_rejects_changed_or_incomplete_tables(tmp_path: Path) -> None:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation("OTPGEN-003")

    with pytest.raises(ValueError, match="row count"):
        store.write_population(
            "OTPGEN-003",
            population_id="female-adults",
            source_request=request(),
            generator=generator(),
            generation=generation(),
            requested_count=3,
            column_names=("IndividualId", "Gender", "Organism|Age"),
            rows=rows(),
        )
