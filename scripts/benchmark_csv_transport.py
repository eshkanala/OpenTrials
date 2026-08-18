"""Staged benchmark for population-linked PBPK execution, JSON vs CSV transport.

Generates and persists a real OTPGEN population, then executes it through the
verified Aciclovir IV population workflow once per requested transport,
printing the per-stage timing breakdown (verify_otpgen, translate_intervention,
execute_population, persist_raw, normalize_results, pk_analysis,
resolve_lineage, persist_endpoints, total) plus, for CSV transport, the R-side
and Python-side sub-stage detail nested inside execute_population
(r_population_load_seconds, r_solver_seconds, r_result_export_seconds,
python_population_csv_write_seconds, python_result_csv_read_seconds).

See HANDOFF v0.6-C for the capability probe that motivated this transport.
"""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--root", type=Path, default=Path("runs/csv-transport-benchmarks"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1_000])
    parser.add_argument(
        "--transports", nargs="+", choices=["json", "csv"], default=["json", "csv"]
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dose-mg", type=float, default=250.0)
    parser.add_argument("--label", default="csv-transport-benchmark")
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
            id=f"csv-benchmark-female-adults-{size}",
            size=size,
            seed=arguments.seed,
            generator_version="0.1.0",
            age_range=AgeRange(minimum=assumed(18, "year"), maximum=assumed(65, "year")),
            sexes=(Sex.FEMALE,),
        )
        translation = translator.translate(specification)
        result = generator.generate(translation)

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

        for transport in arguments.transports:
            run = run_population_execution(
                model_capability_profile=ACICLOVIR_IV_CAPABILITY_PROFILE,
                population_generation_id=generation_id,
                population_root=population_root,
                dose_mg=arguments.dose_mg,
                output_root=run_root,
                r_libs_user=arguments.r_libs_user,
                transport=transport,  # type: ignore[arg-type]
            )
            print(
                json.dumps(
                    {
                        "n": size,
                        "transport": transport,
                        "stage_seconds": {
                            key: round(value, 4) for key, value in run.stage_seconds.items()
                        },
                        "endpoint_rows": len(run.endpoints),
                        "run_id": run.run_id,
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    main()
