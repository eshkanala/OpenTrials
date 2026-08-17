"""Unit-registry utilities shared by scientific domain models."""

from pint import UnitRegistry

# A single registry keeps parsing and dimensionality behavior consistent across
# all core scientific objects. Applications may add display conventions later,
# but core values always retain the unit supplied by their source.
unit_registry: UnitRegistry[float] = UnitRegistry(autoconvert_offset_to_baseunit=True)
