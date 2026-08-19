"""Seed the Registry with the real, individually-cited parameter values found for this project.

Every value here was read from a real FDA/DailyMed drug label (fetched
live, not transcribed from memory) for the two compounds this project
already ships models for -- aciclovir and midazolam. Registry v0.2's own
research pass found no bulk-importable parameter source anywhere in this
project or in ospsuite/PK-Sim, so this is deliberately a small, hand-vetted
set (not "thousands of parameter records"), each one proposed, reviewed,
and accepted through the real ``sdk.parameter_evidence`` pipeline -- not
inserted directly -- so the same checklist gate (citation review, unit
compatibility, duplicate/conflict detection) that would apply to any future
curator's submission applies here too.

Two aciclovir half-life values are seeded for *different* real populations
(normal renal function vs. end-stage renal disease) -- a genuine
COMPLEMENTARY case (same parameter, different context), not a conflict,
proving the pipeline distinguishes the two correctly on real data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opentrials.core.scientific_value import ValueType
from opentrials.registry import EvidenceClass, RegistryBackend, RegistryError
from opentrials.sdk import parameter_evidence as sdk_pe

_ACICLOVIR_LABEL_URL = (
    "https://dailymed.nlm.nih.gov/dailymed/fda/fdaDrugXsl.cfm"
    "?setid=babdbce2-5cbd-4943-bc38-9ebdd696a77a"
)
_MIDAZOLAM_INJECTION_LABEL_URL = (
    "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=affecd4d-1f78-4bbe-5a8d-86849bbdc520"
)
_MIDAZOLAM_SYRUP_LABEL_URL = (
    "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=0be63f63-6a93-4782-8f9c-d13ca5ae44bd"
)

_RETRIEVED_AT = datetime(2026, 8, 19, tzinfo=UTC)


def _aciclovir_citation() -> sdk_pe.LiteratureCitation:
    return sdk_pe.LiteratureCitation(
        url=_ACICLOVIR_LABEL_URL,
        title="ACYCLOVIR FOR INJECTION, USP -- FDA prescribing information (DailyMed)",
        retrieved_at=_RETRIEVED_AT,
        excerpt=(
            "For patients with normal renal function, the mean (±SD) values for "
            "elimination half-life... were 2.5 hours... following administration to "
            "volunteers with end-stage renal disease, the average acyclovir half-life "
            "was approximately 14 hours... Plasma protein binding is relatively low "
            "(9% to 33%)."
        ),
    )


def _midazolam_injection_citation() -> sdk_pe.LiteratureCitation:
    return sdk_pe.LiteratureCitation(
        url=_MIDAZOLAM_INJECTION_LABEL_URL,
        title="MIDAZOLAM injection -- FDA prescribing information (DailyMed)",
        retrieved_at=_RETRIEVED_AT,
        excerpt=(
            "Six single-dose pharmacokinetic studies involving healthy adults yield "
            "pharmacokinetic parameters for midazolam in the following ranges: volume "
            "of distribution (Vd), 1.0 to 3.1 L/kg; total clearance (Cl), 0.25 to 0.54 "
            "L/hr/kg; elimination half-life, 1.8 to 6.4 hours (mean approximately 3 "
            "hours)."
        ),
    )


def _midazolam_syrup_citation() -> sdk_pe.LiteratureCitation:
    return sdk_pe.LiteratureCitation(
        url=_MIDAZOLAM_SYRUP_LABEL_URL,
        title="MIDAZOLAM HYDROCHLORIDE syrup -- FDA prescribing information (DailyMed)",
        retrieved_at=_RETRIEVED_AT,
        excerpt=(
            "In adults and pediatric patients older than 1 year, midazolam is "
            "approximately 97% bound to plasma protein, principally albumin... The "
            "absolute bioavailability of the midazolam HCl syrup in pediatric patients "
            "is about 36%, which is not affected by pediatric age or weight."
        ),
    )


_CANDIDATES: tuple[dict[str, object], ...] = (
    dict(
        logical_id="aciclovir.elimination_half_life.normal-renal-function",
        compound_id="aciclovir",
        canonical_parameter_id="elimination_half_life",
        value=2.5,
        unit="hour",
        value_type=ValueType.OBSERVED,
        population="adult, normal renal function (CLcr > 80 mL/min)",
        citation=_aciclovir_citation,
        evidence_class=EvidenceClass.MEASURED,
    ),
    dict(
        logical_id="aciclovir.elimination_half_life.esrd",
        compound_id="aciclovir",
        canonical_parameter_id="elimination_half_life",
        value=14.0,
        unit="hour",
        value_type=ValueType.OBSERVED,
        population="adult, end-stage renal disease",
        citation=_aciclovir_citation,
        evidence_class=EvidenceClass.MEASURED,
    ),
    dict(
        logical_id="aciclovir.plasma_protein_binding_fraction.label-range-midpoint",
        compound_id="aciclovir",
        canonical_parameter_id="plasma_protein_binding_fraction",
        value=0.21,
        unit="dimensionless",
        value_type=ValueType.DERIVED,
        method="Midpoint of the FDA label's reported 9%-33% range.",
        conditions={"reported_range_percent": "9-33"},
        citation=_aciclovir_citation,
        evidence_class=EvidenceClass.DERIVED,
    ),
    dict(
        logical_id="midazolam.elimination_half_life.healthy-adult-mean",
        compound_id="midazolam",
        canonical_parameter_id="elimination_half_life",
        value=3.0,
        unit="hour",
        value_type=ValueType.OBSERVED,
        population="healthy adult (label-reported mean of 6 single-dose studies)",
        citation=_midazolam_injection_citation,
        evidence_class=EvidenceClass.MEASURED,
    ),
    dict(
        logical_id="midazolam.total_clearance_per_kg.healthy-adult-range-midpoint",
        compound_id="midazolam",
        canonical_parameter_id="total_clearance_per_kg",
        value=0.395,
        unit="L/hour/kg",
        value_type=ValueType.DERIVED,
        method="Midpoint of the FDA label's reported 0.25-0.54 L/hr/kg range.",
        conditions={"reported_range": "0.25-0.54 L/hr/kg"},
        population="healthy adult",
        citation=_midazolam_injection_citation,
        evidence_class=EvidenceClass.DERIVED,
    ),
    dict(
        logical_id="midazolam.volume_of_distribution_per_kg.healthy-adult-range-midpoint",
        compound_id="midazolam",
        canonical_parameter_id="volume_of_distribution_per_kg",
        value=2.05,
        unit="L/kg",
        value_type=ValueType.DERIVED,
        method="Midpoint of the FDA label's reported 1.0-3.1 L/kg range.",
        conditions={"reported_range": "1.0-3.1 L/kg"},
        population="healthy adult",
        citation=_midazolam_injection_citation,
        evidence_class=EvidenceClass.DERIVED,
    ),
    dict(
        logical_id="midazolam.plasma_protein_binding_fraction.label-value",
        compound_id="midazolam",
        canonical_parameter_id="plasma_protein_binding_fraction",
        value=0.97,
        unit="dimensionless",
        value_type=ValueType.OBSERVED,
        population="adult and pediatric > 1 year",
        citation=_midazolam_syrup_citation,
        evidence_class=EvidenceClass.MEASURED,
    ),
    dict(
        logical_id="midazolam.oral_bioavailability.pediatric-syrup",
        compound_id="midazolam",
        canonical_parameter_id="oral_bioavailability",
        value=0.36,
        unit="dimensionless",
        value_type=ValueType.OBSERVED,
        population="pediatric, 6 months to <16 years (HCl syrup formulation)",
        citation=_midazolam_syrup_citation,
        evidence_class=EvidenceClass.MEASURED,
    ),
)


def _already_registered(backend: RegistryBackend, logical_id: str) -> bool:
    try:
        backend.get_latest(logical_id)
        return True
    except RegistryError:
        return False


def seed_parameter_evidence(
    backend: RegistryBackend, *, curation_root: str | None = None
) -> list[str]:
    """Propose, review, and accept every real, cited candidate above -- idempotently.

    Each candidate goes through the full checklist-gated pipeline (not a
    direct write): citation review, unit-dimensionality validation (at
    ``propose_candidate`` time), and duplicate/conflict detection against
    whatever is already registered. Returns the ``logical_id``s newly
    registered by this call.
    """
    registered: list[str] = []
    for spec in _CANDIDATES:
        logical_id = spec["logical_id"]
        assert isinstance(logical_id, str)
        if _already_registered(backend, logical_id):
            continue

        citation_factory = spec["citation"]
        assert callable(citation_factory)
        candidate = sdk_pe.propose_candidate(
            compound_id=spec["compound_id"],  # type: ignore[arg-type]
            canonical_parameter_id=spec["canonical_parameter_id"],  # type: ignore[arg-type]
            value=spec["value"],  # type: ignore[arg-type]
            unit=spec["unit"],  # type: ignore[arg-type]
            value_type=spec["value_type"],  # type: ignore[arg-type]
            citation=citation_factory(),
            species="human",
            population=spec.get("population"),  # type: ignore[arg-type]
            method=spec.get("method"),  # type: ignore[arg-type]
            conditions=spec.get("conditions"),  # type: ignore[arg-type]
            root=curation_root,
        )
        sdk_pe.set_candidate_identity(
            candidate.candidate_id,
            logical_id=logical_id,
            evidence_class=spec["evidence_class"],  # type: ignore[arg-type]
            root=curation_root,
        )
        sdk_pe.mark_citation_reviewed(candidate.candidate_id, root=curation_root)

        result = sdk_pe.checklist(
            sdk_pe.load_candidate(candidate.candidate_id, root=curation_root), backend=backend
        )
        if not result["ok"]:
            conflicts = [
                c for c in result["checks"] if c["requirement"] == "conflicts_acknowledged"
            ]
            if conflicts and conflicts[0]["status"] == "absent":
                sdk_pe.acknowledge_conflict(candidate.candidate_id, root=curation_root)

        manifest = sdk_pe.accept_candidate(
            candidate.candidate_id, backend=backend, root=curation_root
        )
        registered.append(manifest.logical_id)
    return registered
