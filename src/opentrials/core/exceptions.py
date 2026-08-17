"""Domain-specific exceptions for the OpenTrials core."""


class OpenTrialsError(Exception):
    """Base exception for OpenTrials domain errors."""


class InvalidUnitError(OpenTrialsError, ValueError):
    """Raised when a unit cannot be parsed by the configured unit registry."""


class UnitCompatibilityError(OpenTrialsError, ValueError):
    """Raised when converting between dimensionally incompatible units."""
