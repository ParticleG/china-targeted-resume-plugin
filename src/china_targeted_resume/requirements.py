"""Deterministic, source-faithful job requirement extraction."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
import re
from typing import Any

from .models import Requirement, parse_atomic_experience_duration

_HEADING = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?([^:：]{1,80})[:：]?\s*$")
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)、])\s+")
_REQUIRED = re.compile(
    r"\b(?:must|required|requirements?|mandatory|minimum|qualifications?|"
    r"what we(?:'re| are) looking for|need(?:ed)?|shall)\b|"
    r"(?:必须|必需|必要条件|任职要求|任职资格|职位要求|基本要求|最低要求|硬性要求|必备条件)", re.I
)
_HARD_GATE = re.compile(
    r"\b(?:must|required|mandatory|minimum|shall)\b|"
    r"(?:必须|必需|必要条件|最低要求|硬性要求|必备条件)",
    re.I,
)
_PREFERRED = re.compile(
    r"\b(?:preferred|desirable|nice[ -]to[ -]have|plus|bonus)\b|"
    r"(?:优先|加分项?|更佳|最好|具备.*者优先)", re.I
)
_RESPONSIBILITY = re.compile(
    r"\b(?:responsibility|responsibilities|duties|what you(?:'ll| will) do|day.to.day)\b|"
    r"(?:岗位职责|工作职责|主要职责|工作内容|你将)", re.I
)
_SOFT = re.compile(
    r"\b(?:communication|collaboration|leadership|stakeholder|ownership|"
    r"problem.solving|teamwork|adaptab|influence|presentation)\b|"
    r"(?:沟通|协作|领导力|责任心|团队合作|抗压|表达|推动能力|问题解决)", re.I
)
_DOMAIN = re.compile(
    r"\b(?:industry|domain|sector|business knowledge|fintech|healthcare|"
    r"e.?commerce|automotive|manufacturing|saas)\b|"
    r"(?:行业|领域|业务知识|金融科技|医疗|电商|汽车|制造|企业服务)", re.I
)
_SECTION_KINDS = (
    ("preferred", _PREFERRED),
    ("responsibility", _RESPONSIBILITY),
    ("required", _REQUIRED),
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-/]{1,}|[\u4e00-\u9fff]{2,8}")
_STOP = {
    "and", "the", "with", "for", "from", "this", "that", "your", "you",
    "our", "will", "have", "able", "work", "years", "experience", "负责",
    "以及", "具有", "具备", "相关", "工作", "经验", "能力", "优先", "要求",
}


def _make_requirement(data: dict[str, Any]) -> Requirement:
    """Validate against the canonical model while tolerating model evolution."""
    fields = Requirement.model_fields
    aliases = {field.alias: name for name, field in fields.items() if field.alias}
    selected: dict[str, Any] = {}
    for key, value in data.items():
        target = key if key in fields else aliases.get(key)
        if target is not None:
            selected[target] = value
    return Requirement.model_validate(selected)


def _section_kind(heading: str | None) -> str | None:
    if not heading:
        return None
    for kind, pattern in _SECTION_KINDS:
        if pattern.search(heading):
            return kind
    return None


def _excluded_requirement_section(heading: str | None) -> bool:
    if not heading:
        return False
    return bool(re.fullmatch(
        r"(?:application|how to apply|application instructions?|"
        r"source metadata|about(?: the role)?|"
        r"申请(?:方式|说明)?|投递(?:方式|说明)?|来源信息|岗位介绍)",
        heading.casefold().strip(),
    ))


def _is_heading(line: str, candidate: str | None) -> bool:
    if candidate is None:
        return False
    if line.lstrip().startswith("#") or line.rstrip().endswith((":","：")):
        return True
    normalized = candidate.casefold().strip()
    return bool(re.fullmatch(
        r"(?:requirements?|qualifications?|preferred(?: qualifications?)?|"
        r"nice[ -]to[ -]have|responsibilit(?:y|ies)|duties|"
        r"任职要求|任职资格|职位要求|基本要求|最低要求|硬性要求|必备条件|"
        r"加分项?|优先条件|岗位职责|工作职责|主要职责|工作内容)",
        normalized,
    ))


def _category(text: str, section: str) -> str:
    if section == "responsibility":
        return "responsibility"
    if _SOFT.search(text):
        return "soft"
    if _DOMAIN.search(text):
        return "domain"
    return "requirement"


def _necessity(text: str, section: str | None) -> tuple[str, bool]:
    """Return source-derived necessity and hard-gate status.

    Repetition is intentionally absent: frequency is never classification
    evidence. Preferred language wins over broad required wording.
    """
    if section == "preferred" or _PREFERRED.search(text):
        return "preferred", False
    if section == "required" or _REQUIRED.search(text):
        return "required", bool(_HARD_GATE.search(text))
    if section == "responsibility":
        return "responsibility", False
    return "unknown", False


def parse_requirements(jd_text: str, *, source_id: str = "current-jd") -> list[Requirement]:
    """Extract explicit requirements with verbatim quotes and exact line spans.

    A requirement is a bullet/list entry within a recognized section, or a
    standalone sentence containing explicit necessity language. Continuation
    lines belong to the preceding bullet and retain their original newlines.
    """
    if not jd_text or not jd_text.strip():
        return []
    lines = jd_text.splitlines()
    records: list[tuple[int, int, str, str | None]] = []
    heading: str | None = None
    current: tuple[int, list[str], str | None] | None = None

    def flush(end: int) -> None:
        nonlocal current
        if current is not None:
            start, quote_lines, section = current
            records.append((start, end, "\n".join(quote_lines), section))
            current = None

    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        heading_match = _HEADING.match(line) if stripped else None
        candidate_heading = heading_match.group(1).strip() if heading_match else None
        is_heading = _is_heading(line, candidate_heading)
        candidate_section = _section_kind(candidate_heading) if is_heading else None
        if is_heading and not _BULLET.match(line):
            flush(index - 1)
            heading = candidate_heading
            continue
        section = _section_kind(heading)
        excluded_section = _excluded_requirement_section(heading)
        if _BULLET.match(line):
            flush(index - 1)
            if not excluded_section and (
                section is not None or _REQUIRED.search(line) or _PREFERRED.search(line)
            ):
                current = (index, [line], section)
            continue
        if current is not None and stripped and line[:1].isspace():
            current[1].append(line)
            continue
        flush(index - 1)
        if stripped and not excluded_section and (
            section is not None or _REQUIRED.search(line) or _PREFERRED.search(line)
        ):
            records.append((index, index, line, section))
    flush(len(lines))

    result: list[Requirement] = []
    for ordinal, (start, end, quote, section) in enumerate(records, 1):
        necessity, hard_gate = _necessity(quote, section)
        rid = f"REQ-{ordinal:03d}"
        result.append(_make_requirement({
            "requirement_id": rid,
            "text": _BULLET.sub("", quote, count=1).strip(),
            "verbatim_quote": quote,
            "category": _category(quote, section or ""),
            "necessity": necessity,
            "origin": "explicit",
            "source_ref": source_id,
            "source_span": {"start_line": start, "end_line": end},
            "confidence": 1.0,
            "hard_gate": hard_gate,
            "experience_duration": parse_atomic_experience_duration(quote),
        }))
    return result


def make_inferred_requirement(
    text: str,
    *,
    inference_basis: str,
    inference_source: str,
    confidence: float,
    requirement_id: str,
    category: str = "domain",
) -> Requirement:
    """Create a separately labelled inference; inferred items cannot be gates."""
    if not inference_basis.strip() or not inference_source.strip():
        raise ValueError("inferred requirements need both inference_basis and inference_source")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return _make_requirement({
        "requirement_id": requirement_id,
        "text": text,
        "verbatim_quote": None,
        "category": category,
        "necessity": "context",
        "origin": "inferred",
        "source_ref": inference_source,
        "source_span": None,
        "inference_basis": inference_basis,
        "confidence": confidence,
        "hard_gate": False,
    })


def keyword_review_signals(
    jd_text: str, *, minimum_count: int = 2
) -> list[dict[str, int | str]]:
    """Return frequency-only review signals, never classification inputs."""
    if minimum_count < 2:
        raise ValueError("minimum_count must be at least 2")
    counts = Counter(
        token.casefold() for token in _TOKEN.findall(jd_text)
        if token.casefold() not in _STOP
    )
    return [
        {"keyword": token, "count": count, "signal": "review-only"}
        for token, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= minimum_count
    ]


def requirement_dicts(requirements: Iterable[Requirement | Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Produce JSON-safe requirement records for dossier and refresh logic."""
    return [
        item.model_dump(mode="json", exclude_none=False)
        if isinstance(item, Requirement) else dict(item)
        for item in requirements
    ]



def merge_role_family_requirements(
    baseline: Iterable[Requirement | Mapping[str, Any]],
    company_delta: Iterable[Requirement | Mapping[str, Any]],
    *,
    company_explicit_source_ids: Iterable[str],
) -> list[Requirement]:
    """Merge baseline and company delta without fabricating company gates.

    Every source statement is preserved. Role-family and non-company sources
    are downgraded from Required/hard-gate because only an explicit company
    source may establish those company-specific conclusions.
    """
    explicit_sources = set(company_explicit_source_ids)
    output: list[Requirement] = []
    all_items = [(False, item) for item in baseline] + [
        (True, item) for item in company_delta
    ]
    for ordinal, (is_delta, item) in enumerate(all_items, 1):
        record = (
            item.model_dump(mode="python", exclude_none=False)
            if isinstance(item, Requirement) else dict(item)
        )
        source_ref = record.get("source_ref")
        company_explicit = (
            is_delta
            and source_ref in explicit_sources
            and str(record.get("origin", "explicit")) == "explicit"
        )
        if not company_explicit:
            if str(record.get("necessity", "")) == "required":
                record["necessity"] = "context"
            record["hard_gate"] = False
        record["requirement_id"] = f"REQ-{ordinal:03d}"
        output.append(Requirement.model_validate(record))
    return output