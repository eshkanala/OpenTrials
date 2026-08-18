"""Reference ``DataConnector``: the observed PK data bundled with ospsuite.

Proves the v0.8-A contract against one real source rather than only against
synthetic fixtures. ``ospsuite`` ships ``ObsDataAciclovir_1.pkml`` -- a
digitized, population mean +/- SD plasma-concentration curve from the
literature study the bundled Aciclovir PBPK model's own IV parameterization
was itself built from (its simulation is literally named "Vergin 1995 IV").

Every field this connector sets on ``Evidence``/``ObservedDataset`` was read
directly from the bundled file via ``adapters.osp.observed_data`` -- nothing
here is invented. One honesty note that matters scientifically: because this
is the same dataset the bundled model was calibrated against, it must never
be used as an *independent* validation dataset (that would be circular) --
it is registered with ``DatasetRole.CALIBRATION``, not
``EXTERNAL_VALIDATION``/``HELD_OUT_TEST``, and ``ObservedStudy.study_limitations``
says so explicitly. Closing the real, rights-cleared, held-out validation
gap (the founding spec's 0.2-D) is v0.8-C's job, not this connector's.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from opentrials.adapters.osp.observed_data import read_observed_dataset_pkml
from opentrials.compound import Compound, CompoundIdentity, Dose, Intervention, Regimen, Route
from opentrials.core.distributions import Distribution, DistributionPurpose, DistributionType
from opentrials.core.evidence import Evidence, EvidenceSet, EvidenceSourceType
from opentrials.core.scientific_value import ScientificValue, ValueType
from opentrials.evidence.connector import (
    DataConnectorIdentity,
    DataConnectorRunResult,
    RawSnapshot,
    SourceDescriptor,
    TransformationStep,
)
from opentrials.validation.observed import ObservedDataset, ObservedPkObservation, ObservedStudy
from opentrials.validation.study import DatasetRole

CONNECTOR_ID = "osp.bundled.observed-aciclovir-vergin-1995-iv"
CONNECTOR_VERSION = "1.0.0"

# The same license note this project already uses for the bundled Aciclovir
# PKML itself (models/profiles/aciclovir_iv.py) -- this observed-data file
# ships from the same ospsuite package under the same terms.
SOURCE_LICENSE = "Bundled ospsuite example; redistribution not asserted."

STUDY_ID = "vergin-1995-iv"
DATASET_ID = "OTOBS-vergin-1995-iv"
ANALYTE = "aciclovir"
MATRIX = "peripheral venous plasma"
FRACTION = "total"
MEASUREMENT = "concentration"


class OspBundledPkObservationsConnector:
    """Reads the bundled ``ObsDataAciclovir_1.pkml`` observed-data building block."""

    def __init__(self, *, r_libs_user: str | None = None) -> None:
        self._r_libs_user = r_libs_user

    @property
    def identity(self) -> DataConnectorIdentity:
        return DataConnectorIdentity(connector_id=CONNECTOR_ID, version=CONNECTOR_VERSION)

    def fetch(self) -> RawSnapshot:
        """Ask the local OSP installation to read and report the bundled PKML's fields.

        The "raw" content here is ``ospsuite``'s own parsed report of the
        ``DataSet`` -- the same "engine's unprocessed response is raw"
        convention this project already uses for simulation results (see
        ``RawSimulationResult``), since no independent PKML parser exists
        in this project and OSP is the one trusted interpreter of its own
        file format.
        """
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
        payload: dict[str, Any] = json.loads(snapshot.content.decode("utf-8"))
        metadata = payload["metadata"]
        x_values = payload["x_values"]
        y_values = payload["y_values"]
        y_error_values = payload["y_error_values"]
        if not (len(x_values) == len(y_values) == len(y_error_values)):
            raise ValueError(
                "Bundled observed dataset x/y/yError arrays must be the same length."
            )
        x_unit = payload["x_unit"]
        y_unit = payload["y_unit"]

        source = SourceDescriptor(
            # Matches ObservedDataset.source_identifier below exactly -- both
            # identify the same thing (the cited study), not the local file
            # path, which belongs in rights_notes instead.
            accession=metadata["Study Id"],
            license=SOURCE_LICENSE,
            rights_notes=(
                "Bundled with the ospsuite R package (extdata/ObsDataAciclovir_1.pkml) as "
                "example observed data; same terms as the Aciclovir.pkml simulation model "
                "it accompanies."
            ),
            retrieved_at=snapshot.retrieved_at,
        )

        dose_amount, dose_unit = _parse_dose(metadata["Dose"])
        intervention = Intervention(
            intervention_id=f"{STUDY_ID}-intervention",
            compound=Compound(
                identity=CompoundIdentity(compound_id=ANALYTE, preferred_name="Aciclovir")
            ),
            regimen=Regimen(
                regimen_id=f"{STUDY_ID}-regimen",
                doses=(
                    Dose(
                        amount=ScientificValue(
                            value=dose_amount, unit=dose_unit, value_type=ValueType.OBSERVED
                        ),
                        route=Route.INTRAVENOUS,
                        administration_time=ScientificValue(
                            value=0, unit=x_unit, value_type=ValueType.ASSUMED
                        ),
                    ),
                ),
            ),
        )

        study_evidence = Evidence(
            id=f"EV-{STUDY_ID}-study",
            source_type=EvidenceSourceType.PEER_REVIEWED_ARTICLE,
            source_identifier=metadata["Study Id"],
            citation=(
                f"{metadata['Study Id']} (digitized via ospsuite's bundled observed-data "
                "PKML; full bibliographic citation not available from the source's own "
                "metadata)"
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
        for index, (time_value, concentration, standard_deviation) in enumerate(
            zip(x_values, y_values, y_error_values, strict=True)
        ):
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
                    uncertainty=Distribution(
                        distribution_type=DistributionType.NORMAL,
                        purpose=DistributionPurpose.MEASUREMENT_UNCERTAINTY,
                        unit=y_unit,
                        parameters={
                            "mean": concentration,
                            "standard_deviation": standard_deviation,
                        },
                        description=payload.get("y_error_type"),
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
            "concentration (population mean +/- SD)",
            evidence_ids=(study_evidence.id,),
            population_description=(
                "Population mean +/- SD plasma concentration-time curve, digitized from the "
                f"published {metadata['Study Id']} study as bundled with ospsuite's example "
                "observed data. This is a summary curve, not per-subject observations -- "
                "'Patient Id' in the source metadata is a digitization grouping label, not "
                "an individual subject identifier."
            ),
            intervention=intervention,
            study_limitations=(
                "This is the same reference dataset the bundled Aciclovir OSP model's own "
                "IV parameterization was built from (the model's simulation is literally "
                "named 'Vergin 1995 IV'). Using it as an independent validation dataset "
                "would be circular. Registered here with DatasetRole.CALIBRATION as a "
                "v0.8-A architecture proof, not as validation evidence."
            ),
        )

        dataset = ObservedDataset(
            dataset_id=DATASET_ID,
            role=DatasetRole.CALIBRATION,
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
                    "Parsed the source metadata Dose field (e.g. '250 mg') into a "
                    "ScientificValue amount/unit pair for the registered Intervention."
                ),
                details={"source_field": "metaData.Dose"},
            ),
            TransformationStep(
                description=(
                    "Paired each (x, y, yError) triple into one ObservedPkObservation "
                    "(mean) plus one Evidence record carrying a NORMAL "
                    "MEASUREMENT_UNCERTAINTY Distribution built from y and yError -- "
                    "the source's own ArithmeticStdDev error type."
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
    """Locate the bundled ``ObsDataAciclovir_1.pkml`` the same way the aciclovir profile does.

    Mirrors ``models/profiles/aciclovir_iv.py``'s own ``artifact_uri`` -- the
    same local R library install, not re-derived from R at import time so
    this module can be imported without R present.
    """
    parsed = urlparse(
        "file:///Users/eshkanala/Library/R/arm64/4.6/library/ospsuite/extdata/"
        "ObsDataAciclovir_1.pkml"
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
