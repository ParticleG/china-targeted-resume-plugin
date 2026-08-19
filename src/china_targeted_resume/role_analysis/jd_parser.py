"""High-level deterministic JD parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
import re
from ..constraints import parse_application_constraints
from ..models import ApplicationConstraint, Requirement
from ..requirements import keyword_review_signals, parse_requirements


@dataclass(frozen=True, slots=True)
class ParsedJobDescription:
    source_ref: str
    source_hash: str
    line_count: int
    source_url: str | None
    published_date: date | None
    checked_at: datetime | None
    requirements: tuple[Requirement, ...]
    application_constraints: tuple[ApplicationConstraint, ...]
    review_signals: tuple[dict[str, int | str], ...]


def _labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    label = "|".join(re.escape(item) for item in labels)
    match = re.search(
        rf"^\s*[-*]?\s*(?:{label})\s*[:：]\s*(.+?)\s*$",
        text,
        re.I | re.M,
    )
    return match.group(1).strip() if match else None


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b", value)
    return date.fromisoformat(match.group(0)) if match else None


def _source_metadata(text: str) -> tuple[str | None, date | None, datetime | None]:
    raw_url = _labeled_value(
        text,
        ("Official source", "Source URL", "URL", "官方来源", "来源链接"),
    )
    url_match = re.search(r"https://[^)\]>\s]+", raw_url or "")
    published = _iso_date(
        _labeled_value(
            text,
            ("Published", "Published at", "Source date", "发布日期", "来源日期"),
        )
    )
    checked_date = _iso_date(
        _labeled_value(
            text,
            ("Accessed", "Accessed at", "Checked at", "访问日期", "核验日期"),
        )
    )
    checked_at = (
        datetime.combine(checked_date, time.min, tzinfo=UTC)
        if checked_date
        else None
    )
    return (
        url_match.group(0) if url_match else None,
        published,
        checked_at,
    )


def parse_job_description(
    text: str, *, source_ref: str = "current-jd"
) -> ParsedJobDescription:
    """Parse a complete or partial JD without candidate data or LLM calls."""
    if not text or not text.strip():
        raise ValueError("job description text is empty")
    source_url, published_date, checked_at = _source_metadata(text)
    return ParsedJobDescription(
        source_ref=source_ref,
        source_hash=sha256(text.encode("utf-8")).hexdigest(),
        line_count=len(text.splitlines()),
        source_url=source_url,
        published_date=published_date,
        checked_at=checked_at,
        requirements=tuple(parse_requirements(text, source_id=source_ref)),
        application_constraints=tuple(
            parse_application_constraints(text, source_id=source_ref)
        ),
        review_signals=tuple(keyword_review_signals(text)),
    )


parse_jd = parse_job_description
