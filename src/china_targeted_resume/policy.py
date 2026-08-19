"""Fail-closed evidence and disclosure policy gates."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from china_targeted_resume.models import DisclosureLevel, FactState


_EXPLICIT_FACT = re.compile(r"(?<![A-Z0-9])F([1-6])(?![A-Z0-9])", re.IGNORECASE)
_EXPLICIT_DISCLOSURE = re.compile(r"(?<![A-Z0-9])P([0-3])(?![A-Z0-9])", re.IGNORECASE)
_SENSITIVE = re.compile(
    r"(?:身份证|护照|银行卡|银行账户|家庭住址|内部地址|内部仓库|客户数据|客户名称|"
    r"薪资|工资|电话(?:号码)?|手机号|(?:内部|生产|真实)(?:凭据|密钥)|"
    r"personal\s+(?:id|address|phone)|passport|bank\s+account|customer\s+data|"
    r"internal\s+(?:address|identifier|repository)|salary|compensation|"
    r"credential\s*[:=]|password\s*[:=]|api\s+key\s*[:=]|access\s+token\s*[:=]|private\s+key\s*[:=])",
    re.IGNORECASE,
)
_FACT_PROSE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("F6", (
        "strictly confidential", "高度敏感", "绝密", "不得读取", "do not ingest",
        "内部凭据", "内部地址", "内部仓库", "客户数据", "customer data", "proprietary data",
    )),
    ("F5", ("待确认", "需要确认", "待本人确认", "unconfirmed", "needs confirmation", "to confirm", "unknown")),
    ("F4", ("合理推断", "推测", "可能", "据说", "assumed", "inferred", "possibly")),
    ("F3", (
        "尚未复核", "待复核", "缺少最近核验", "未作最近核验",
        "not recently verified", "recent verification missing", "verification required", "reverify",
    )),
    ("F2", ("有限口径", "约", "阶段记录", "limited scope", "approximate")),
    ("F1", (
        "明确事实", "来自原始综合资料", "本人确认", "可公开核验", "公开事实",
        "verified fact", "confirmed by the candidate", "source-backed fact", "publicly verified",
    )),
)
_DISCLOSURE_PROSE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("P3", (
        "不得披露", "不得使用", "禁止输出", "内部标识", "内部数据", "内部秘密",
        "do not disclose", "never disclose", "private only", "internal identifier", "internal data",
    )),
    ("P2", (
        "仅限求职", "仅限定向投递", "仅限面试", "定向材料", "targeted application only",
        "application only", "interview only",
    )),
    ("P1", (
        "可公开概述", "公司角色", "岗位职责", "通用技术栈", "抽象架构",
        "limited disclosure", "company role", "general stack", "abstract architecture",
    )),
    ("P0", (
        "公开链接", "开源链接", "已核验公开事实", "可公开引用",
        "public link", "open-source link", "verified public fact", "publishable link",
    )),
)


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _dump(record: Any) -> dict[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="python")
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "__dict__"):
        return vars(record).copy()
    return {}


def _field(record: Any, *names: str, default: Any = None) -> Any:
    data = _dump(record)
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def _enum_member(enum_type: type[Enum], marker: str) -> Enum:
    marker_upper = marker.upper()
    for member in enum_type:
        if member.name.upper() == marker_upper or str(member.value).upper() == marker_upper:
            return member
    raise ValueError(f"{marker!r} is not a valid {enum_type.__name__} marker")


def _mode(mode: Any) -> str:
    return str(_value(mode)).lower()


class PolicyDecision(BaseModel):
    """Auditable result of applying ingestion and output policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_as_candidate: bool
    allowed_in_output: bool
    confirmation_required: bool = False
    current_verification_required: bool = False
    reason_codes: tuple[str, ...] = ()
    record: dict[str, Any] | None = None


def parse_policy_markers(
    text: str,
    *,
    default_fact: FactState = FactState.F5,
    default_disclosure: DisclosureLevel = DisclosureLevel.P3,
) -> tuple[FactState, DisclosureLevel]:
    """Parse explicit markers first, then conservative prose markers.

    Ambiguous or absent text retains the fail-closed defaults. When prose contains
    multiple classifications, the most restrictive classification wins.
    """

    if not isinstance(text, str):
        return default_fact, default_disclosure
    facts = {f"F{match}" for match in _EXPLICIT_FACT.findall(text)}
    disclosures = {f"P{match}" for match in _EXPLICIT_DISCLOSURE.findall(text)}
    lowered = text.casefold()
    if not facts:
        facts = {marker for marker, phrases in _FACT_PROSE if any(p.casefold() in lowered for p in phrases)}
    if not disclosures:
        disclosures = {
            marker for marker, phrases in _DISCLOSURE_PROSE if any(p.casefold() in lowered for p in phrases)
        }
    fact_marker = max(facts, key=lambda marker: int(marker[1:])) if facts else None
    disclosure_marker = max(disclosures, key=lambda marker: int(marker[1:])) if disclosures else None
    fact = _enum_member(FactState, fact_marker) if fact_marker else default_fact
    disclosure = _enum_member(DisclosureLevel, disclosure_marker) if disclosure_marker else default_disclosure
    return fact, disclosure


def detect_sensitive_content(text: str) -> bool:
    """Return whether text contains a conservative sensitive-data marker."""

    return isinstance(text, str) and _SENSITIVE.search(text) is not None


def _freshness_fields(record: Any) -> tuple[Any, Any, Any]:
    stale = _field(record, "is_stale", "stale")
    verified = _field(record, "verified_at", "last_verified_at", "as_of")
    expires = _field(record, "expires_at", "valid_until", "stale_after")
    freshness = _field(record, "freshness")
    if freshness is not None:
        stale = _field(freshness, "stale", default=stale)
        verified = _field(freshness, "checked_at", default=verified)
        expires = _field(freshness, "expires_at", default=expires)
    return stale, verified, expires


def _is_stale(record: Any, now: datetime | date | None) -> bool:
    explicit, verified, expires = _freshness_fields(record)
    if explicit is not None:
        return bool(explicit)
    if verified is None:
        return True
    if expires is None:
        return False
    current = now or datetime.now(timezone.utc)
    if isinstance(current, datetime) and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        end = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        if isinstance(current, date) and not isinstance(current, datetime):
            return current > end.date()
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return current > end
    except (TypeError, ValueError):
        return True


def apply_evidence_policy(record: Any, mode: Any, *, now: datetime | date | None = None) -> PolicyDecision:
    """Apply ingestion and disclosure gates without exposing rejected content."""

    fact = str(_value(_field(record, "fact_state", "fact", "fact_level", default="F5"))).upper()
    disclosure = str(
        _value(_field(record, "disclosure_level", "disclosure", "privacy_level", default="P3"))
    ).upper()
    mode_value = _mode(mode)
    reasons: list[str] = []
    candidate = True
    output = True
    confirmation = False
    current_verification = False

    if fact == "F6" or disclosure == "P3":
        candidate = output = False
        reasons.append("excluded_from_processing")
    content = " ".join(
        str(_field(record, name, default="") or "")
        for name in ("proposed_claim", "safe_claim", "rendered_claim", "body", "snippet")
    )
    if detect_sensitive_content(content):
        candidate = output = False
        reasons.append("sensitive_content_detected")
    if fact in {"F4", "F5"}:
        output = False
        confirmation = fact == "F4"
        reasons.append("unconfirmed_fact" if fact == "F4" else "unsupported_fact")
    if disclosure == "P2" and mode_value != "targeted_application":
        output = False
        reasons.append("targeted_application_only")
    if fact == "F3":
        current_verification = True
        _, verified, _ = _freshness_fields(record)
        if _is_stale(record, now) or not verified:
            output = False
            confirmation = True
            reasons.append("current_verification_required")
    if fact not in {"F1", "F2", "F3", "F4", "F5", "F6"}:
        candidate = output = False
        reasons.append("unknown_fact_state")
    if disclosure not in {"P0", "P1", "P2", "P3"}:
        candidate = output = False
        reasons.append("unknown_disclosure_level")

    safe_record = None if not candidate else _dump(record)
    return PolicyDecision(
        allowed_as_candidate=candidate,
        allowed_in_output=output,
        confirmation_required=confirmation,
        current_verification_required=current_verification,
        reason_codes=tuple(dict.fromkeys(reasons)),
        record=safe_record,
    )


def is_allowed_in_output(record: Any, mode: Any) -> bool:
    """Return the final-content gate decision."""

    return apply_evidence_policy(record, mode).allowed_in_output
