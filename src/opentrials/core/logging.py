"""Minimal structured logging configuration for OpenTrials workflows."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the package logger without affecting the root logger.

    Callers may replace handlers for files, JSON output, or remote collection.
    Phase 0 keeps logs local and dependency-free so failed external engines can
    preserve their diagnostics without coupling the core to a logging service.
    """
    logger = logging.getLogger("opentrials")
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger
