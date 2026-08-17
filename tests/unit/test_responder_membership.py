from pathlib import Path

import pytest

from opentrials.analysis.pk import PkEndpointResult, PkEndpointType
from opentrials.core.serialization import document
from opentrials.responders import ExtremeResponderDefinition, SelectionMethod, TiePolicy
from opentrials.storage import (
    ExtremeResponderMembershipArtifactStore,
    PkEndpointArtifactStore,
    PkEndpointSubjectLineage,
    PopulationArtifactManifest,
    PopulationArtifactStore,
    PopulationGenerationProvenance,
    PopulationGeneratorProvenance,
    ResponderGroupKind,
)
from opentrials.storage.row_identity import source_row_sha256

SOURCE_HASH = "sha256:" + "a" * 64
COLUMNS = ("IndividualId", "Gender", "Organism|Age")
GENERATION_ID = "OTPGEN-responder-membership-test"
ENDPOINT_ID = "OTPK-responder-membership-test"
AUC_VALUES = {0: 10.0, 1: 20.0, 2: 30.0, 3: 40.0, 4: 50.0}


def population_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {"IndividualId": index, "Gender": "FEMALE", "Organism|Age": 20.0 + index}
        for index in range(5)
    )


def build_population(tmp_path: Path) -> tuple[PopulationArtifactStore, PopulationArtifactManifest]:
    store = PopulationArtifactStore(tmp_path / "populations")
    store.create_generation(GENERATION_ID)
    manifest = store.write_population(
        GENERATION_ID,
        population_id="responder-demo",
        source_request=document(
            "opentrials.osp.population-worker-request", {"population_id": "responder-demo"}
        ),
        generator=PopulationGeneratorProvenance(
            engine_id="osp", population_model="demo", software_versions={"osp": "12.4"}
        ),
        generation=PopulationGenerationProvenance(
            requested_seed=1, engine_seed=1, determinism_level="STRICT"
        ),
        requested_count=5,
        column_names=COLUMNS,
        rows=population_rows(),
    )
    return store, manifest


def build_endpoint(
    tmp_path: Path, manifest: PopulationArtifactManifest, *, corrupt_row_hash: bool = False
) -> PkEndpointArtifactStore:
    endpoints = []
    lineage = {}
    for row_index, auc in AUC_VALUES.items():
        subject_id = f"subject-{row_index}"
        endpoints.append(
            PkEndpointResult(
                subject_id=subject_id,
                endpoint_type=PkEndpointType.AUC_0_LAST,
                value=auc,
                unit="umol/L * min",
                time_basis="actual_sample_times",
                integration_method="linear_trapezoidal",
                source_result_hash=SOURCE_HASH,
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
            )
        )
        row_hash = (
            "sha256:" + "f" * 64
            if corrupt_row_hash and row_index == 0
            else source_row_sha256(COLUMNS, population_rows()[row_index])
        )
        lineage[subject_id] = PkEndpointSubjectLineage(
            source_generation_id=GENERATION_ID,
            source_population_semantic_sha256=manifest.individuals.semantic_content_sha256,
            source_population_row_index=row_index,
            source_population_row_sha256=row_hash,
        )
    store = PkEndpointArtifactStore(tmp_path / "endpoints")
    store.create_endpoint_artifact(ENDPOINT_ID)
    store.write_endpoints(
        ENDPOINT_ID,
        endpoints=tuple(endpoints),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-responder-test",
        run_id="OTR-responder-test",
        subject_lineage=lineage,
    )
    return store


def top_two_definition(
    endpoint_hash: str, population_hash: str, *, count: int = 2
) -> ExtremeResponderDefinition:
    return ExtremeResponderDefinition(
        definition_id="OTRESP-top-auc",
        source_endpoint_id=ENDPOINT_ID,
        source_endpoint_semantic_sha256=endpoint_hash,
        source_generation_id=GENERATION_ID,
        source_population_semantic_sha256=population_hash,
        endpoint_type=PkEndpointType.AUC_0_LAST,
        method=SelectionMethod.TOP_N,
        count=count,
        percentile=None,
        tie_policy=TiePolicy.STRICT_COUNT,
    )


def test_write_extreme_and_reference_memberships(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoints = build_endpoint(tmp_path, population_manifest)
    endpoint_manifest = endpoints.verify_endpoints(ENDPOINT_ID)
    definition = top_two_definition(
        endpoint_manifest.endpoints.semantic_content_sha256,
        population_manifest.individuals.semantic_content_sha256,
    )
    store = ExtremeResponderMembershipArtifactStore(
        tmp_path / "memberships", endpoint_store=endpoints, population_store=populations
    )

    store.create_membership("OTXMEM-extreme")
    extreme = store.write_membership(
        "OTXMEM-extreme", definition=definition, group_kind=ResponderGroupKind.EXTREME
    )
    store.create_membership("OTXMEM-reference")
    reference = store.write_membership(
        "OTXMEM-reference", definition=definition, group_kind=ResponderGroupKind.REFERENCE
    )

    assert extreme.members.rows == 2
    assert reference.members.rows == 3
    assert extreme.total_population == 5
    assert extreme.threshold_value == 40.0
    assert extreme.endpoint_unit == "umol/L * min"

    extreme_rows = store.read_member_rows("OTXMEM-extreme")
    assert sorted(subject.value for subject in extreme_rows) == [40.0, 50.0]
    assert {subject.rank for subject in extreme_rows} == {1, 2}

    assert store.verify_membership("OTXMEM-extreme") == extreme
    assert store.verify_membership("OTXMEM-reference") == reference


def test_write_membership_rejects_endpoint_without_lineage(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoint_store = PkEndpointArtifactStore(tmp_path / "endpoints")
    endpoint_store.create_endpoint_artifact(ENDPOINT_ID)
    endpoint_store.write_endpoints(
        ENDPOINT_ID,
        endpoints=(
            PkEndpointResult(
                subject_id="0",
                endpoint_type=PkEndpointType.AUC_0_LAST,
                value=10.0,
                unit="umol/L * min",
                time_basis="actual_sample_times",
                integration_method="linear_trapezoidal",
                source_result_hash=SOURCE_HASH,
                analyte="aciclovir",
                matrix="plasma",
                fraction="total",
                measurement="concentration",
            ),
        ),
        source_result_semantic_sha256=SOURCE_HASH,
        source_result_id="OTRES-nolineage",
        run_id="OTR-nolineage",
    )
    endpoint_manifest = endpoint_store.verify_endpoints(ENDPOINT_ID)
    definition = top_two_definition(
        endpoint_manifest.endpoints.semantic_content_sha256,
        population_manifest.individuals.semantic_content_sha256,
        count=1,
    )
    store = ExtremeResponderMembershipArtifactStore(
        tmp_path / "memberships", endpoint_store=endpoint_store, population_store=populations
    )
    store.create_membership("OTXMEM-extreme")

    with pytest.raises(ValueError, match="Schema v2\\+ required"):
        store.write_membership(
            "OTXMEM-extreme", definition=definition, group_kind=ResponderGroupKind.EXTREME
        )


def test_write_membership_rejects_tampered_lineage_claim(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoints = build_endpoint(tmp_path, population_manifest, corrupt_row_hash=True)
    endpoint_manifest = endpoints.verify_endpoints(ENDPOINT_ID)
    definition = top_two_definition(
        endpoint_manifest.endpoints.semantic_content_sha256,
        population_manifest.individuals.semantic_content_sha256,
    )
    store = ExtremeResponderMembershipArtifactStore(
        tmp_path / "memberships", endpoint_store=endpoints, population_store=populations
    )
    store.create_membership("OTXMEM-extreme")

    with pytest.raises(ValueError, match="lineage does not match the verified population row"):
        store.write_membership(
            "OTXMEM-extreme", definition=definition, group_kind=ResponderGroupKind.EXTREME
        )


def test_write_membership_rejects_endpoint_hash_mismatch(tmp_path: Path) -> None:
    populations, population_manifest = build_population(tmp_path)
    endpoints = build_endpoint(tmp_path, population_manifest)
    definition = top_two_definition(
        "sha256:" + "c" * 64, population_manifest.individuals.semantic_content_sha256
    )
    store = ExtremeResponderMembershipArtifactStore(
        tmp_path / "memberships", endpoint_store=endpoints, population_store=populations
    )
    store.create_membership("OTXMEM-extreme")

    with pytest.raises(ValueError, match="Definition endpoint hash"):
        store.write_membership(
            "OTXMEM-extreme", definition=definition, group_kind=ResponderGroupKind.EXTREME
        )
