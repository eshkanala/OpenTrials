"""Seed the default OpenTrials Registry with the real, hand-verified content this project ships.

Deliberately narrow, per explicit direction not to "try to ingest
everything": registers only the two shipped models, the compounds they
declare, and the one real, *eligible* evidence connector's dataset
(Vergin 1995). Laskin 1982 is excluded on purpose -- it is a real,
already-built connector, but genuinely ineligible (weight-normalized
dose with no recoverable body weight; see
``evidence.connectors.osp_bundled_laskin_1982``'s own docstring), and
registering an ineligible candidate as evidence would be exactly the
mistake this module exists to avoid.

No ``PARAMETER_EVIDENCE`` record is seeded here. Every candidate single
reusable value this project could point to (e.g. a physiology-target
parameter *path*) is a mapping, not a ``ScientificValue`` -- and every
genuinely numeric observed value already belongs to the dataset(s)
registered above, not a separate derived summary. Aggregating a
population *mean* concentration-time curve's own values into one number
would misrepresent what that data actually is (a curve, not a Cmax
sample); no such record is registered rather than fabricate one that
looks more authoritative than it is. Left open for a future pass once a
genuinely reusable candidate exists.
"""

from __future__ import annotations

from opentrials.compound import Compound, CompoundIdentity
from opentrials.evidence.connector import run_connector
from opentrials.evidence.connectors import OspBundledPkObservationsConnector
from opentrials.models.profiles.aciclovir_iv import ACICLOVIR_IV_CAPABILITY_PROFILE
from opentrials.models.profiles.midazolam_po import MIDAZOLAM_PO_CAPABILITY_PROFILE
from opentrials.registry import (
    EvidenceClass,
    RegistryBackend,
    RegistryCompatibility,
    RegistryError,
    RegistryRecordKind,
    RegistrySource,
)


def _already_registered(backend: RegistryBackend, logical_id: str) -> bool:
    try:
        backend.get_latest(logical_id)
        return True
    except RegistryError:
        return False


def seed_default_registry(backend: RegistryBackend, *, r_libs_user: str | None = None) -> list[str]:
    """Register the real models, their compounds, and eligible evidence this project ships.

    Idempotent: a ``logical_id`` already present in ``backend`` is left
    untouched rather than re-registered as a duplicate version. The
    dataset step is skipped entirely (not an error) if ``r_libs_user`` is
    not supplied, since fetching it requires real local OSP.

    Returns the list of ``logical_id``s newly registered by this call.
    """
    registered: list[str] = []

    for profile, logical_id in (
        (ACICLOVIR_IV_CAPABILITY_PROFILE, "osp.aciclovir.vergin-1995-iv"),
        (MIDAZOLAM_PO_CAPABILITY_PROFILE, "osp.midazolam.po-10mg-tablet"),
    ):
        if _already_registered(backend, logical_id):
            continue
        backend.put(
            RegistryRecordKind.MODEL,
            profile,
            logical_id=logical_id,
            evidence_class=EvidenceClass.CURATED,
            license=profile.package.manifest.license,
            source=RegistrySource(kind="model_package", identifier=logical_id),
        )
        registered.append(logical_id)

        compound_capability = profile.compounds[0]
        compound_logical_id = compound_capability.compound_id
        if not _already_registered(backend, compound_logical_id):
            compound = Compound(
                identity=CompoundIdentity(
                    compound_id=compound_capability.compound_id,
                    preferred_name=compound_capability.engine_molecule_id,
                )
            )
            backend.put(
                RegistryRecordKind.COMPOUND,
                compound,
                logical_id=compound_logical_id,
                evidence_class=EvidenceClass.CURATED,
                license=profile.package.manifest.license,
                source=RegistrySource(kind="model_package", identifier=logical_id),
                compatibility=RegistryCompatibility(model_ids=(logical_id,)),
            )
            registered.append(compound_logical_id)

    dataset_logical_id = "osp.bundled.observed-aciclovir-vergin-1995-iv"
    if r_libs_user is not None and not _already_registered(backend, dataset_logical_id):
        connector = OspBundledPkObservationsConnector(r_libs_user=r_libs_user)
        result = run_connector(connector)
        backend.put(
            RegistryRecordKind.DATASET,
            result.dataset,
            logical_id=dataset_logical_id,
            evidence_class=EvidenceClass.MEASURED,
            license=result.dataset.license,
            source=RegistrySource(
                kind="connector",
                identifier=connector.identity.connector_id,
                retrieved_at=result.raw_snapshot.retrieved_at,
            ),
            compatibility=RegistryCompatibility(model_ids=("osp.aciclovir.vergin-1995-iv",)),
        )
        registered.append(dataset_logical_id)

    return registered
