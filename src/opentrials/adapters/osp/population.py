"""Strict translation from OpenTrials population specifications to OSP requests."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrials.core.assumptions import Assumption, AssumptionScope
from opentrials.patient.patient import Sex
from opentrials.patient.population import PopulationSpec


class OspHumanPopulation(StrEnum):
    """Human population-model identifiers exposed by ospsuite 12.4.4.

    These are OSP model identifiers, not OpenTrials social identity categories.
    """

    ASIAN_TANAKA_1996 = "Asian_Tanaka_1996"
    BLACK_AMERICAN_NHANES_1997 = "BlackAmerican_NHANES_1997"
    EUROPEAN_ICRP_2002 = "European_ICRP_2002"
    JAPANESE_POPULATION = "Japanese_Population"
    MEXICAN_AMERICAN_WHITE_NHANES_1997 = "MexicanAmericanWhite_NHANES_1997"
    PREGNANT = "Pregnant"
    PRETERM = "Preterm"
    WHITE_AMERICAN_NHANES_1997 = "WhiteAmerican_NHANES_1997"


class OspDeterminismLevel(StrEnum):
    """Observed level of reproducibility for an OSP population generator."""

    UNVERIFIED = "UNVERIFIED"
    STRICT = "STRICT"
    ENGINE_DEPENDENT = "ENGINE_DEPENDENT"
    NONDETERMINISTIC = "NONDETERMINISTIC"


class PopulationFeatureStatus(StrEnum):
    """How a requested OpenTrials population feature was handled."""

    MAPPED = "MAPPED"
    UNSUPPORTED = "UNSUPPORTED"
    DEFAULTED = "DEFAULTED"


class PopulationTranslationItem(BaseModel):
    """One transparent field-level decision made during population translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_field: str = Field(min_length=1)
    status: PopulationFeatureStatus
    target_field: str | None = None
    detail: str = Field(min_length=1)


class PopulationTranslationReport(BaseModel):
    """Machine-readable mapping, defaulting, and failure information."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[PopulationTranslationItem, ...] = Field(min_length=1)
    assumptions: tuple[Assumption, ...] = ()
    determinism_level: OspDeterminismLevel = OspDeterminismLevel.UNVERIFIED

    @property
    def mapped(self) -> tuple[PopulationTranslationItem, ...]:
        return tuple(item for item in self.items if item.status is PopulationFeatureStatus.MAPPED)

    @property
    def unsupported(self) -> tuple[PopulationTranslationItem, ...]:
        return tuple(
            item for item in self.items if item.status is PopulationFeatureStatus.UNSUPPORTED
        )

    @property
    def defaulted(self) -> tuple[PopulationTranslationItem, ...]:
        return tuple(
            item for item in self.items if item.status is PopulationFeatureStatus.DEFAULTED
        )


class OspPopulationProfile(BaseModel):
    """Explicit OSP-specific reference population selected by the caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_population: OspHumanPopulation


class OspPopulationRequest(BaseModel):
    """The versioned, solver-owned input for a future OSP population worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    population_id: str = Field(min_length=1)
    number_of_individuals: int = Field(gt=0)
    requested_seed: int
    reference_population: OspHumanPopulation
    age_minimum_years: float | None = Field(default=None, ge=0)
    age_maximum_years: float | None = Field(default=None, ge=0)
    proportion_female_percent: float | None = Field(default=None, ge=0, le=100)
    source_generator_version: str = Field(min_length=1)
    source_provenance_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_age_bounds(self) -> OspPopulationRequest:
        if (self.age_minimum_years is None) != (self.age_maximum_years is None):
            raise ValueError("OSP population age bounds must be provided together.")
        if (
            self.age_minimum_years is not None
            and self.age_maximum_years is not None
            and self.age_minimum_years > self.age_maximum_years
        ):
            raise ValueError("OSP population minimum age cannot exceed maximum age.")
        return self


class OspPopulationTranslation(BaseModel):
    """A translated OSP request paired with its complete decision report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: OspPopulationRequest
    report: PopulationTranslationReport


class UnsupportedPopulationFeatureError(ValueError):
    """Raised when PopulationSpec contains a feature B3 cannot map safely."""

    def __init__(self, translation: OspPopulationTranslation) -> None:
        self.translation = translation
        unsupported_fields = ", ".join(item.source_field for item in translation.report.unsupported)
        super().__init__(f"Unsupported OSP population features: {unsupported_fields}.")


class OspPopulationTranslator:
    """Create strict, reviewable OSP population-generation requests.

    This class performs no random generation and has no R/OSP runtime dependency.
    """

    def __init__(self, profile: OspPopulationProfile) -> None:
        self._profile = profile

    def translate(self, specification: PopulationSpec) -> OspPopulationTranslation:
        items = [
            PopulationTranslationItem(
                source_field="id",
                status=PopulationFeatureStatus.MAPPED,
                target_field="population_id",
                detail="OpenTrials population ID is retained in the OSP worker request.",
            ),
            PopulationTranslationItem(
                source_field="size",
                status=PopulationFeatureStatus.MAPPED,
                target_field="number_of_individuals",
                detail="Maps directly to OSP numberOfIndividuals.",
            ),
            PopulationTranslationItem(
                source_field="seed",
                status=PopulationFeatureStatus.MAPPED,
                target_field="requested_seed",
                detail=(
                    "Maps directly to OSP population-characteristics seed. Strict reproducibility "
                    "is verified for the supported ospsuite 12.4.4 generation path."
                ),
            ),
            PopulationTranslationItem(
                source_field="generator_version",
                status=PopulationFeatureStatus.MAPPED,
                target_field="source_generator_version",
                detail="Retained as OpenTrials generation-request provenance.",
            ),
            PopulationTranslationItem(
                source_field="provenance_ids",
                status=PopulationFeatureStatus.MAPPED,
                target_field="source_provenance_ids",
                detail="Retained for the future population artifact provenance chain.",
            ),
            PopulationTranslationItem(
                source_field="osp_profile.reference_population",
                status=PopulationFeatureStatus.MAPPED,
                target_field="reference_population",
                detail="Explicitly selects an OSP human population-model identifier.",
            ),
        ]
        age_minimum_years: float | None = None
        age_maximum_years: float | None = None
        if specification.age_range is None:
            items.append(
                PopulationTranslationItem(
                    source_field="age_range",
                    status=PopulationFeatureStatus.DEFAULTED,
                    detail=(
                        "No OpenTrials age range was supplied. The eventual worker must record "
                        "the OSP default age bounds it uses."
                    ),
                )
            )
        else:
            age_minimum_years = specification.age_range.minimum.to("year").value
            age_maximum_years = specification.age_range.maximum.to("year").value
            items.append(
                PopulationTranslationItem(
                    source_field="age_range",
                    status=PopulationFeatureStatus.MAPPED,
                    target_field="age_minimum_years,age_maximum_years",
                    detail="Unit-aware age bounds are converted to years for OSP.",
                )
            )
        proportion_female_percent = self._translate_sexes(specification.sexes, items)
        self._report_unsupported_features(specification, items)
        report = PopulationTranslationReport(
            items=tuple(items),
            assumptions=(
                Assumption(
                    assumption_id="osp-generated-physiology",
                    statement=(
                        "Physiological characteristics not explicitly constrained by the "
                        "OpenTrials population request are generated by OSP."
                    ),
                    scope=AssumptionScope.POPULATION,
                    rationale=(
                        "v0.1 delegates physiological coherence and correlated human physiology "
                        "to the selected OSP population model."
                    ),
                    uncertainty_impact=(
                        "Generated physiology reflects the OSP population model and its parameter "
                        "distributions, not independently validated OpenTrials assumptions."
                    ),
                ),
            ),
            determinism_level=OspDeterminismLevel.STRICT,
        )
        translation = OspPopulationTranslation(
            request=OspPopulationRequest(
                population_id=specification.id,
                number_of_individuals=specification.size,
                requested_seed=specification.seed,
                reference_population=self._profile.reference_population,
                age_minimum_years=age_minimum_years,
                age_maximum_years=age_maximum_years,
                proportion_female_percent=proportion_female_percent,
                source_generator_version=specification.generator_version,
                source_provenance_ids=specification.provenance_ids,
            ),
            report=report,
        )
        if report.unsupported:
            raise UnsupportedPopulationFeatureError(translation)
        return translation

    @staticmethod
    def _translate_sexes(
        sexes: tuple[Sex, ...], items: list[PopulationTranslationItem]
    ) -> float | None:
        if not sexes:
            items.append(
                PopulationTranslationItem(
                    source_field="sexes",
                    status=PopulationFeatureStatus.DEFAULTED,
                    detail=(
                        "No OpenTrials biological-sex constraint was supplied. The eventual worker "
                        "must record the OSP default female proportion it uses."
                    ),
                )
            )
            return None
        if sexes == (Sex.FEMALE,):
            items.append(
                PopulationTranslationItem(
                    source_field="sexes",
                    status=PopulationFeatureStatus.MAPPED,
                    target_field="proportion_female_percent",
                    detail="Female-only request maps to 100 percent female in OSP.",
                )
            )
            return 100.0
        if sexes == (Sex.MALE,):
            items.append(
                PopulationTranslationItem(
                    source_field="sexes",
                    status=PopulationFeatureStatus.MAPPED,
                    target_field="proportion_female_percent",
                    detail="Male-only request maps to 0 percent female in OSP.",
                )
            )
            return 0.0
        items.append(
            PopulationTranslationItem(
                source_field="sexes",
                status=PopulationFeatureStatus.UNSUPPORTED,
                detail=(
                    "PopulationSpec does not express an OSP-compatible female proportion for "
                    "mixed, intersex, or unspecified biological-sex requests."
                ),
            )
        )
        return None

    @staticmethod
    def _report_unsupported_features(
        specification: PopulationSpec, items: list[PopulationTranslationItem]
    ) -> None:
        for source_field, value, detail in (
            (
                "inclusion_criteria",
                specification.inclusion_criteria,
                "Free-text inclusion criteria require a future machine-readable OSP mapping.",
            ),
            (
                "enrichment",
                specification.enrichment,
                "Population enrichment has no defined OSP translation in v0.1-B3a.",
            ),
            (
                "metadata",
                specification.metadata,
                "Arbitrary metadata is not a scientific population-generation input.",
            ),
        ):
            if value:
                items.append(
                    PopulationTranslationItem(
                        source_field=source_field,
                        status=PopulationFeatureStatus.UNSUPPORTED,
                        detail=detail,
                    )
                )
