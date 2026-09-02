"""Deterministic, evidence-grounded resume composition."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from china_targeted_resume.models import ResumeDocument, ResumeVariant

_BLOCKED_FACT_STATES = frozenset({"F4", "F5", "F6"})
_DIRECTNESS = {"已有直接证据": 5, "可迁移经验": 4, "有知识无实践": 2, "明确缺口": 0, "待确认": 0}
_FACT_STRENGTH = {"F1": 4, "F2": 3, "F3": 1}
_DISCLOSURE = {"P0": 3, "P1": 2, "P2": 1}
_PRIORITY = {"critical": 5, "high": 4, "required": 4, "medium": 3, "preferred": 2, "low": 1, "inferred": 1}
_PLACEHOLDER = re.compile(
    r"(?:\{\{.*?\}\}|\[[A-Z][A-Z0-9_ -]{2,}\]|"
    r"<(?:(?i:insert|replace|todo)|[A-Z][A-Z0-9_-]{2,})>|"
    r"\b(?i:TODO|TBD|TBC|PLACEHOLDER|LOREM IPSUM)\b)"
)
_RESUME_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "document_title": "Resume",
        "resume_for": "Resume for ",
        "contact_details": "Contact details",
        "phone": "Phone:",
        "email": "Email:",
        "location": "Location:",
        "summary": "Professional Summary",
        "skills": "Skills",
        "experience": "Experience",
        "projects": "Projects",
        "education": "Education",
        "honors": "Honors",
        "links": "Links",
        "technologies": "Technologies:",
        "selected_evidence": "Selected Evidence",
    },
    "zh": {
        "document_title": "简历",
        "resume_for": "简历：",
        "contact_details": "联系方式",
        "phone": "电话：",
        "email": "邮箱：",
        "location": "所在地：",
        "summary": "职业概述",
        "skills": "专业技能",
        "experience": "工作经历",
        "projects": "项目经历",
        "education": "教育经历",
        "honors": "荣誉奖项",
        "links": "相关链接",
        "technologies": "技术栈：",
        "selected_evidence": "补充经历",
    },
}


def resume_labels(locale: Any) -> Mapping[str, str]:
    """Return visible structural labels for the requested resume locale."""

    language = "zh" if str(locale or "").casefold().startswith("zh") else "en"
    return _RESUME_LABELS[language]


_EXCLUDED_RESUME_SECTION_MARKERS = (
    "overview",
    "background",
    "technology stack",
    "key challenges and decisions",
    "tech stack",
    "time and role",
    "public links",
    "fact boundary",
    "fact boundaries",
    "evidence boundary",
    "evidence boundaries",
    "collaboration and upstream boundaries",
    "system architecture and responsibility scope",
    "representative project mapping",
    "upstream inference layer",
    "pending confirmation",
    "risks and open questions",
    "unknowns and limitations",
    "概览",
    "背景与目标",
    "技术栈",
    "关键难点与决策",
    "时间与角色",
    "公开链接",
    "事实边界",
    "证据边界",
    "协作及上游边界",
    "系统架构与职责范围",
    "代表项目映射",
    "推理层（上游）",
    "待确认信息",
    "风险与待确认",
)
_RESUME_SECTION_PRIORITIES = (
    (4, ("personal work", "个人工作", "results and metrics", "结果与指标", "量化信息", "outcomes")),
    (3, ("engineering and verification", "工程化与验证")),
)
_PREDICATE_OPTIONAL_SECTION_MARKERS = (
    "results and metrics",
    "结果与指标",
    "量化信息",
    "outcomes",
    "engineering and verification",
    "工程化与验证",
)
_RESUME_CONTEXT_SECTION_MARKERS = (
    "overview",
    "background",
    "project positioning",
    "project context",
    "概览",
    "背景与目标",
    "项目定位",
    "项目背景",
)
_NON_RESUME_FIELD_LABEL = re.compile(
    r"^(?:(?:project (?:nature|positioning|scope|phase|date)|"
    r"(?:responsibility|role|team) scope|personal contribution|archive goal|"
    r"fact boundary|evidence boundary|limitations?|pending confirmation)|"
    r"(?:项目性质|项目定位|项目范围|项目时间|所属阶段|相关岗位阶段|"
    r"职责方向|职责范围|角色范围|个人角色|个人贡献|团队工作|问题|决策|"
    r"共享状态|数据与状态|归档目标|事实边界|证据边界|边界说明|限制说明|"
    r"待确认信息)|(?:\d+\s*人(?:小组|团队)))\s*[:：]",
    re.I,
)
_EVIDENCE_BOUNDARY_LANGUAGE = re.compile(
    r"(?:current\s+checkout|only\s+(?:proves?|establishes?|shows?)|"
    r"does\s+not\s+(?:prove|establish|demonstrate|mean|implement)|"
    r"(?:must|do)\s+not\s+(?:infer|claim|describe)|"
    r"cannot\s+(?:prove|establish|replace|be\s+claimed)|not\s+evidence\s+of)|"
    r"(?:当前\s*checkout|不据此(?:声明|推断)|只能证明|不证明|不实现|"
    r"不计入(?:已交付|交付能力)|不把[^。；;\n]{0,80}计为|不归为|不表述为|"
    r"不得(?:据此|描述|推断|声明)|不能(?:据此|证明|替代|声称)|"
    r"不自动(?:代表|证明)|不(?:等同于|代表|表示|视为))",
    re.I,
)
_ACTION_PREDICATE = re.compile(
    r"\b(?:implemented|built|designed|developed|delivered|automated|reduced|"
    r"improved|introduced|maintained|deployed|integrated|validated|controlled|"
    r"mapped|synchronized|used|created|established|migrated|resolved)\b|"
    r"(?:实现|开发|构建|设计|建立|引入|改造|优化|降低|提升|完成|交付|"
    r"维护|负责|推动|建设|拆分|协调|集成|部署|验证|处理|控制|读取|同步|复用|"
    r"保护|限制|生成|识别|发现|映射|采用|使用|沉淀|包装|管理|修复|解决|"
    r"迁移|对账|清理|编排|建模|固化|复核|保留|释放|评估|研究|避免|分层|"
    r"绑定|减少)",
    re.I,
)
_CURRENT_DATE_ENDINGS = frozenset({"至今", "present", "current", "now"})









def _plain(value: Any) -> Any:
    return value.model_dump(mode="python") if hasattr(value, "model_dump") else value


def _dict(value: Any) -> dict[str, Any]:
    value = _plain(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _get(value: Any, *names: str, default: Any = None) -> Any:
    data = _dict(value)
    for name in names:
        if name in data and data[name] is not None:
            result = data[name]
            return result.value if hasattr(result, "value") else result
    return default


def _items(value: Any) -> list[Any]:
    value = _plain(value)
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    return list(value) if isinstance(value, Iterable) else [value]


def _mode(mode: Any) -> str:
    return str(getattr(mode, "value", mode) or "targeted_application")


def contains_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.search(text))


def _source(record: Any) -> dict[str, Any]:
    return _dict(_get(record, "source", default={}))


def _source_relevance(source: Mapping[str, Any]) -> int:
    path = f"/{str(source.get('path') or '').casefold().strip('/')}/"
    if "/work/" in path:
        return 5
    if "/company-projects/" in path:
        return 4
    if "/community-projects/" in path or "/personal-projects/" in path:
        return 3
    if "/projects/" in path:
        return 2
    if "/profile/" in path:
        return 1
    return 0


def provenance_ref(record: Any) -> str | None:
    """Build a stable source reference without copying source content."""
    direct = _get(record, "provenance_ref", "source_ref")
    if direct:
        return str(direct)
    source = _source(record)
    path = source.get("path")
    section = source.get("section")
    digest = source.get("source_hash")
    if path and section and digest:
        return f"{path}#{section}@{digest}"
    return None

def fact_ledger_ref(text: Any, source_ref: str) -> str:
    """Associate a visible fact with a source without storing the fact twice."""
    fact_hash = hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()[:20]
    source_hash = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:20]
    return f"fact:{fact_hash}:{source_hash}"


def _ledger_values(refs: list[str], values: Iterable[Any], source_refs: Sequence[str]) -> None:
    for source_ref in source_refs:
        refs.append(source_ref)
        refs.extend(fact_ledger_ref(value, source_ref) for value in values if value is not None and str(value).strip())



def evidence_is_allowed(record: Any, mode: Any = "targeted_application") -> bool:
    fact = str(_get(record, "fact_state", default=""))
    disclosure = str(_get(record, "disclosure", default=""))
    claim = str(_get(record, "safe_claim", default="")).strip()
    if fact in _BLOCKED_FACT_STATES or fact not in _FACT_STRENGTH:
        return False
    freshness = _dict(_get(record, "freshness", default={}))
    if fact == "F3" and (freshness.get("stale") or not freshness.get("checked_at")):
        return False
    if disclosure == "P3" or disclosure not in _DISCLOSURE:
        return False
    if disclosure == "P2" and _mode(mode) != "targeted_application":
        return False
    return bool(claim and not contains_placeholder(claim) and provenance_ref(record))


def _resume_section_priority(section: str) -> int | None:
    if any(marker in section for marker in _EXCLUDED_RESUME_SECTION_MARKERS):
        return None
    for priority, markers in _RESUME_SECTION_PRIORITIES:
        if any(marker in section for marker in markers):
            return priority
    return 1


def resume_claim_priority(
    record: Any,
    *,
    text: str | None = None,
) -> int | None:
    """Classify candidate-facing claim quality without deleting audit evidence."""
    source = _source(record)
    path = (
        "/"
        + str(source.get("path") or "")
        .replace("\\", "/")
        .casefold()
        .strip("/")
        + "/"
    )
    section = str(source.get("section") or "").casefold().strip()
    claim = str(
        text if text is not None else _get(record, "safe_claim", default="")
    ).strip()
    if not claim or "/personal-data/meta/" in path:
        return None
    section_priority = _resume_section_priority(section)
    if section_priority is None:
        return None
    if re.search(r"[\u2500-\u257f]", claim) or claim.endswith((":", "：")):
        return None
    if _NON_RESUME_FIELD_LABEL.search(claim):
        return None
    if _EVIDENCE_BOUNDARY_LANGUAGE.search(claim):
        return None
    predicate_optional = any(
        marker in section
        for marker in _PREDICATE_OPTIONAL_SECTION_MARKERS
    )
    if not predicate_optional and not _ACTION_PREDICATE.search(claim):
        return None
    return section_priority


def resume_claim_is_substantive(
    record: Any,
    *,
    text: str | None = None,
) -> bool:
    """Return whether evidence is suitable as a standalone resume fact."""
    return resume_claim_priority(record, text=text) is not None

def resume_context_is_substantive(
    record: Any,
    *,
    text: str | None = None,
) -> bool:
    """Allow source-backed project context without admitting it as a bullet."""
    source = _source(record)
    path = (
        "/"
        + str(source.get("path") or "")
        .replace("\\", "/")
        .casefold()
        .strip("/")
        + "/"
    )
    section = str(source.get("section") or "").casefold().strip()
    claim = str(
        text if text is not None else _get(record, "safe_claim", default="")
    ).strip()
    if (
        not claim
        or "/personal-data/meta/" in path
        or not any(marker in section for marker in _RESUME_CONTEXT_SECTION_MARKERS)
        or len(claim) < 12
        or len(claim) > 280
        or claim.endswith((":", "："))
        or contains_placeholder(claim)
        or re.search(r"[\u2500-\u257f]", claim)
        or _NON_RESUME_FIELD_LABEL.search(claim)
        or _EVIDENCE_BOUNDARY_LANGUAGE.search(claim)
    ):
        return False
    return True


def _freshness(record: Any, now: datetime | None) -> int:
    data = _dict(_get(record, "freshness", default={}))
    if data.get("stale"):
        return 0
    if not data.get("dynamic", False):
        return 3
    checked = data.get("checked_at")
    if not checked:
        return 0
    try:
        stamp = checked if isinstance(checked, datetime) else datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if now is None:
            return int(stamp.timestamp())
        days = max(0, (now - stamp.astimezone(UTC)).days)
    except (TypeError, ValueError):
        return 0
    return 3 if days <= 30 else 2 if days <= 180 else 1


def _mapping_data(evidence_id: str, mappings: Sequence[Any]) -> tuple[list[str], float]:
    requirement_ids: list[str] = []
    priority = 0.0
    for mapping in mappings:
        if evidence_id in {str(value) for value in _items(_get(mapping, "evidence_ids", default=[]))}:
            requirement_ids.extend(str(value) for value in _items(_get(mapping, "requirement_id", "requirement_ids", default=[])))
            priority = max(priority, float(_get(mapping, "resume_priority", default=0.0)))
    return requirement_ids, priority


def _importance(requirements: Sequence[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for requirement in requirements:
        requirement_id = str(_get(requirement, "requirement_id", "id", default=""))
        value = str(_get(requirement, "priority", "necessity", default="medium")).lower()
        if requirement_id:
            result[requirement_id] = _PRIORITY.get(value, 2)
    return result


def evidence_rank_key(record: Any, *, mappings: Sequence[Any] = (), requirements: Sequence[Any] = (), now: datetime | None = None) -> tuple[Any, ...]:
    """Rank importance, strength/directness, freshness, verifiability, clarity,
    disclosure suitability, and page cost, with stable ID tie-breaking.
    """
    evidence_id = str(_get(record, "evidence_id", "id", default=""))
    mapped_ids, mapping_priority = _mapping_data(evidence_id, mappings)
    requirement_ids = [str(value) for value in _items(_get(record, "requirement_ids", default=[]))] + mapped_ids
    importance = _importance(requirements)
    requirement_score = max((importance.get(value, 2) for value in requirement_ids), default=0)
    source = _source(record)
    verifiability = sum(bool(source.get(key)) for key in ("path", "section", "source_hash"))
    scope = str(_get(record, "contribution_scope", default="")).lower()
    clarity = 2 if any(token in scope for token in ("personal", "individual", "owned", "led")) else 1 if scope else 0
    claim = str(_get(record, "safe_claim", default=""))
    page_cost = max(1, (len(claim) + 79) // 80)
    return (-requirement_score, -mapping_priority, -_FACT_STRENGTH.get(str(_get(record, "fact_state", default="")), 0), -_DIRECTNESS.get(str(_get(record, "match_state", default="")), 0), -_source_relevance(source), -_freshness(record, now), -verifiability, -clarity, -_DISCLOSURE.get(str(_get(record, "disclosure", default="")), 0), page_cost, evidence_id)


def rank_evidence(evidence_records: Sequence[Any], *, mappings: Sequence[Any] = (), requirements: Sequence[Any] = (), mode: Any = "targeted_application", now: datetime | None = None) -> list[Any]:
    allowed = [record for record in evidence_records if evidence_is_allowed(record, mode)]
    return sorted(allowed, key=lambda record: evidence_rank_key(record, mappings=mappings, requirements=requirements, now=now))


def _profile_collection(profile: Any, name: str) -> list[dict[str, Any]]:
    return [_dict(item) for item in _items(_get(profile, name, default=[])) if _dict(item)]


def _metadata_refs(item: Mapping[str, Any]) -> list[str]:
    return [str(value) for value in _items(item.get("provenance_refs") or item.get("source_refs")) if value]


def _record_matches(item: Mapping[str, Any], record: Any) -> bool:
    evidence_id = str(_get(record, "evidence_id", default=""))
    explicit_ids = {str(value) for value in _items(item.get("evidence_ids") or item.get("claim_ids"))}
    if explicit_ids:
        return evidence_id in explicit_ids
    refs = set(_metadata_refs(item))
    return bool(refs and provenance_ref(record) in refs)


def _bullet(record: Any, position: int, total: int) -> dict[str, Any]:
    ref = provenance_ref(record)
    result: dict[str, Any] = {
        "text": str(_get(record, "safe_claim")).strip(),
        "claim_ids": [str(_get(record, "evidence_id"))],
        "priority": 1.0 if total <= 1 else round(1.0 - (position / (total - 1)), 6),
    }
    # Supported by the canonical model revision; harmlessly omitted only for an
    # older model loaded concurrently during installation.
    if "provenance_refs" in getattr(__import__("china_targeted_resume.models", fromlist=["ResumeBullet"]).ResumeBullet, "model_fields", {}):
        result["provenance_refs"] = [ref]
    return result


def _contact(profile: Any, mode: str) -> dict[str, Any]:
    raw = _dict(_get(profile, "contact", default={}))
    if not raw:
        raw = {key: _get(profile, key, default=None) for key in ("name", "phone", "email", "location", "links")}
    result = {key: raw[key] for key in ("name", "phone", "email", "location") if raw.get(key) and not contains_placeholder(str(raw[key]))}
    result.setdefault("name", "")
    links = []
    for link in _items(raw.get("links") or _get(profile, "links", default=[])):
        item = _dict(link)
        if item.get("label") and item.get("url") and not contains_placeholder(str(item)):
            links.append({"label": str(item["label"]), "url": str(item["url"])})
    result["links"] = links
    if mode == "public_portfolio":
        result.pop("phone", None)
    return result


def _group_experience(profile: Any, ranked: Sequence[Any], assigned: set[str], refs: list[str]) -> list[dict[str, Any]]:
    output = []
    for item in _profile_collection(profile, "experience"):
        matched = [record for record in ranked if _record_matches(item, record)]
        if not matched:
            continue
        assigned.update(str(_get(record, "evidence_id")) for record in matched)
        refs.extend(_metadata_refs(item))
        output.append({
            "organization": str(item.get("organization") or item.get("company") or ""),
            "role": str(item.get("role") or item.get("title") or ""),
            "location": item.get("location"),
            "start_date": str(item.get("start_date") or ""),
            "end_date": str(item.get("end_date") or ""),
            "context": item.get("context"),
            "bullets": [_bullet(record, ranked.index(record), len(ranked)) for record in matched],
        })
    return output


def _group_projects(profile: Any, ranked: Sequence[Any], assigned: set[str], refs: list[str]) -> list[dict[str, Any]]:
    output = []
    for item in _profile_collection(profile, "projects"):
        matched = [record for record in ranked if _record_matches(item, record)]
        if not matched:
            continue
        assigned.update(str(_get(record, "evidence_id")) for record in matched)
        refs.extend(_metadata_refs(item))
        output.append({
            "name": str(item.get("name") or item.get("title") or "Selected Project"),
            "role": item.get("role"), "context": item.get("context"),
            "start_date": item.get("start_date"), "end_date": item.get("end_date"),
            "technologies": [str(value) for value in _items(item.get("technologies"))],
            "bullets": [_bullet(record, ranked.index(record), len(ranked)) for record in matched],
        })
    return output


def _skills(profile: Any, allowed_ids: set[str], refs: list[str]) -> list[dict[str, Any]]:
    groups = []
    for group in _profile_collection(profile, "skills"):
        values = []
        for item in _items(group.get("items")):
            data = _dict(item)
            if data:
                evidence_ids = {str(value) for value in _items(data.get("evidence_ids") or data.get("claim_ids"))}
                if evidence_ids and evidence_ids <= allowed_ids:
                    text = str(data.get("text") or data.get("name") or "").strip()
                    if text and not contains_placeholder(text):
                        values.append(text)
                        refs.extend(_metadata_refs(data))
            elif isinstance(item, str) and group.get("evidence_ids") and set(map(str, _items(group["evidence_ids"]))) <= allowed_ids:
                values.append(item)
        if values:
            groups.append({"group": str(group.get("group") or group.get("name") or "Core Skills"), "items": list(dict.fromkeys(values))})
            refs.extend(_metadata_refs(group))
    return groups


def _provenanced_metadata(profile: Any, section: str, refs: list[str]) -> list[dict[str, Any]]:
    output = []
    for item in _profile_collection(profile, section):
        item_refs = _metadata_refs(item)
        if item_refs and not contains_placeholder(json.dumps(item, ensure_ascii=False, default=str)):
            refs.extend(item_refs)
            output.append({key: value for key, value in item.items() if key not in {"provenance_refs", "source_refs", "evidence_ids", "claim_ids"}})
    return output

def _scalars(value: Any) -> list[str]:
    value = _plain(value)
    if isinstance(value, Mapping):
        return [text for key, item in value.items() if key not in {"provenance_refs", "source_refs", "evidence_ids", "claim_ids"} for text in _scalars(item)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [text for item in value for text in _scalars(item)]
    return [str(value)] if value is not None and str(value).strip() else []


def _add_fact_ledger(profile: Any, target: Mapping[str, Any], payload: Mapping[str, Any], ranked: Sequence[Any], refs: list[str]) -> None:
    profile_data = _dict(profile)
    root_refs = _metadata_refs(profile_data)
    contact_data = _dict(profile_data.get("contact"))
    _ledger_values(refs, _scalars(payload.get("contact", {})), _metadata_refs(contact_data) or root_refs)
    target_refs = [str(value) for value in _items(target.get("source_refs")) if value]
    headline_refs = _metadata_refs(_dict(profile_data.get("headline_metadata"))) or root_refs or target_refs
    summary_refs = _metadata_refs(
        _dict(profile_data.get("summary_metadata"))
    ) or root_refs
    _ledger_values(refs, payload.get("summary", []), summary_refs)
    _ledger_values(refs, [payload.get("headline")], headline_refs)
    for section in ("skills", "experience", "projects", "education", "honors"):
        for item in _profile_collection(profile, section):
            item_refs = _metadata_refs(item) or root_refs
            _ledger_values(refs, _scalars(item), item_refs)
            for nested in _items(item.get("items")):
                nested_data = _dict(nested)
                if nested_data:
                    _ledger_values(refs, _scalars(nested_data), _metadata_refs(nested_data) or item_refs)
    for record in ranked:
        ref = provenance_ref(record)
        if ref:
            _ledger_values(refs, [str(_get(record, "safe_claim"))], [ref])



def build_resume_document(
    candidate_profile: Any,
    target_context: Any,
    evidence_records: Sequence[Any],
    mappings: Sequence[Any] = (),
    requirements: Sequence[Any] = (),
    *,
    mode: Any = "targeted_application",
    locale: str = "zh-CN",
    variant: Any = ResumeVariant.TECHNICAL_TWO_PAGE,
    target_pages: int = 2,
    minimum_pages: int = 1,
    template: str = "ats-simple",
) -> ResumeDocument:
    """Build a resume. Target context affects selection/order, never claim text."""
    mode_value = _mode(mode)
    variant_value = str(getattr(variant, "value", variant))
    ranked = rank_evidence(evidence_records, mappings=mappings, requirements=requirements, mode=mode_value)
    refs: list[str] = []
    assigned: set[str] = set()
    experience = _group_experience(candidate_profile, ranked, assigned, refs)
    projects = _group_projects(candidate_profile, ranked, assigned, refs)
    assigned.update(str(value) for value in _items(_get(candidate_profile, "metadata_evidence_ids", ())))
    unassigned = [record for record in ranked if str(_get(record, "evidence_id")) not in assigned]
    if unassigned:
        projects.append(
            {
                "name": resume_labels(locale)["selected_evidence"],
                "role": None,
                "context": None,
                "start_date": None,
                "end_date": None,
                "technologies": [],
                "bullets": [
                    _bullet(record, ranked.index(record), len(ranked))
                    for record in unassigned
                ],
            }
        )
    refs.extend(ref for record in ranked if (ref := provenance_ref(record)))
    target = _dict(target_context)
    headline = str(_get(candidate_profile, "headline", default="") or (target.get("role") if mode_value == "targeted_application" else "") or "").strip()
    if contains_placeholder(headline):
        headline = ""
    allowed_ids = {str(_get(record, "evidence_id")) for record in ranked}
    payload = {
        "schema_version": 1, "locale": locale,
        "variant": variant_value,
        "target": {"company": target.get("company"), "role": target.get("role"), "target_basis": str(getattr(target.get("target_basis"), "value", target.get("target_basis") or "insufficient-target"))},
        "contact": _contact(candidate_profile, mode_value), "headline": headline,
        "summary": [
            str(item).strip()
            for item in _items(_get(candidate_profile, "summary", default=[]))
            if str(item).strip() and not contains_placeholder(str(item))
        ],
        "skills": _skills(candidate_profile, allowed_ids, refs),
        "experience": experience, "projects": projects,
        "education": _provenanced_metadata(candidate_profile, "education", refs),
        "honors": _provenanced_metadata(candidate_profile, "honors", refs),
        "render_policy": {
            "target_pages": max(1, int(target_pages)),
            "minimum_pages": max(1, int(minimum_pages)),
            "template": template,
            "minimum_body_font_pt": (
                12.5
                if variant_value == ResumeVariant.EXTENDED_THREE_PAGE.value
                else 10.0
            ),
            "minimum_margin_mm": 12.0,
        },
        "provenance_refs": [],
    }
    payload["provenance_refs"] = list(dict.fromkeys(refs))
    visible_payload = {key: value for key, value in payload.items() if key != "provenance_refs"}
    if contains_placeholder(json.dumps(visible_payload, ensure_ascii=False, default=str)):
        raise ValueError("resume contains an unresolved placeholder")
    normalized = ResumeDocument.model_validate(payload).model_dump(mode="python")
    _add_fact_ledger(candidate_profile, target, normalized, ranked, refs)
    normalized["provenance_refs"] = list(dict.fromkeys(refs))
    return ResumeDocument.model_validate(normalized)


def _bullet_lines(container: Any) -> list[str]:
    return [str(_get(item, "text", default="")).strip() for item in _items(_get(container, "bullets", default=[])) if str(_get(item, "text", default="")).strip()]

def _format_date_range(start_date: Any, end_date: Any) -> str:
    start = str(start_date or "").strip()
    end = str(end_date or "").strip()
    if not start or not end:
        return start or end
    separator = " " if end.casefold() in _CURRENT_DATE_ENDINGS else " – "
    return f"{start}{separator}{end}"


def render_targeted_markdown(document: Any) -> str:
    data = _dict(document)
    contact = _dict(data.get("contact", {}))
    labels = resume_labels(data.get("locale"))
    lines: list[str] = []
    if contact.get("name"):
        lines.append(f"# {contact['name']}")
    if data.get("headline"):
        lines.append(f"**{data['headline']}**")
    contact_line = " | ".join(
        str(contact[key])
        for key in ("phone", "email", "location")
        if contact.get(key)
    )
    if contact_line:
        lines.extend((contact_line, ""))
    if data.get("summary"):
        lines.append(f"## {labels['summary']}")
        lines.extend(f"- {value}" for value in data["summary"])
        lines.append("")
    if data.get("skills"):
        lines.append(f"## {labels['skills']}")
        for group in data["skills"]:
            lines.append(
                f"- **{_get(group, 'group')}**: "
                f"{', '.join(map(str, _items(_get(group, 'items', default=[]))))}"
            )
        lines.append("")
    for section in ("experience", "projects"):
        if not data.get(section):
            continue
        lines.append(f"## {labels[section]}")
        for item in data[section]:
            name = _get(item, "organization", "name", default="")
            role = _get(item, "role", default="")
            lines.append(f"### {name}" + (f" — {role}" if role else ""))
            dates = _format_date_range(
                _get(item, "start_date", default=""),
                _get(item, "end_date", default=""),
            )
            location = _get(item, "location", default="")
            if dates or location:
                lines.append(
                    " | ".join(str(value) for value in (dates, location) if value)
                )
            context = _get(item, "context", default="")
            if context:
                lines.append(str(context))
            technologies = _items(_get(item, "technologies", default=[]))
            if technologies:
                lines.append(
                    f"{labels['technologies']} " + ", ".join(map(str, technologies))
                )
            lines.extend(f"- {text}" for text in _bullet_lines(item))
        lines.append("")
    for section in ("education", "honors"):
        if not data.get(section):
            continue
        lines.append(f"## {labels[section]}")
        for item in data[section]:
            value = _get(item, "institution", "name", default="")
            details = [
                _get(item, "degree", "issuer", default=""),
                _get(item, "field", default=""),
            ]
            dates = _format_date_range(
                _get(item, "start_date", "date", default=""),
                _get(item, "end_date", default=""),
            )
            lines.append(
                "- "
                + " — ".join(str(part) for part in (value, *details, dates) if part)
            )
            extra = _items(_get(item, "details", default=[]))
            if extra:
                lines.extend(f"  - {part}" for part in extra)
        lines.append("")
    links = _items(contact.get("links"))
    if links:
        lines.append(f"## {labels['links']}")
        lines.extend(
            f"- [{_get(link, 'label')}]({_get(link, 'url')})" for link in links
        )
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if contains_placeholder(text):
        raise ValueError("resume contains an unresolved placeholder")
    return text


def render_ats_text(document: Any) -> str:
    markdown = render_targeted_markdown(document)
    text = re.sub(r"^#{1,3}\s+", "", markdown, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1: \2", text)
    text = re.sub(r"^-\s+", "", text, flags=re.M)
    return text


def _cost(data: Mapping[str, Any]) -> int:
    strings = list(map(str, data.get("summary", [])))
    strings.extend(str(value) for group in data.get("skills", []) for value in _items(_get(group, "items", default=[])))
    strings.extend(text for section in ("experience", "projects") for item in data.get(section, []) for text in _bullet_lines(item))
    return sum(max(1, (len(value) + 79) // 80) for value in strings)


def compact_resume_document(document: Any, max_cost: int) -> ResumeDocument:
    """Apply the mandated semantic compaction order without rewriting claims."""
    if max_cost < 0: raise ValueError("max_cost must be non-negative")
    data = deepcopy(_dict(document))
    over = lambda: _cost(data) > max_cost
    removed_bullets = False
    # 1. Low-priority bullets/projects.
    bullets = []
    for section in ("projects", "experience"):
        for container_index, container in enumerate(data.get(section, [])):
            for bullet_index, bullet in enumerate(container.get("bullets", [])):
                bullets.append((float(_get(bullet, "priority", default=0.0)), section, container_index, bullet_index))
    for _, section, ci, bi in sorted(bullets):
        if not over(): break
        current = data[section][ci]["bullets"]
        if bi < len(current) and current[bi] is not None:
            current[bi] = None
            removed_bullets = True
    for section in ("projects", "experience"):
        for item in data.get(section, []): item["bullets"] = [bullet for bullet in item.get("bullets", []) if bullet is not None]
        data[section] = [item for item in data.get(section, []) if item.get("bullets")]
    if removed_bullets:
        visible_bullet_text = " ".join(
            text
            for section in ("experience", "projects")
            for item in data.get(section, [])
            for text in _bullet_lines(item)
        ).casefold()
        for group in data.get("skills", []):
            group["items"] = [
                value
                for value in group.get("items", [])
                if str(value).casefold() in visible_bullet_text
            ]
        data["skills"] = [
            group for group in data.get("skills", []) if group.get("items")
        ]
    # 2. Duplicate skills.
    if over():
        seen = set()
        for group in data.get("skills", []):
            group["items"] = [value for value in group.get("items", []) if not (str(value).casefold() in seen or seen.add(str(value).casefold()))]
    # 3. Early/weak experience.
    while over() and len(data.get("experience", [])) > 1: data["experience"].pop()
    # 4. Summary.
    while over() and data.get("summary"): data["summary"].pop()
    # 5. Repeated context.
    if over():
        seen_context = set()
        for section in ("experience", "projects"):
            for item in data.get(section, []):
                context = str(item.get("context") or "").casefold()
                if context in seen_context: item["context"] = None
                elif context: seen_context.add(context)
    # 6. Spacing is a renderer concern; enforce the immutable minimums here.
    policy = data.setdefault("render_policy", {})
    policy["minimum_body_font_pt"] = max(10.0, float(policy.get("minimum_body_font_pt", 10.0)))
    policy["minimum_margin_mm"] = max(12.0, float(policy.get("minimum_margin_mm", 12.0)))
    return ResumeDocument.model_validate(data)


def serialize_resume_document(document: Any) -> str:
    return json.dumps(_plain(document), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n"


compose_resume = build_resume_document
to_markdown = render_targeted_markdown
to_ats_text = render_ats_text
compact_resume = compact_resume_document
