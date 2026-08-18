"""Contract tests for the immutable OTPHYS physiology-state population artifact."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from opentrials.adapters.osp import physiology_coverage_for, resolve_osp_physiology_column
from opentrials.core.serialization import document
from opentrials.physiology import PhysiologicalStateOverride
from opentrials.storage import (
    PhysiologyPopulationArtifactManifest,
    PhysiologyPopulationArtifactStore,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)

GENERATION_ID = "OTPGEN-physiology-test"
GFR_COLUMN = "Organism|Kidney|GFRmat"
COLUMNS = ("IndividualId", "Gender", "Organism|Age", GFR_COLUMN)
TARGET = "renal.glomerular_filtration_rate"


def source_rows() -> tuple[dict[str, object], ...]:
    return (
        {"IndividualId": 0, "Gender": "FEMALE", "Organism|Age": 40.0, GFR_COLUMN: 0.10},
        {"IndividualId": 1, "Gender": "MALE", "Organism|Age": 55.0, GFR_COLUMN: 0.12},
        {"IndividualId": 2, "Gender": "FEMALE", "Organism|Age": 63.0, GFR_COLUMN: 0.09},
    )


def build_population(tmp_path: Path) -> tuple[Path, PopulationArtifactManifest]:
    root = tmp_path / "populations"
    store = PopulationArtifactStore(root)
    store.create_generation(GENERATION_ID)
    manifest = store.write_population(
        GENERATION_ID,
        population_id="physiology-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "physiology-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=3,
        column_names=COLUMNS,
        rows=source_rows(),
    )
    return root, manifest


def override(scale_factor: float) -> PhysiologicalStateOverride:
    return PhysiologicalStateOverride(
        target=TARGET,
        scale_factor=scale_factor,
        unit="L/min",
        purpose="v0.6-A verified renal-function perturbation test",
    )


def write_physiology_population(
    tmp_path: Path, physiology_population_id: str, scale_factor: float
) -> tuple[PhysiologyPopulationArtifactStore, PhysiologyPopulationArtifactManifest]:
    population_root, population_manifest = build_population(tmp_path)
    physiology_store = PhysiologyPopulationArtifactStore(tmp_path / "physiology")
    physiology_store.create_physiology_population(physiology_population_id)
    manifest = physiology_store.write_physiology_population(
        physiology_population_id,
        source_population_manifest=population_manifest,
        source_column_names=COLUMNS,
        source_rows=source_rows(),
        override=override(scale_factor),
        osp_parameter_path=resolve_osp_physiology_column(TARGET),
        coverage=physiology_coverage_for(TARGET),
    )
    return physiology_store, manifest


def test_scaling_preserves_row_order_count_and_every_other_column(tmp_path: Path) -> None:
    physiology_store, manifest = write_physiology_population(
        tmp_path, "OTPHYS-severe", scale_factor=0.3
    )
    assert manifest.individuals.rows == 3
    assert manifest.changed_column == GFR_COLUMN
    assert manifest.osp_parameter_path == GFR_COLUMN

    table = pq.read_table(tmp_path / "physiology" / "OTPHYS-severe" / "individuals.parquet")
    rows = table.to_pylist()
    assert [row["IndividualId"] for row in rows] == [0, 1, 2]
    for source, executed in zip(source_rows(), rows, strict=True):
        assert executed["Gender"] == source["Gender"]
        assert executed["Organism|Age"] == source["Organism|Age"]
        source_gfr = source[GFR_COLUMN]
        assert isinstance(source_gfr, float)
        assert executed[GFR_COLUMN] == pytest.approx(source_gfr * 0.3)


def test_value_summaries_reflect_original_and_executed_values(tmp_path: Path) -> None:
    _, manifest = write_physiology_population(tmp_path, "OTPHYS-mild", scale_factor=0.6)
    assert manifest.original_value_summary.mean == pytest.approx((0.10 + 0.12 + 0.09) / 3)
    assert manifest.executed_value_summary.mean == pytest.approx(
        (0.10 + 0.12 + 0.09) / 3 * 0.6
    )
    assert manifest.executed_value_summary.maximum == pytest.approx(0.12 * 0.6)


def test_coverage_statement_is_persisted_verbatim(tmp_path: Path) -> None:
    _, manifest = write_physiology_population(tmp_path, "OTPHYS-coverage", scale_factor=1.0)
    assert manifest.coverage.modeled == ("renal.glomerular_filtration",)
    assert "renal.tubular_secretion" in manifest.coverage.unmodeled


def test_round_trip_verification_detects_tampering(tmp_path: Path) -> None:
    physiology_store, manifest = write_physiology_population(
        tmp_path, "OTPHYS-tamper", scale_factor=0.5
    )
    assert physiology_store.verify_physiology_population("OTPHYS-tamper") == manifest

    parquet_path = tmp_path / "physiology" / "OTPHYS-tamper" / "individuals.parquet"
    table = pq.read_table(parquet_path)
    tampered_rows = table.to_pylist()
    tampered_rows[0][GFR_COLUMN] = 999.0
    pq.write_table(
        pa.table({col: [row[col] for row in tampered_rows] for col in COLUMNS}), parquet_path
    )

    with pytest.raises(ValueError, match="does not match its manifest"):
        physiology_store.verify_physiology_population("OTPHYS-tamper")


def test_rejects_a_target_absent_from_the_source_table(tmp_path: Path) -> None:
    population_root, population_manifest = build_population(tmp_path)
    physiology_store = PhysiologyPopulationArtifactStore(tmp_path / "physiology")
    physiology_store.create_physiology_population("OTPHYS-missing-column")

    with pytest.raises(ValueError, match="no column"):
        physiology_store.write_physiology_population(
            "OTPHYS-missing-column",
            source_population_manifest=population_manifest,
            source_column_names=("IndividualId", "Gender", "Organism|Age"),
            source_rows=tuple(
                {k: v for k, v in row.items() if k != GFR_COLUMN} for row in source_rows()
            ),
            override=override(0.5),
            osp_parameter_path=resolve_osp_physiology_column(TARGET),
            coverage=physiology_coverage_for(TARGET),
        )


def test_rejects_creating_the_same_physiology_population_twice(tmp_path: Path) -> None:
    physiology_store, _ = write_physiology_population(tmp_path, "OTPHYS-dup", scale_factor=0.5)
    with pytest.raises(FileExistsError):
        physiology_store.create_physiology_population("OTPHYS-dup")
