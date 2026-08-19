"""Deterministic role-analysis public API."""

from .anomaly_detector import (
    anomaly_sections_by_hash,
    detect_anomalies,
    order_sources,
    source_priority,
)
from .competency_builder import build_role_competencies, merge_company_delta
from .jd_parser import ParsedJobDescription, parse_jd, parse_job_description
from .requirement_classifier import (
    classify_requirement,
    classify_requirements,
    infer_requirement,
)

__all__ = [
    "ParsedJobDescription",
    "anomaly_sections_by_hash",
    "build_role_competencies",
    "classify_requirement",
    "classify_requirements",
    "detect_anomalies",
    "infer_requirement",
    "merge_company_delta",
    "order_sources",
    "parse_jd",
    "parse_job_description",
    "source_priority",
]
