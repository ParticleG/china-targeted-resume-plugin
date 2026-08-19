"""Deterministic HTML, PDF, and PDF inspection helpers."""

from .html import render_html
from .inspect import InspectionConfig, inspect_pdf
from .pdf import PdfRenderResult, render_pdf, render_with_compaction

__all__ = [
    "InspectionConfig",
    "PdfRenderResult",
    "inspect_pdf",
    "render_html",
    "render_pdf",
    "render_with_compaction",
]
