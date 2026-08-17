from pathlib import Path

import pytest

from opentrials.adapters.osp import resolve_population_execution_lineage
from opentrials.core.serialization import document
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

COLUMNS = ("IndividualId", "Gender", "Organism|Age")


def rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 25.0},
        {"IndividualId": 1, "Gender": "MALE", "Organism|Age": 40.0},
        {"IndividualId": 2, "Gender": "FEMALE", "Organism|Age": 60.0},
    )


def population_manifest(tmp_path: Path) -> object:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation("OTPGEN-lineage-test")
    return store.write_population(
        "OTPGEN-lineage-test",
        population_id="lineage-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "lineage-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=3,
        column_names=COLUMNS,
        rows=rows(),
    )


def test_resolves_lineage_by_individual_id_value_not_row_position(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)

    lineage = resolve_population_execution_lineage(manifest, COLUMNS, rows(), (2, 0, 1))

    assert set(lineage) == {"0", "1", "2"}
    assert lineage["0"].source_population_row_index == 0
    assert lineage["1"].source_population_row_index == 1
    assert lineage["2"].source_population_row_index == 2
    assert lineage["0"].source_generation_id == "OTPGEN-lineage-test"
    assert lineage["0"].source_population_semantic_sha256 == (
        manifest.individuals.semantic_content_sha256  # type: ignore[attr-defined]
    )
    assert lineage["0"].source_population_row_sha256 != lineage["1"].source_population_row_sha256


def test_rejects_result_individual_id_absent_from_population(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)

    with pytest.raises(ValueError, match="absent from the verified population"):
        resolve_population_execution_lineage(manifest, COLUMNS, rows(), (0, 1, 99))


def test_rejects_population_row_missing_from_results(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)

    with pytest.raises(ValueError, match="missing from the OSP execution result"):
        resolve_population_execution_lineage(manifest, COLUMNS, rows(), (0, 1))


def test_rejects_duplicate_result_individual_ids(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)

    with pytest.raises(ValueError, match="duplicate IndividualId"):
        resolve_population_execution_lineage(manifest, COLUMNS, rows(), (0, 0, 1))


def test_rejects_population_table_without_individual_id_column(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)

    with pytest.raises(ValueError, match="no IndividualId column"):
        resolve_population_execution_lineage(
            manifest, ("Gender", "Organism|Age"), rows(), (0, 1, 2)
        )


def test_rejects_duplicate_individual_id_in_population_table(tmp_path: Path) -> None:
    manifest = population_manifest(tmp_path)
    duplicated_rows = (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 25.0},
        {"IndividualId": 0, "Gender": "MALE", "Organism|Age": 40.0},
    )

    with pytest.raises(ValueError, match="duplicate IndividualId"):
        resolve_population_execution_lineage(manifest, COLUMNS, duplicated_rows, (0,))
