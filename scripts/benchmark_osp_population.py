"""Generate and persist OSP population-scale baselines without PBPK simulation."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from opentrials.adapters.osp import (
    OspHumanPopulation,
    OspPopulationGenerator,
    OspPopulationProfile,
    OspPopulationTranslator,
)
from opentrials.adapters.osp.generation import (
    POPULATION_WORKER_REQUEST_SCHEMA,
    POPULATION_WORKER_SCHEMA_VERSION,
)
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.core.serialization import document
from opentrials.patient import AgeRange, PopulationSpec, Sex
from opentrials.storage import (
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
)


def assumed(value: float, unit: str) -> ScientificValue:
    return ScientificValue(value=value, unit=unit, value_type=ValueType.ASSUMED)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r-libs-user", required=True, help="R library containing ospsuite.")
    parser.add_argument("--root", type=Path, default=Path("runs/population-benchmarks"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 1_000, 10_000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--label", default="osp-population-benchmark")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    store = PopulationArtifactStore(arguments.root)
    translator = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    )
    generator = OspPopulationGenerator(r_libs_user=arguments.r_libs_user)

    for size in arguments.sizes:
        specification = PopulationSpec(
            id=f"osp-female-adults-{size}",
            size=size,
            seed=arguments.seed,
            generator_version="0.1.0",
            age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
            sexes=(Sex.FEMALE,),
        )
        translation = translator.translate(specification)
        generation_started = time.perf_counter()
        result = generator.generate(translation)
        generation_seconds = time.perf_counter() - generation_started

        generation_id = f"OTPGEN-{arguments.label}-n{size}-{uuid.uuid4().hex[:12]}"
        write_started = time.perf_counter()
        store.create_generation(generation_id)
        manifest = store.write_population(
            generation_id,
            population_id=result.population_id,
            source_request=document(
                POPULATION_WORKER_REQUEST_SCHEMA,
                translation.request,
                POPULATION_WORKER_SCHEMA_VERSION,
            ),
            generator=PopulationGeneratorProvenance(
                engine_id="osp",
                population_model=translation.request.reference_population.value,
                software_versions={"ospsuite": result.ospsuite_version, "r": result.r_version},
            ),
            generation=PopulationGenerationProvenance(
                requested_seed=result.requested_seed,
                engine_seed=result.engine_seed,
                determinism_level=result.determinism_level.value,
            ),
            requested_count=translation.request.number_of_individuals,
            column_names=result.column_names,
            rows=result.raw_rows,
            generated_physiology_provenance=tuple(
                assumption.assumption_id for assumption in translation.report.assumptions
            ),
        )
        write_seconds = time.perf_counter() - write_started
        store.verify_population(generation_id)
        artifact_path = arguments.root / generation_id / manifest.individuals.path
        print(
            json.dumps(
                {
                    "generation_id": generation_id,
                    "n": size,
                    "generation_seconds": round(generation_seconds, 3),
                    "artifact_write_seconds": round(write_seconds, 3),
                    "rows": manifest.individuals.rows,
                    "columns": manifest.individuals.columns,
                    "parquet_bytes": artifact_path.stat().st_size,
                    "requested_seed": result.requested_seed,
                    "engine_seed": result.engine_seed,
                    "semantic_content_sha256": manifest.individuals.semantic_content_sha256,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
