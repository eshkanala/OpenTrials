"""Registered logical field mapping for raw OSP population tables."""

from opentrials.cohort import FieldCatalog, LogicalField, LogicalFieldKind


def osp_population_field_catalog() -> FieldCatalog:
    """Return the canonical v0.4 mapping for OSP's raw population data frame.

    Definitions reference ``demographics.age`` and ``demographics.sex`` only;
    OSP column paths stay confined to this adapter.
    """
    return FieldCatalog(
        catalog_id="osp.population.raw-v1",
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
        ),
    )
