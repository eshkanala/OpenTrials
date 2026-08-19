"""OpenTrials Registry v0.1: immutable, versioned records of reusable scientific knowledge.

See ``registry.schema`` for the record model and ``registry.store`` for
the persistence backend.
"""

from opentrials.registry.schema import (
    RECORD_ID_PATTERN,
    SEMVER_PATTERN,
    EvidenceClass,
    ExperimentRecord,
    ModelVerificationRecord,
    ParameterEvidenceRecord,
    RegistryCompatibility,
    RegistryEntryManifest,
    RegistryRecordKind,
    RegistrySource,
)
from opentrials.registry.store import FilesystemRegistryBackend, RegistryBackend, RegistryError

__all__ = [
    "RECORD_ID_PATTERN",
    "SEMVER_PATTERN",
    "EvidenceClass",
    "ExperimentRecord",
    "FilesystemRegistryBackend",
    "ModelVerificationRecord",
    "ParameterEvidenceRecord",
    "RegistryBackend",
    "RegistryCompatibility",
    "RegistryEntryManifest",
    "RegistryError",
    "RegistryRecordKind",
    "RegistrySource",
]
