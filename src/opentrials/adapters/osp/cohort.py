"""Registered logical field mapping for raw OSP population tables."""

from opentrials.cohort import FieldCatalog, LogicalField, LogicalFieldKind


def osp_population_field_catalog() -> FieldCatalog:
    """Return the canonical v0.4 mapping for OSP's raw population data frame.

    Definitions reference ``demographics.age``, ``demographics.sex``, and the
    anthropometric fields ``physiology.weight``/``physiology.height``/
    ``physiology.bmi``. Units and source columns were verified empirically
    against the installed ``ospsuite`` (weight in kg, height in dm, BMI in
    kg/dm**2 -- OSP's own base units, not silently reinterpreted). OSP column
    paths stay confined to this adapter; catalog content changes bump
    ``catalog_id`` rather than mutating a fixed version's meaning.
    """
    return FieldCatalog(
        catalog_id="osp.population.raw-v2",
        source_schema="osp.populationToDataFrame",
        subject_id_column="IndividualId",
        fields=(
            LogicalField(
                field_id="demographics.age",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|Age",
                unit="year",
            ),
            LogicalField(
                field_id="demographics.sex",
                kind=LogicalFieldKind.CATEGORICAL,
                source_column="Gender",
            ),
            LogicalField(
                field_id="physiology.weight",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|Weight",
                unit="kg",
            ),
            LogicalField(
                field_id="physiology.height",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|Height",
                unit="dm",
            ),
            LogicalField(
                field_id="physiology.bmi",
                kind=LogicalFieldKind.NUMERIC,
                source_column="Organism|BMI",
                unit="kg/dm**2",
            ),
        ),
    )
