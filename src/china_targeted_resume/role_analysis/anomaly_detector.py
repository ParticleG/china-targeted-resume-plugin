"""Source conflict, anomaly, and staleness detection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
import re
from typing import Any

_SOURCE_PRIORITY = {
    "current-official": 0,
    "official-current": 0,
    "official": 0,
    "snapshot": 1,
    "archived-snapshot": 1,
    "third-party": 2,
    "third_party": 2,
}


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    return dict(value)


def source_priority(source: Mapping[str, Any]) -> int:
    """Current official > snapshot > third party > unknown."""
    kind = str(source.get("source_type") or source.get("kind") or "").casefold()
    status = str(source.get("status") or "").casefold()
    publisher = str(source.get("publisher") or "").casefold()
    if "snapshot" in kind or "archive" in kind:
        return 1
    if "official" in kind or (status == "current" and publisher):
        return 0
    if "third" in kind:
        return 2
    return _SOURCE_PRIORITY.get(kind, 3)


def order_sources(sources: Iterable[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    """Order sources without deduplicating or dropping lower-priority claims."""
    records = [_dump(source) for source in sources]
    return sorted(
        records,
        key=lambda source: (
            source_priority(source),
            str(source.get("published_at") or source.get("source_date") or ""),
            str(source.get("url") or source.get("path") or source.get("id") or ""),
        ),
    )


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _subject(text: str) -> str:
    words = re.findall(r"[a-z0-9+#.]+|[\u4e00-\u9fff]+", text.casefold())
    stop = {"must", "required", "preferred", "需要", "必须", "优先", "具备"}
    return " ".join(word for word in words if word not in stop)


def detect_anomalies(
    requirements: Iterable[Mapping[str, Any] | Any],
    sources: Iterable[Mapping[str, Any] | Any],
    *,
    as_of: date | None = None,
    stale_after_days: int | None = 180,
) -> list[str]:
    """Report conflicts and staleness while retaining every source claim.

    Pass ``as_of`` to enable age-based staleness. Omitting it avoids consulting
    the wall clock, keeping identical inputs byte-for-byte deterministic.
    """
    source_records = order_sources(sources)
    anomalies: list[str] = []
    source_by_ref: dict[str, dict[str, Any]] = {}
    for source in source_records:
        ref = str(source.get("id") or source.get("source_id") or source.get("url") or source.get("path") or "unknown-source")
        source_by_ref[ref] = source
        published = _parse_date(source.get("published_at") or source.get("source_date"))
        explicit_stale = bool(source.get("stale"))
        age_stale = (
            as_of is not None
            and stale_after_days is not None
            and published is not None
            and (as_of - published).days > stale_after_days
        )
        if explicit_stale or age_stale:
            anomalies.append(
                f"STALE_SOURCE source={ref} date={published or 'unknown'} "
                f"priority={source_priority(source)}"
            )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in requirements:
        record = _dump(item)
        keywords = sorted(str(value).casefold() for value in record.get("keywords") or [])
        subject = "keywords:" + ",".join(keywords) if keywords else _subject(
            str(record.get("text") or record.get("summary") or "")
        )
        grouped[subject].append(record)
    for subject, claims in sorted(grouped.items()):
        if not subject or len(claims) < 2:
            continue
        conclusions = {
            (str(claim.get("necessity")), bool(claim.get("hard_gate", False)))
            for claim in claims
        }
        if len(conclusions) < 2:
            continue
        details = []
        for claim in claims:
            ref = str(claim.get("source_ref") or claim.get("source_id") or "unknown-source")
            priority = source_priority(source_by_ref.get(ref, {}))
            details.append(
                f"{claim.get('requirement_id', 'unknown')}@{ref}[priority={priority}]="
                f"{claim.get('necessity')}/hard_gate={bool(claim.get('hard_gate', False))}"
            )
        anomalies.append(f"SOURCE_CONFLICT subject={subject!r}: " + "; ".join(details))

    for item in requirements:
        record = _dump(item)
        if str(record.get("origin")) == "inferred" and bool(record.get("hard_gate")):
            anomalies.append(
                f"INVALID_INFERENCE_GATE requirement={record.get('requirement_id', 'unknown')}"
            )
        if str(record.get("origin")) == "explicit" and not record.get("verbatim_quote"):
            anomalies.append(
                f"MISSING_EXPLICIT_QUOTE requirement={record.get('requirement_id', 'unknown')}"
            )
    return anomalies


def anomaly_sections_by_hash(
    old_source_hashes: Mapping[str, str],
    new_source_hashes: Mapping[str, str],
) -> set[str]:
    """Return source IDs whose anomaly conclusions require recomputation."""
    return {
        source_id
        for source_id in old_source_hashes.keys() | new_source_hashes.keys()
        if old_source_hashes.get(source_id) != new_source_hashes.get(source_id)
    }
