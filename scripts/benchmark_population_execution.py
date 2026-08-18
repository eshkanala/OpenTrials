"""Benchmark end-to-end population-linked PBPK execution across population sizes.

Generates and persists a real OTPGEN population, then executes it through the
verified Aciclovir IV population workflow (reconstruction, one intervention
mutation, batched runSimulations(), lineage resolution, OTRES/OTPK v2
persistence), timing generation and execution separately.
"""

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
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.orchestration.population_execution import run_population_execution
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
    parser.add_argument("--root", type=Path, default=Path("runs/population-execution-benchmarks"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[3, 10, 100, 1_000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dose-mg", type=float, default=250.0)
    parser.add_argument("--label", default="pbpk-population-benchmark")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    population_root = arguments.root / "populations"
    run_root = arguments.root / "runs"
    store = PopulationArtifactStore(population_root)
    translator = OspPopulationTranslator(
        OspPopulationProfile(reference_population=OspHumanPopulation.EUROPEAN_ICRP_2002)
    )
    generator = OspPopulationGenerator(r_libs_user=arguments.r_libs_user)

    for size in arguments.sizes:
        specification = PopulationSpec(
            id=f"pbpk-benchmark-female-adults-{size}",
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
        store.create_generation(generation_id)
        store.write_population(
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
        store.verify_population(generation_id)

        execution_started = time.perf_counter()
        run = run_population_execution(
            model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
            population_generation_id=generation_id,
            population_root=population_root,
            dose_mg=arguments.dose_mg,
            output_root=run_root,
            r_libs_user=arguments.r_libs_user,
        )
        execution_seconds = time.perf_counter() - execution_started

        endpoint_parquet = run.endpoint_directory / "endpoints.parquet"
        result_parquet = run.result_directory / "concentration_time.parquet"
        print(
            json.dumps(
                {
                    "n": size,
                    "generation_seconds": round(generation_seconds, 3),
                    "execution_seconds": round(execution_seconds, 3),
                    "total_seconds": round(generation_seconds + execution_seconds, 3),
                    "endpoint_rows": len(run.endpoints),
                    "endpoint_parquet_bytes": endpoint_parquet.stat().st_size,
                    "result_parquet_bytes": result_parquet.stat().st_size,
                    "run_id": run.run_id,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
