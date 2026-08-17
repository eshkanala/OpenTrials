"""Local immutable run-directory artifact contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

from opentrials.core.serialization import SchemaDocument

_ALLOWED_ARTIFACTS = frozenset({"manifest", "trial", "population", "results", "validation"})


class RunArtifactStore:
    """Write versioned JSON artifacts and integrity checksums for one run."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_run(self, run_id: str) -> Path:
        """Create an empty immutable run directory; reject reuse of an ID."""
        if not run_id.startswith("OTR-"):
            raise ValueError("Run IDs must begin with 'OTR-'.")
        run_directory = self.root / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        return run_directory

    def write_document(self, run_id: str, artifact: str, document: SchemaDocument) -> Path:
        """Write one canonical JSON artifact exactly once."""
        if artifact not in _ALLOWED_ARTIFACTS:
            raise ValueError(f"Unsupported run artifact: {artifact!r}.")
        path = self.root / run_id / f"{artifact}.json"
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Run directory does not exist: {run_id!r}.")
        if path.exists():
            raise FileExistsError(f"Run artifact already exists: {path}.")
        path.write_text(document.canonical_json() + "\n", encoding="utf-8")
        return path

    def write_checksums(self, run_id: str) -> Path:
        """Write SHA-256 checksums for all JSON artifacts in stable path order."""
        run_directory = self.root / run_id
        if not run_directory.is_dir():
            raise FileNotFoundError(f"Run directory does not exist: {run_id!r}.")
        lines = []
        for path in sorted(run_directory.glob("*.json")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"sha256:{digest}  {path.name}")
        checksum_path = run_directory / "checksums.txt"
        checksum_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return checksum_path
