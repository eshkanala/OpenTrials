"""Human-readable views over already-verified OpenTrials run artifacts.

Reports never become a second scientific-analysis engine: every number
rendered here is read from an artifact a store's own ``verify_*()`` call
has already confirmed, or computed by the exact same shared analysis
function (``analysis.descriptive.calculate_descriptive_summary``) every
other comparison in this project already uses. This package formats and
visualizes; it does not recompute science with different rules.
"""

from opentrials.reporting.build import build_population_report, build_trial_report
from opentrials.reporting.data import ReportData
from opentrials.reporting.render_html import render_html
from opentrials.reporting.render_markdown import render_markdown

__all__ = [
    "ReportData",
    "build_population_report",
    "build_trial_report",
    "render_html",
    "render_markdown",
]
