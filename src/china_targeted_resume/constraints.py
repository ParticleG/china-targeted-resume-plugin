"""Application constraints, kept separate from role competencies."""

from __future__ import annotations

import re
from typing import Any

from .models import ApplicationConstraint

_CONSTRAINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("location", re.compile(r"\b(?:location|based in|on.?site|hybrid|remote)\b|(?:工作地点|办公地点|现场办公|混合办公|远程)", re.I)),
    ("work_authorization", re.compile(r"\b(?:work authorization|authorized to work|visa sponsorship|citizen(?:ship)?)\b|(?:工作许可|签证|公民身份)", re.I)),
    ("language", re.compile(r"\b(?:fluent|proficien(?:t|cy)|business level).{0,30}(?:english|mandarin|chinese|cantonese)\b|(?:英语|普通话|中文|粤语).{0,20}(?:流利|熟练|能力|水平)", re.I)),
    ("travel", re.compile(r"\b(?:travel|relocat(?:e|ion))\b|(?:出差|差旅|搬迁|异地)", re.I)),
    ("schedule", re.compile(r"\b(?:shift|weekend|on.?call|working hours|start date)\b|(?:轮班|倒班|周末|值班|工作时间|到岗时间)", re.I)),
    ("application_deadline", re.compile(r"\b(?:application deadline|apply by|closing date)\b|(?:申请截止|截止日期|投递截止)", re.I)),
    ("background_check", re.compile(r"\b(?:background check|security clearance|drug test)\b|(?:背景调查|背调|安全许可|药物检测)", re.I)),
)


def _make_constraint(data: dict[str, Any]) -> ApplicationConstraint:
    fields = ApplicationConstraint.model_fields
    aliases = {field.alias: name for name, field in fields.items() if field.alias}
    selected: dict[str, Any] = {}
    for key, value in data.items():
        target = key if key in fields else aliases.get(key)
        if target is not None:
            selected[target] = value
    return ApplicationConstraint.model_validate(selected)


def parse_application_constraints(
    jd_text: str, *, source_id: str = "current-jd"
) -> list[ApplicationConstraint]:
    """Parse logistics/eligibility statements with candidate status unknown.

    A JD describes the employer's constraint, not whether a candidate satisfies
    it. Consequently every detected constraint defaults to ``unknown``.
    """
    result: list[ApplicationConstraint] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(jd_text.splitlines(), 1):
        if not line.strip():
            continue
        for kind, pattern in _CONSTRAINTS:
            if not pattern.search(line):
                continue
            key = (kind, line)
            if key in seen:
                continue
            seen.add(key)
            cid = f"CON-{len(result) + 1:03d}"
            result.append(_make_constraint({
                "constraint_id": cid,
                "kind": kind,
                "status": "unknown",
                "required_value": line.strip(),
                "impact": f"Source {source_id}, line {line_number}",
            }))
    return result


def constraint_with_status(
    constraint: ApplicationConstraint, status: str
) -> ApplicationConstraint:
    """Return a validated status update without conflating it with parsing."""
    allowed = {"satisfied", "unsatisfied", "unknown", "not_applicable"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    data = constraint.model_dump(mode="python")
    data["status"] = status
    return ApplicationConstraint.model_validate(data)
