"""Second reference ``DataConnector``: a candidate *independent* observed dataset.

v0.8-B/C's evidence-acquisition step. ``ospsuite`` bundles a second observed
PK building block beyond the Vergin 1995 dataset v0.8-A already registered:
``ObsDataAciclovir_2.pkml``, digitized from Laskin et al. 1982 (a genuinely
different study, different research group, different decade, different
dosing paradigm -- mg/kg dose-ranging rather than a single fixed dose).
Confirmed directly (not assumed) that the pinned Aciclovir model's own PKML
contains zero references to "Laskin" anywhere, versus over a thousand to
"Vergin 1995" (the model's own parameter-identification test container is
literally named after it) -- the best available first-hand evidence that
Laskin 1982 was not part of this model's own calibration, unlike Vergin 1995.

This connector would have registered Laskin 1982 as a *candidate*
``DatasetRole.EXTERNAL_VALIDATION`` record -- its role was decided here,
before any compatibility or validation computation, per the explicit
"freeze the role before evaluation" discipline this milestone requires.
It never gets that far: ``normalize()`` discovers a more fundamental
problem first (see its own docstring) and raises
``IneligibleEvidenceCandidateError`` instead of producing a dataset --
proven directly, not asserted, in
``tests/unit/test_osp_bundled_laskin_1982_connector.py``.

One real generalization finding surfaced by this second connector, worth
recording even though it never reached the compatibility gate: unlike
Vergin 1995's ``ArithmeticStdDev`` errors, Laskin 1982's errors are reported
as ``GeometricStdDev`` -- a log-normal, not normal, uncertainty shape -- and
several later timepoints have no reported error at all (``null``). Had the
dose issue not already disqualified this candidate, this connector would
still have deliberately omitted ``Evidence.uncertainty`` entirely rather
than guess at an unverified geometric-SD-to-log-normal-parameter transform.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from opentrials.adapters.osp.observed_data import read_observed_dataset_pkml
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    DataConnectorRunResult,
    IneligibleEvidenceCandidateError,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole

CONNECTOR_ID = "osp.bundled.observed-aciclovir-laskin-1982-group-d"
CONNECTOR_VERSION = "1.0.0"

# Same bundling terms as the Vergin 1995 connector -- ospsuite's own example
# data license note, not an independently open-licensed source. This is
# recorded honestly as one of the reasons this candidate does not meet the
# higher rights bar an external validation dataset should ideally clear.
SOURCE_LICENSE = "Bundled ospsuite example; redistribution not asserted."

STUDY_ID = "laskin-1982-group-d"
DATASET_ID = "OTOBS-laskin-1982-group-d"
ANALYTE = "aciclovir"
MATRIX = "peripheral venous plasma"
FRACTION = "total"
MEASUREMENT = "concentration"


class OspBundledLaskin1982Connector:
    """Reads the bundled ``ObsDataAciclovir_2.pkml`` (Laskin 1982, Group D) building block."""

    def __init__(self, *, r_libs_user: str | None = None) -> None:
        self._r_libs_user = r_libs_user

    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id=CONNECTOR_ID, version=CONNECTOR_VERSION)

    def fetch(self) -> RawSnapshot:
        pkml_path = self._pkml_path()
        payload = read_observed_dataset_pkml(pkml_path, r_libs_user=self._r_libs_user)
        content = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        retrieved_at = _parse_generated_at(payload.get("generated_at"))
        return RawSnapshot(
            content=content, media_type="application/json", retrieved_at=retrieved_at
        )

    def normalize(self, snapshot: RawSnapshot) -> DataConnectorRunResult:
        """Build the candidate dataset -- point means only, no invented uncertainty.

        Laskin 1982's reported error type is ``GeometricStdDev``, which
        implies a log-normal uncertainty shape (``log_mean``/
        ``log_standard_deviation``), not the ``NORMAL`` shape the Vergin
        1995 connector uses for its ``ArithmeticStdDev`` errors. Converting
        a reported geometric SD into those log-space parameters correctly
        requires a transform this project has not independently verified,
        and several of Laskin's own later timepoints report no error value
        at all (``null``). Rather than guess, every ``Evidence`` record
        here carries only the reported point mean with ``uncertainty=None``
        -- an honest scope limitation, not a silent approximation.
        """
        payload: dict[str, Any] = json.loads(snapshot.content.decode("utf-8"))
        metadata = payload["metadata"]
        x_values = payload["x_values"]
        y_values = payload["y_values"]
        if len(x_values) != len(y_values):
            raise ValueError("Bundled observed dataset x/y arrays must be the same length.")
        x_unit = payload["x_unit"]
        y_unit = payload["y_unit"]

        source = SourceDescriptor(
            accession=metadata["Study Id"],
            license=SOURCE_LICENSE,
            rights_notes=(
                "Bundled with the ospsuite R package (extdata/ObsDataAciclovir_2.pkml) as "
                "example observed data, digitized from a paywalled 1982 publication "
                "(Laskin et al., Antimicrob Agents Chemother 21(3):393-398). Neither the "
                "bundled file nor the underlying publication carries a verified open reuse "
                "license -- this does not clear the same rights bar the v0.8-B/C search "
                "targeted for an external validation source."
            ),
            retrieved_at=snapshot.retrieved_at,
        )

        dose_amount, dose_unit = _parse_dose(metadata["Dose"])
        try:
            # Deliberately left in its reported weight-based unit (mg/kg),
            # not converted to an absolute mass -- no subject body weight is
            # available from the bundled metadata or the freely accessible
            # portion of the source publication to do that conversion
            # honestly. compound.intervention.Dose requires mass dimensions
            # for exactly this reason, and correctly refuses a weight-ratio
            # amount rather than silently accepting a scientifically
            # meaningless comparison later.
            dose = Dose(
                amount=ScientificValue(
                    value=dose_amount, unit=dose_unit, value_type=ValueType.OBSERVED
                ),
                route=Route.INTRAVENOUS,
                administration_time=ScientificValue(
                    value=0, unit=x_unit, value_type=ValueType.ASSUMED
                ),
                # Not stated anywhere in the bundled metadata or the
                # accessible abstract of the source publication -- left
                # absent rather than assumed to match the pinned model's
                # 10-minute protocol.
                infusion_duration=None,
            )
        except ValidationError as error:
            raise IneligibleEvidenceCandidateError(
                f"Laskin 1982 (Group D) reports its dose as {metadata['Dose']!r} -- a "
                "weight-normalized amount, not an absolute mass. No subject body weight is "
                "available from the bundled metadata or the freely accessible portion of "
                "the source publication to convert it honestly, and "
                "compound.intervention.Dose correctly requires mass dimensions for its "
                "amount. This candidate cannot be represented as an OpenTrials Intervention "
                "without inventing a body weight, which this connector will not do."
            ) from error
        intervention = Intervention(
            intervention_id=f"{STUDY_ID}-intervention",
            compound=Compound(
                identity=CompoundIdentity(compound_id=ANALYTE, preferred_name="Aciclovir")
            ),
            regimen=Regimen(regimen_id=f"{STUDY_ID}-regimen", doses=(dose,)),
        )

        study_evidence = Evidence(
            id=f"EV-{STUDY_ID}-study",
            source_type=EvidenceSourceType.PEER_REVIEWED_ARTICLE,
            source_identifier=metadata["Study Id"],
            citation=(
                "Laskin OL, Longstreth JA, Saral R, de Miranda P, Keeney R, Lietman PS. "
                "Pharmacokinetics and tolerance of acyclovir, a new anti-herpesvirus agent, "
                "in humans. Antimicrob Agents Chemother. 1982;21(3):393-398. (digitized via "
                "ospsuite's bundled observed-data PKML; the publication itself is paywalled "
                "and was not independently retrieved for this connector)"
            ),
            species=metadata.get("Species"),
            tissue=metadata.get("Organ"),
            measured_quantity=f"{ANALYTE} {payload['y_dimension'].lower()}",
            quality_metadata={"digitization_source": metadata.get("Source", "")},
            license=SOURCE_LICENSE,
            retrieval_version=CONNECTOR_VERSION,
            retrieved_at=snapshot.retrieved_at,
        )

        observation_evidence: list[Evidence] = []
        observations: list[ObservedPkObservation] = []
        for index, (time_value, concentration) in enumerate(zip(x_values, y_values, strict=True)):
            evidence_id = f"EV-{STUDY_ID}-obs-{index:02d}"
            observation_evidence.append(
                Evidence(
                    id=evidence_id,
                    source_type=EvidenceSourceType.PEER_REVIEWED_ARTICLE,
                    source_identifier=metadata["Study Id"],
                    species=metadata.get("Species"),
                    tissue=metadata.get("Organ"),
                    measured_quantity=f"{ANALYTE} {payload['y_dimension'].lower()}",
                    result=ScientificValue(
                        value=concentration, unit=y_unit, value_type=ValueType.OBSERVED
                    ),
                    license=SOURCE_LICENSE,
                    retrieval_version=CONNECTOR_VERSION,
                    retrieved_at=snapshot.retrieved_at,
                )
            )
            observations.append(
                ObservedPkObservation(
                    observation_id=f"OBS-{STUDY_ID}-{index:02d}",
                    subject_or_population_id=f"{STUDY_ID}-population-mean",
                    time=ScientificValue(
                        value=time_value, unit=x_unit, value_type=ValueType.OBSERVED
                    ),
                    value=ScientificValue(
                        value=concentration, unit=y_unit, value_type=ValueType.OBSERVED
                    ),
                    analyte=ANALYTE,
                    matrix=MATRIX,
                    fraction=FRACTION,
                    measurement=MEASUREMENT,
                    evidence_ids=(evidence_id,),
                )
            )

        study = ObservedStudy(
            study_id=STUDY_ID,
            title=f"{payload['name']}: {metadata['Dose']} {metadata['Route']} aciclovir plasma "
            "concentration (population mean)",
            evidence_ids=(study_evidence.id,),
            population_description=(
                "Population mean plasma concentration-time curve, digitized from the "
                f"published {metadata['Study Id']} study (Group D, {metadata['Dose']}) as "
                "bundled with ospsuite's example observed data. Per-subject body weight is "
                "not available, so the reported weight-based dose cannot be converted to an "
                "absolute administered mass."
            ),
            intervention=intervention,
            study_limitations=(
                "Candidate EXTERNAL_VALIDATION dataset: this is a different study from the "
                "one the pinned Aciclovir model was built from (confirmed directly -- 'Laskin' "
                "appears zero times anywhere in the model's own PKML, versus over a thousand "
                "references to 'Vergin 1995'), so it is not circular in the way the v0.8-A "
                "calibration connector's dataset would be. It has two known, independently "
                "disqualifying gaps this connector does not paper over: (1) the dose is "
                "reported per body weight (mg/kg) with no subject weight available anywhere "
                "accessible, so it cannot be compared against the pinned model's fixed "
                "absolute-mass administration; (2) infusion duration is not stated. Neither "
                "the bundled file nor its paywalled source publication carries a verified "
                "open reuse license, unlike the external, independently rights-cleared "
                "sources a v0.8-B acquisition ideally targets. Registered as a candidate for "
                "transparency, with its eligibility left to the compatibility gate to decide "
                "-- not asserted here."
            ),
        )

        dataset = ObservedDataset(
            dataset_id=DATASET_ID,
            role=DatasetRole.EXTERNAL_VALIDATION,
            study=study,
            observations=tuple(observations),
            license=SOURCE_LICENSE,
            source_identifier=metadata["Study Id"],
            provenance_ids=(study_evidence.id, *(evidence.id for evidence in observation_evidence)),
        )

        transformation_provenance = (
            TransformationStep(
                description=(
                    "Read the bundled DataSet building block via ospsuite's "
                    "loadDataSetFromPKML(), exactly as ospsuite itself parses it -- no "
                    "independent PKML interpretation."
                ),
                details={"worker": "adapters/osp/read_observed_dataset.R"},
            ),
            TransformationStep(
                description=(
                    "Kept the source metadata Dose field (e.g. '15 mg/kg') in its reported "
                    "weight-based unit rather than converting to an absolute mass -- no "
                    "subject body weight was available to do that conversion honestly."
                ),
                details={"source_field": "metaData.Dose"},
            ),
            TransformationStep(
                description=(
                    "Deliberately omitted Evidence.uncertainty for every observation: the "
                    "source reports GeometricStdDev errors (a log-normal shape), several "
                    "timepoints have no reported error at all, and this project has not "
                    "independently verified a geometric-SD-to-log-normal-parameter "
                    "transform. Only point means are carried."
                ),
                details={"y_error_type": payload.get("y_error_type") or ""},
            ),
        )

        return DataConnectorRunResult(
            identity=self.identity,
            source=source,
            raw_snapshot=snapshot,
            transformation_provenance=transformation_provenance,
            evidence=EvidenceSet(evidence=(study_evidence, *observation_evidence)),
            dataset=dataset,
        )

    @staticmethod
    def _pkml_path() -> Path:
        return _bundled_pkml_path()


def _bundled_pkml_path() -> Path:
    parsed = urlparse(
        "file:///Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/"
        "ObsDataAciclovir_2.pkml"
    )
    return Path(unquote(parsed.path))


def _parse_dose(dose_text: str) -> tuple[float, str]:
    parts = dose_text.split()
    if len(parts) != 2:
        raise ValueError(f"Expected a '<amount> <unit>' dose string, got {dose_text!r}.")
    amount_text, unit = parts
    return float(amount_text), unit


def _parse_generated_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Observed-dataset worker response is missing generated_at.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observed-dataset worker generated_at must include a timezone.")
    return parsed.astimezone(UTC)
