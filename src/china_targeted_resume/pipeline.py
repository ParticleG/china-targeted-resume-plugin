"""Deterministic orchestration for targeted-resume runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .adapters.markdown_career_v1 import MarkdownCareerV1Adapter
from .application_advice import recommend_application
from .audit import audit_resume
from .role_analysis import build_role_competencies, parse_job_description
from .composition import (
    build_resume_document,
    compact_resume_document,
    evidence_rank_key,
    rank_evidence,
    provenance_ref,
    resume_context_is_substantive,
    resume_claim_is_substantive,
    resume_claim_priority,
    render_ats_text,
    render_targeted_markdown,
    resume_labels,
)
from .dossier import DOSSIER_FILES, refresh_role as refresh_role_sections, render_dossier_files
from .evidence import (
    KNOWN_SKILLS,
    build_evidence_map as build_evidence_mappings,
    bind_experience_duration_diagnostics,
    build_evidence_record,
    claim_supports_skill,
    refresh_match as refresh_evidence_match,
    text_mentions_skill,
)
from .gaps import build_gaps
from .io import create_run_directory, jsonable, read_json, secure_directory, validate_output_root, write_json, write_text
from .markdown_structure import SourceDocument, source_map_block_is_safe
from .models import (
    ApplicationConstraint, CompanyRef, JdInput, OutputMode, Requirement,
    ResumeVariant, RoleDossierIR, RoleMatchState, RoleRef, RoleRequest,
    RunRequest, SourceRef, TargetBasis, TargetContext,
)
from .provenance import build_confirmation_questions, build_provenance
from .roadmap_handoff import export_roadmap_handoff as make_roadmap_handoff
from .requirements import make_inferred_requirement
from .target_resolution import resolve_target
from .rendering.html import render_html
from .rendering.inspect import InspectionConfig, inspect_pdf as inspect_pdf_file
from .rendering.pdf import render_with_compaction

_MAX_JD_BYTES = 2 * 1024 * 1024
_CONVENTIONAL_SOURCE_CHILDREN = frozenset(
    {"company-research", "personal-data", "role-research", "growth-roadmap"}
)


def _career_source_root(source: str | Path) -> Path:
    candidate = Path(source).expanduser()
    if (
        candidate.name in _CONVENTIONAL_SOURCE_CHILDREN
        and candidate.is_dir()
        and not candidate.is_symlink()
    ):
        parent = candidate.parent
        if (
            (parent / "company-research").is_dir()
            and (parent / "personal-data").is_dir()
        ):
            return parent
    return candidate



class PipelineError(ValueError):
    """Expected, user-actionable pipeline error."""


class SelectionRequired(PipelineError):
    def __init__(self, message: str, choices: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.choices = list(choices)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    operation: str
    run_dir: Path | None = None
    artifacts: tuple[Path, ...] = ()
    summary: Mapping[str, Any] | None = None

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        del mode
        return {
            "operation": self.operation,
            "run_dir": str(self.run_dir) if self.run_dir else None,
            "artifacts": [str(path) for path in self.artifacts],
            "summary": jsonable(self.summary or {}),
        }


@dataclass(frozen=True, slots=True)
class ResumeVariantSpec:
    variant: ResumeVariant
    base_name: str
    target_pages: int
    work_bullets: int
    project_limit: int
    project_bullets: int
    max_cost: int


_RECRUITER_ONE_PAGE = ResumeVariantSpec(
    variant=ResumeVariant.RECRUITER_ONE_PAGE,
    base_name="resume-recruiter-1p",
    target_pages=1,
    work_bullets=2,
    project_limit=3,
    project_bullets=2,
    max_cost=20,
)
_TECHNICAL_TWO_PAGE = ResumeVariantSpec(
    variant=ResumeVariant.TECHNICAL_TWO_PAGE,
    base_name="resume-technical-2p",
    target_pages=2,
    work_bullets=5,
    project_limit=5,
    project_bullets=3,
    max_cost=24,
)
_EXTENDED_THREE_PAGE = ResumeVariantSpec(
    variant=ResumeVariant.EXTENDED_THREE_PAGE,
    base_name="technical-profile-3p",
    target_pages=3,
    work_bullets=8,
    project_limit=5,
    project_bullets=4,
    max_cost=36,
)


def _requested_variant_specs(
    request: RunRequest,
) -> tuple[ResumeVariantSpec, ...]:
    defaults = (_RECRUITER_ONE_PAGE, _TECHNICAL_TWO_PAGE)
    return (
        (*defaults, _EXTENDED_THREE_PAGE)
        if request.include_extended_profile
        else defaults
    )

def _template_for_variant(
    requested: str,
    variant: ResumeVariant,
) -> str:
    if requested == "adaptive":
        return (
            "ats-simple"
            if variant is ResumeVariant.RECRUITER_ONE_PAGE
            else "human-readable"
        )
    if requested in {"ats-simple", "human-readable"}:
        return requested
    raise PipelineError(
        "template must be adaptive, ats-simple, or human-readable"
    )


def _resume_discovery_requirements() -> list[Requirement]:
    texts = (
        (
            "resume-discovery-platform",
            "平台 架构 接口 自动化 交付 运维 工作区 容器 调度 推理 部署",
        ),
        (
            "resume-discovery-results",
            "性能 延迟 吞吐 缓存 检索 并发 测试 验证 结果 指标",
        ),
        (
            "resume-discovery-systems",
            "网络 协议 数据库 编译 日志 监控 前端 后端 大模型",
        ),
        (
            "resume-discovery-network-stage",
            "NETCONF CLI MPLS 协议 网络 测试 自动化",
        ),
        (
            "resume-discovery-ide-stage",
            "IDE WebSocket Hook 编辑器 上下文 通信 代码补全",
        ),
        (
            "resume-discovery-rag-stage",
            "RAG CTags tree-sitter 检索 索引 缓存 并发",
        ),
        (
            "resume-discovery-supply-chain",
            "离线 交付 镜像 制品 供应链 编译 部署 自动化 vendoring SHA-256",
        ),
        (
            "resume-discovery-supply-chain-state",
            "完整状态 镜像状态 多目标 恢复 离线 交付 镜像 制品",
        ),
        (
            "resume-discovery-supply-chain-cache",
            "vendoring 共享缓存 SHA-256 skipped 离线 编译 依赖 同步",
        ),
        (
            "resume-discovery-omni-context",
            (
                "企业研发环境 VS Code 闭源 Windows IDE 宿主 "
                "上下文采集 结果回写"
            ),
        ),
        (
            "resume-discovery-supply-chain-context",
            (
                "offline-tool-supply-chain FTP 文件挂载 中转介质 "
                "分角色部署 中间制品恢复"
            ),
        ),
    )
    return [
        make_inferred_requirement(
            text=text,
            inference_basis=(
                "Run-local semantic resume discovery; not a role requirement."
            ),
            inference_source="resume-variant-policy",
            confidence=0.1,
            requirement_id=requirement_id,
            category="resume-discovery",
        )
        for requirement_id, text in texts
    ]


def _bounded_file(path: Path) -> str:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_JD_BYTES:
        raise PipelineError("JD file must be a regular UTF-8 file no larger than 2 MiB")
    return resolved.read_text(encoding="utf-8")


def _bounded_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise PipelineError("JD URL must be an explicit public HTTPS URL without credentials")
    request = Request(url, headers={"User-Agent": "china-targeted-resume/1"})
    with urlopen(request, timeout=10) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > _MAX_JD_BYTES:
            raise PipelineError("JD URL response exceeds 2 MiB")
        body = response.read(_MAX_JD_BYTES + 1)
        if len(body) > _MAX_JD_BYTES:
            raise PipelineError("JD URL response exceeds 2 MiB")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset)


def _load_jd(jd: JdInput) -> tuple[str, str | None]:
    supplied = sum(value is not None for value in (jd.text, jd.file, jd.url))
    if supplied > 1:
        raise PipelineError("provide exactly one of JD text, file, or URL")
    if jd.text is not None:
        return jd.text, "inline-current-jd"
    if jd.file is not None:
        path = Path(jd.file).expanduser().resolve(strict=True)
        return _bounded_file(path), str(path)
    if jd.url is not None:
        url = str(jd.url)
        return _bounded_url(url), url
    return "", None


def _match_company(adapter: MarkdownCareerV1Adapter, value: str | CompanyRef | None) -> CompanyRef | None:
    if value is None or isinstance(value, CompanyRef):
        return value
    folded = value.casefold()
    matches = [item for item in adapter.list_companies() if folded in {item.company_id.casefold(), item.display_name.casefold()}]
    if len(matches) != 1:
        raise SelectionRequired("company selection is missing or ambiguous", adapter.list_companies())
    return matches[0]


def _match_role(adapter: MarkdownCareerV1Adapter, company: CompanyRef | None, value: str | RoleRef | None) -> RoleRef | None:
    if value is None or isinstance(value, RoleRef):
        return value
    choices = adapter.list_roles(company) if company else []
    folded = value.casefold()
    matches = [item for item in choices if folded in {item.role_id.casefold(), item.title.casefold()}]
    if len(matches) != 1:
        raise SelectionRequired("role selection is missing or ambiguous", choices)
    return matches[0]


def _source_refs(
    jd_text: str,
    jd_origin: str | None,
    official_url: str | None = None,
) -> list[SourceRef]:
    if not jd_text:
        return []
    digest = "sha256:" + sha256(jd_text.encode("utf-8")).hexdigest()
    source_url = official_url or (
        jd_origin if jd_origin and jd_origin.startswith("https://") else None
    )
    if source_url:
        return [SourceRef(url=source_url, title="Current job description", source_hash=digest, source_type="current-jd")]
    return [SourceRef(path=jd_origin or "inline-current-jd", title="Current job description", source_hash=digest, source_type="current-jd")]


def _role_sources(
    manifest: Any,
    company: CompanyRef | None,
    role: RoleRef | None,
    jd_text: str,
    jd_origin: str | None,
    official_url: str | None = None,
) -> list[SourceRef]:
    result = _source_refs(jd_text, jd_origin, official_url)
    hashes = {
        section.source_path: section.source_hash for section in manifest.sections
    }
    seen = {str(item.path or item.url) for item in result}
    for raw in [*(company.source_refs if company else []), *(role.source_refs if role else [])]:
        path = re.split(r"#|:L\d+", raw, maxsplit=1)[0]
        if not path or path in seen or path not in hashes:
            continue
        seen.add(path)
        result.append(SourceRef(
            path=path,
            title=path.rsplit("/", 1)[-1],
            source_hash=hashes[path],
            source_type="career-role-source",
        ))
    return result


def _with_jd_metadata(
    target: TargetContext,
    parsed_jd: Any | None,
    jd_origin: str | None,
) -> TargetContext:
    if parsed_jd is None:
        return target
    source_refs = list(target.source_refs)
    if parsed_jd.source_url:
        source_refs = [parsed_jd.source_url]
    elif jd_origin:
        source_refs = [jd_origin]
    return target.model_copy(
        update={
            "jd_source_date": parsed_jd.published_date,
            "jd_checked_at": parsed_jd.checked_at,
            "source_refs": source_refs,
        }
    )


def _persistable_dossier(dossier: RoleDossierIR) -> RoleDossierIR:
    """Keep refresh state without persisting retrieved source-section bodies."""
    return dossier.model_copy(update={"evidence_candidates": [], "evidence_records": []})


def _application_constraints(
    parsed: Sequence[ApplicationConstraint],
    requested: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> list[ApplicationConstraint]:
    if isinstance(requested, Mapping):
        raw = requested.get("constraints", ())
    else:
        raw = requested
    values = list(raw)
    if not values:
        return list(parsed)
    return [
        item
        if isinstance(item, ApplicationConstraint)
        else ApplicationConstraint.model_validate(item)
        for item in values
    ]


def _replace_owned_section(text: str, section: str, replacement: str) -> str:
    pattern = re.compile(
        rf"<!-- generated:{re.escape(section)}:start -->.*?"
        rf"<!-- generated:{re.escape(section)}:end -->",
        re.S,
    )
    if not pattern.search(text):
        raise PipelineError(f"role dossier lacks generated {section!r} ownership markers")
    return pattern.sub(lambda _: replacement, text, count=1)


def _load_verified_candidates(
    adapter: MarkdownCareerV1Adapter, candidates: Sequence[Any]
) -> list[Any]:
    """Load owning source sections, omitting candidates that cannot be verified."""
    verified: list[Any] = []
    for candidate in candidates:
        try:
            loaded = adapter.load_evidence(candidate)
        except (KeyError, RuntimeError, ValueError):
            continue
        verified.append(candidate.model_copy(update={
            "requirement_ids": loaded.requirement_ids,
            "proposed_claim": loaded.safe_claim,
            "fact_state": loaded.fact_state,
            "disclosure": loaded.disclosure,
            "match_state": loaded.match_state,
        }))
    return _deduplicate_candidates(verified)


def _deduplicate_candidates(candidates: Sequence[Any]) -> list[Any]:
    merged: dict[tuple[str, str, str, str], Any] = {}
    for candidate in candidates:
        key = (
            str(candidate.source.path or ""),
            str(candidate.source.section or ""),
            candidate.proposed_claim,
            str(candidate.match_state.value),
        )
        previous = merged.get(key)
        if previous is None:
            merged[key] = candidate
            continue
        requirement_ids = list(dict.fromkeys([
            *previous.requirement_ids, *candidate.requirement_ids
        ]))
        merged[key] = previous.model_copy(update={
            "requirement_ids": requirement_ids,
            "confidence": max(previous.confidence, candidate.confidence),
        })
    return list(merged.values())


def _experience_duration_fact_index(
    records: Sequence[Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        fact = getattr(record, "experience_duration_fact", None)
        if fact is None:
            continue
        source = record.source
        result.append(
            {
                "evidence_id": record.evidence_id,
                "requirement_ids": list(record.requirement_ids),
                "source": {
                    "path": source.path,
                    "section": source.section,
                    "source_hash": source.source_hash,
                },
                "source_span": (
                    record.source_span.model_dump(mode="json")
                    if record.source_span is not None
                    else None
                ),
                "experience_duration_fact": fact.model_dump(mode="json"),
            }
        )
    return result


def _mapped_evidence_ids(mappings: Sequence[Any]) -> set[str]:
    return {
        str(evidence_id)
        for mapping in mappings
        for evidence_id in (
            mapping.get("evidence_ids", [])
            if isinstance(mapping, Mapping)
            else getattr(mapping, "evidence_ids", [])
        )
    }


def _visible_rank_key(
    record: Any,
    mappings: Sequence[Any],
    requirements: Sequence[Any],
) -> tuple[Any, ...]:
    base = evidence_rank_key(
        record,
        mappings=mappings,
        requirements=requirements,
    )
    return (
        *base[:5],
        -int(resume_claim_priority(record) or 0),
        *base[5:],
    )


def _rank_visible_records(
    records: Sequence[Any],
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
    *,
    include_unmapped: bool = False,
) -> list[Any]:
    mapped_ids = _mapped_evidence_ids(mappings)
    ranked = rank_evidence(
        [
            record
            for record in records
            if (include_unmapped or record.evidence_id in mapped_ids)
            and (
                str(getattr(mode, "value", mode)) != OutputMode.TARGETED_APPLICATION.value
                or record.match_state
                in {
                    RoleMatchState.DIRECT_EVIDENCE,
                    RoleMatchState.TRANSFERABLE_EXPERIENCE,
                }
            )
            and resume_claim_is_substantive(record)
        ],
        mappings=mappings,
        requirements=requirements,
        mode=mode,
    )
    ranked.sort(
        key=lambda record: _visible_rank_key(record, mappings, requirements)
    )
    return ranked


def _record_dimensions(record: Any) -> set[str]:
    section = str(record.source.section or "").casefold()
    claim = str(record.safe_claim)
    dimensions = {"technical"}
    if any(
        marker in section
        for marker in (
            "result",
            "metric",
            "outcome",
            "结果",
            "指标",
            "量化",
        )
    ) or re.search(
        r"\d|数十|数百|提升|降低|减少|完成交付|吞吐|延迟|耗时|版本化",
        claim,
        re.I,
    ):
        dimensions.add("result")
    if any(
        marker in section
        for marker in ("verification", "validation", "工程化与验证")
    ) or re.search(
        r"\b(?:test|pytest|mock|dry-run|validated?|verified?)\b|"
        r"(?:测试|验证|复核|对账|连续失败|终态)",
        claim,
        re.I,
    ):
        dimensions.add("verification")
    if re.search(
        r"\b(?:led|owned|coordinated|responsible)\b|"
        r"(?:带领|负责|协调|主导|个人完成|独立完成)",
        claim,
        re.I,
    ):
        dimensions.add("ownership")
    return dimensions


def _select_diverse_records(
    ranked: Sequence[Any],
    limit: int,
    dimensions: Sequence[str],
) -> list[Any]:
    selected: list[Any] = []
    selected_ids: set[str] = set()
    for dimension in dimensions:
        record = next(
            (
                candidate
                for candidate in ranked
                if candidate.evidence_id not in selected_ids
                and dimension in _record_dimensions(candidate)
            ),
            None,
        )
        if record is None:
            continue
        selected.append(record)
        selected_ids.add(record.evidence_id)
        if len(selected) >= limit:
            return selected
    for record in ranked:
        if record.evidence_id in selected_ids:
            continue
        selected.append(record)
        selected_ids.add(record.evidence_id)
        if len(selected) >= limit:
            break
    return selected


def _work_stage_ranges(
    adapter: MarkdownCareerV1Adapter,
    source_path: str,
) -> list[tuple[int, int]]:
    document = _seed_document(adapter, source_path)
    if document is None:
        return []
    return [
        (section.location.start_line, section.location.end_line + 1)
        for section in document.sections
        if section.level == 3
        and re.match(r"^(?:阶段|stage\b)", section.heading, re.I)
        and not section.flags.excluded_from_evidence
    ]


def _select_work_records(
    adapter: MarkdownCareerV1Adapter,
    source_path: str,
    ranked: Sequence[Any],
    limit: int,
    *,
    preserve_stages: bool,
) -> list[Any]:
    selected: list[Any] = []
    selected_ids: set[str] = set()
    if preserve_stages:
        for start_line, end_line in reversed(
            _work_stage_ranges(adapter, source_path)
        ):
            record = next(
                (
                    candidate
                    for candidate in ranked
                    if candidate.source_span is not None
                    and start_line
                    <= candidate.source_span.start_line
                    < end_line
                    and candidate.evidence_id not in selected_ids
                ),
                None,
            )
            if record is None:
                continue
            selected.append(record)
            selected_ids.add(record.evidence_id)
            if len(selected) >= limit:
                return selected
    remaining = [
        record for record in ranked if record.evidence_id not in selected_ids
    ]
    for record in _select_diverse_records(
        remaining,
        limit - len(selected),
        ("result", "ownership", "verification", "technical"),
    ):
        selected.append(record)
        selected_ids.add(record.evidence_id)
    return selected


def _project_source_priority(path: str) -> int:
    normalized = f"/{path.casefold().strip('/')}/"
    if "/company-projects/" in normalized:
        return 0
    if "/personal-projects/" in normalized:
        return 1
    if "/community-projects/" in normalized:
        return 2
    if "/projects/" in normalized:
        return 3
    return 4


def _select_variant_records(
    adapter: MarkdownCareerV1Adapter,
    records: Sequence[Any],
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
    spec: ResumeVariantSpec,
) -> list[Any]:
    ranked = _rank_visible_records(
        records,
        mappings,
        requirements,
        mode,
        include_unmapped=(
            not bool(mappings)
            or str(getattr(mode, "value", mode))
            != OutputMode.TARGETED_APPLICATION.value
        ),
    )
    by_path: dict[str, list[Any]] = {}
    for record in ranked:
        by_path.setdefault(str(record.source.path or ""), []).append(record)

    work_paths = sorted(
        (path for path in by_path if "/work/" in f"/{path}/"),
        key=lambda path: _visible_rank_key(
            by_path[path][0], mappings, requirements
        ),
    )
    selected: list[Any] = []
    remaining_work_slots = spec.work_bullets
    for path in work_paths:
        if remaining_work_slots <= 0:
            break
        chosen = _select_work_records(
            adapter,
            path,
            by_path[path],
            remaining_work_slots,
            preserve_stages=spec.variant
            is not ResumeVariant.RECRUITER_ONE_PAGE,
        )
        selected.extend(chosen)
        remaining_work_slots -= len(chosen)

    project_paths = [
        path
        for path in by_path
        if any(
            marker in f"/{path}/"
            for marker in (
                "/company-projects/",
                "/personal-projects/",
                "/community-projects/",
                "/projects/",
            )
        )
    ]
    company_project_paths = [
        path for path in project_paths
        if "/company-projects/" in f"/{path}/"
    ]
    if company_project_paths:
        project_paths = company_project_paths
    project_paths.sort(
        key=lambda path: (
            _project_source_priority(path),
            _visible_rank_key(by_path[path][0], mappings, requirements),
            path,
        )
    )
    for path in project_paths[: spec.project_limit]:
        selected.extend(
            _select_diverse_records(
                by_path[path],
                spec.project_bullets,
                ("technical", "result", "verification", "ownership"),
            )
        )

    deduplicated: dict[str, tuple[tuple[Any, ...], Any]] = {}
    for record in selected:
        claim_key = re.sub(
            r"\s+", " ", str(record.safe_claim)
        ).strip().casefold()
        key = claim_key or str(record.evidence_id)
        rank = _visible_rank_key(record, mappings, requirements)
        previous = deduplicated.get(key)
        if previous is None or rank < previous[0]:
            deduplicated[key] = (rank, record)
    return [record for _, record in deduplicated.values()]


def _select_resume_records(
    records: Sequence[Any],
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
    *,
    total_limit: int = 8,
    per_source_limit: int = 2,
) -> list[Any]:
    selected: list[Any] = []
    counts: dict[str, int] = {}
    for record in _rank_visible_records(
        records,
        mappings,
        requirements,
        mode,
    ):
        path = str(record.source.path or record.evidence_id)
        if counts.get(path, 0) >= per_source_limit:
            continue
        selected.append(record)
        counts[path] = counts.get(path, 0) + 1
        if len(selected) >= total_limit:
            break
    return selected


def _seed_document(
    adapter: MarkdownCareerV1Adapter, relative: str
) -> SourceDocument | None:
    if relative not in set(adapter.manifest.documents):
        return None
    try:
        return adapter.source_document(relative)
    except (KeyError, ValueError):
        return None


def _seed_text(adapter: MarkdownCareerV1Adapter, relative: str) -> str:
    document = _seed_document(adapter, relative)
    return document.text if document is not None else ""


def _normalized_field_key(value: str) -> str:
    return re.sub(r"[\s_:/：()（）-]+", "", value.casefold())


def _plain_markdown_value(value: str) -> str:
    text = re.sub(r"!?\[([^]]+)\]\([^)]+\)", r"\1", value)
    text = re.sub(r"(?<!\*)\*\*([^*\n]+)\*\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)__([^_\n]+)__(?!_)", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _profile_fields(
    adapter: MarkdownCareerV1Adapter,
    relative: str,
) -> dict[str, str]:
    document = _seed_document(adapter, relative)
    if document is None:
        return {}
    fields: dict[str, str] = {}
    for block in document.blocks:
        if (
            block.kind not in {"list_item", "paragraph"}
            or not adapter.structural_block_is_safe(block)
        ):
            continue
        labeled = re.match(
            r"^(.{1,80}?)\s*[:：]\s*(.+?)\s*$",
            _plain_markdown_value(block.plain_text),
        )
        if labeled:
            fields[_normalized_field_key(labeled.group(1))] = labeled.group(2)
    for table in adapter.parse_pipe_tables(relative):
        for row in table["rows"][1:]:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                fields[_normalized_field_key(_plain_markdown_value(row[0]))] = (
                    row[1].strip()
                )
    return fields


def _field(fields: Mapping[str, str], *aliases: str) -> str:
    return next(
        (
            fields[_normalized_field_key(alias)]
            for alias in aliases
            if _normalized_field_key(alias) in fields
        ),
        "",
    )


def _contact_value(raw: str, kind: str) -> str | None:
    value = _plain_markdown_value(raw)
    if not value:
        return None
    if kind == "email":
        match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
        return match.group(0) if match else None
    if kind == "phone":
        match = re.search(r"\+?\d(?:[\d ()-]{6,}\d)", value)
        return re.sub(r"[ ()-]", "", match.group(0)) if match else None
    if kind == "location" and re.search(
        r"(?:待确认|未确认|unknown|unverified)",
        value,
        re.I,
    ):
        return None
    return value


def _public_profile_links(
    adapter: MarkdownCareerV1Adapter,
    relative: str,
) -> list[dict[str, Any]]:
    document = _seed_document(adapter, relative)
    if document is None:
        return []
    links: list[dict[str, Any]] = []
    for block in document.blocks:
        if (
            block.kind not in {"list_item", "paragraph"}
            or not adapter.structural_block_is_safe(block)
        ):
            continue
        active = re.search(
            r"(?:^|[-*+]\s+)Active,\s*P0:\s*"
            r"\[([^]]+)\]\((https://[^)]+)\)",
            block.text,
            re.I,
        )
        if active:
            links.append(
                {
                    "label": active.group(1),
                    "url": active.group(2),
                    "source_refs": [relative],
                }
            )
    for table in adapter.parse_pipe_tables(relative):
        for row in table["rows"][1:]:
            if not row:
                continue
            label = _plain_markdown_value(row[0])
            if not re.search(
                r"(?:个人\s*GitHub\s*主页|personal\s+(?:github|profile|site))",
                label,
                re.I,
            ):
                continue
            status = " ".join(row[2:]).casefold()
            if re.search(r"(?:不可访问|broken|unreachable|retired)", status, re.I):
                continue
            if not re.search(
                r"(?:\bactive\b|\breachable\b|HTTP\s*2\d\d|可访问)",
                status,
                re.I,
            ):
                continue
            url_match = next(
                (
                    re.search(r"\]\((https://[^)]+)\)", cell)
                    for cell in row
                    if re.search(r"\]\((https://[^)]+)\)", cell)
                ),
                None,
            )
            if url_match is not None:
                links.append(
                    {
                        "label": label,
                        "url": url_match.group(1),
                        "source_refs": [relative],
                    }
                )
    deduplicated: dict[str, dict[str, Any]] = {}
    for link in links:
        deduplicated.setdefault(str(link["url"]), link)
    return list(deduplicated.values())


def _split_period(value: str) -> tuple[str, str]:
    period = _plain_markdown_value(value)
    if re.search(r"\s+to\s+", period, re.I):
        start, end = re.split(r"\s+to\s+", period, maxsplit=1, flags=re.I)
        return start.strip(), end.strip()
    for delimiter in ("－", "–", "—"):
        if delimiter in period:
            start, end = period.split(delimiter, 1)
            return start.strip(), end.strip()
    return period.removesuffix(" 起").strip(), ""


def _timeline_rows(
    adapter: MarkdownCareerV1Adapter,
    relative: str,
) -> list[dict[str, str]]:
    if relative not in set(adapter.manifest.documents):
        return []
    collected: list[dict[str, str]] = []
    for table in adapter.parse_pipe_tables(relative):
        rows = table["rows"]
        if len(rows) < 2:
            continue
        headers = [_normalized_field_key(header) for header in rows[0]]

        def column(*names: str) -> int | None:
            normalized = {_normalized_field_key(name) for name in names}
            return next(
                (index for index, header in enumerate(headers) if header in normalized),
                None,
            )

        period_index = column("period", "date", "dates", "时间")
        organization_index = column("organization", "company", "组织/项目", "组织项目")
        role_index = column("role", "title", "角色或阶段")
        source_index = column("类型与来源", "类型来源", "type/source")
        fact_index = column("fact", "fact state", "status")
        disclosure_index = column("disclosure", "publicity")
        if period_index is None or organization_index is None or role_index is None:
            continue
        for row in rows[1:]:
            required_index = max(period_index, organization_index, role_index)
            if len(row) <= required_index:
                continue
            if source_index is not None and source_index < len(row):
                source_type = _normalized_field_key(
                    _plain_markdown_value(row[source_index])
                )
                if source_type not in {
                    "公司任职经历",
                    "公司经历",
                    "任职经历",
                    "companyemployment",
                    "employment",
                    "workexperience",
                }:
                    continue
            if fact_index is not None and (
                fact_index >= len(row) or row[fact_index].strip() not in {"F1", "F2"}
            ):
                continue
            if disclosure_index is not None and (
                disclosure_index >= len(row) or row[disclosure_index].strip() == "P3"
            ):
                continue
            start_date, end_date = _split_period(row[period_index])
            collected.append(
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "organization": _plain_markdown_value(row[organization_index]),
                    "role": _plain_markdown_value(row[role_index]),
                }
            )
    consolidated: dict[str, dict[str, str]] = {}
    for row in collected:
        key = row["organization"].casefold()
        previous = consolidated.get(key)
        if previous is None:
            consolidated[key] = row
        else:
            previous["end_date"] = row["end_date"]
            previous["role"] = row["role"]
    return list(consolidated.values())


def _education_and_honors(
    adapter: MarkdownCareerV1Adapter,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    available = set(adapter.manifest.documents)
    relative = next(
        (
            candidate
            for candidate in (
                "personal-data/profile/education-and-honors.md",
                "personal-data/community/education-and-honors.md",
            )
            if candidate in available
        ),
        "",
    )
    if not relative:
        return [], []
    document = _seed_document(adapter, relative)
    if document is None:
        return [], []
    eligible_blocks = [
        block
        for block in document.blocks
        if block.kind in {"list_item", "paragraph"}
        and adapter.structural_block_is_safe(block)
    ]
    education: list[dict[str, Any]] = []
    legacy = next(
        (
            match
            for block in eligible_blocks
            if (
                match := re.match(
                    r"^\s*[-*+]?\s*([^,]+),\s*([^,]+),\s*"
                    r"(\d{4}-\d{2})\s+to\s+(\d{4}-\d{2});\s*"
                    r"F[12],\s*P[012]\.",
                    block.text,
                )
            )
        ),
        None,
    )
    if legacy:
        degree_field, institution, start_date, end_date = legacy.groups()
        degree_parts = re.split(r"\s+in\s+", degree_field, maxsplit=1)
        education.append(
            {
                "institution": institution,
                "degree": degree_parts[0],
                "field": degree_parts[1] if len(degree_parts) > 1 else None,
                "start_date": start_date,
                "end_date": end_date,
                "source_refs": [relative],
            }
        )
    if not education:
        table_fields: dict[str, str] = {}
        for table in adapter.parse_pipe_tables(relative):
            for row in table["rows"][1:]:
                if len(row) >= 2:
                    table_fields[_normalized_field_key(row[0])] = _plain_markdown_value(row[1])
        institution = _field(table_fields, "学校", "institution", "school")
        if institution:
            start_date, end_date = _split_period(_field(table_fields, "时间", "period"))
            education.append(
                {
                    "institution": institution,
                    "degree": _field(table_fields, "学历层次", "degree") or None,
                    "field": _field(table_fields, "专业", "field") or None,
                    "start_date": start_date,
                    "end_date": end_date,
                    "source_refs": [relative],
                }
            )
    honors: list[dict[str, Any]] = []
    for block in eligible_blocks:
        match = re.match(
            r"^\s*[-*+]?\s*([^;]+),\s*(\d{4});\s*F[12],\s*P[012]\.",
            block.text,
        )
        if match:
            honors.append(
                {
                    "name": match.group(1).strip(),
                    "date": match.group(2),
                    "source_refs": [relative],
                }
            )
        if len(honors) >= 2:
            break
    if not honors:
        for section in document.sections:
            match = re.match(r"^(.+?)\s*[（(](\d{4})[)）]\s*$", section.heading)
            if match and not section.flags.excluded_from_evidence:
                honors.append(
                    {
                        "name": match.group(1).strip(),
                        "date": match.group(2),
                        "source_refs": [relative],
                    }
                )
            if len(honors) >= 2:
                break
    return education, honors


def _work_stage_metadata(
    adapter: MarkdownCareerV1Adapter,
    source_path: str,
) -> list[dict[str, Any]]:
    document = _seed_document(adapter, source_path)
    if document is None:
        return []
    stages: list[dict[str, Any]] = []
    for section in document.sections:
        if (
            section.level != 3
            or not re.match(r"^(?:阶段|stage\b)", section.heading, re.I)
            or section.flags.excluded_from_evidence
        ):
            continue
        chunk = document.exact_text(section.location)
        period_match = re.search(r"^\s*\*\*([^*\n]+)\*\*", chunk, re.M)
        start_date, end_date = (
            _split_period(period_match.group(1))
            if period_match is not None
            else ("", "")
        )
        role = re.split(
            r"[:：]", _plain_markdown_value(section.heading), maxsplit=1
        )[-1].strip()
        stages.append(
            {
                "start_line": section.location.start_line,
                "end_line": section.location.end_line + 1,
                "role": role,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return stages


def _context_record(
    records: Sequence[Any],
    source_path: str,
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
) -> Any | None:
    candidates = [
        record
        for record in records
        if str(record.source.path or "") == source_path
        and resume_context_is_substantive(record)
        and (
            start_line is None
            or (
                record.source_span is not None
                and start_line
                <= record.source_span.start_line
                < (end_line or start_line + 1)
            )
        )
    ]
    ranked = rank_evidence(
        candidates,
        mappings=mappings,
        requirements=requirements,
        mode=mode,
    )
    ranked.sort(
        key=lambda record: evidence_rank_key(
            record,
            mappings=mappings,
            requirements=requirements,
        )
    )
    return ranked[0] if ranked else None


def _work_stage_profiles(
    adapter: MarkdownCareerV1Adapter,
    source_path: str,
    organization: str,
    selected_records: Sequence[Any],
    all_records: Sequence[Any],
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for stage in reversed(_work_stage_metadata(adapter, source_path)):
        linked = [
            record
            for record in selected_records
            if record.source_span is not None
            and stage["start_line"]
            <= record.source_span.start_line
            < stage["end_line"]
        ]
        if not linked:
            continue
        context_record = _context_record(
            all_records,
            source_path,
            mappings,
            requirements,
            mode,
            start_line=stage["start_line"],
            end_line=stage["end_line"],
        )
        refs = [source_path]
        if context_record is not None:
            ref = provenance_ref(context_record)
            if ref:
                refs.append(ref)
        entries.append(
            {
                "organization": organization,
                "role": stage["role"],
                "start_date": stage["start_date"],
                "end_date": stage["end_date"],
                "context": (
                    context_record.safe_claim
                    if context_record is not None
                    else None
                ),
                "evidence_ids": [
                    record.evidence_id for record in linked
                ],
                "source_refs": refs,
            }
        )
    return entries


def _candidate_profile(
    adapter: MarkdownCareerV1Adapter,
    records: Sequence[Any],
    all_records: Sequence[Any],
    mappings: Sequence[Any],
    requirements: Sequence[Any],
    mode: Any,
    spec: ResumeVariantSpec,
) -> dict[str, Any]:
    basic_ref = "personal-data/profile/basic-information.md"
    fields = _profile_fields(adapter, basic_ref)
    contact: dict[str, Any] = {
        "name": _contact_value(_field(fields, "name", "姓名"), "name") or "",
        "email": _contact_value(_field(fields, "email", "邮箱"), "email"),
        "phone": _contact_value(_field(fields, "phone", "手机", "电话"), "phone"),
        "location": _contact_value(
            _field(fields, "location", "所在地", "当前所在地", "所在地历史记录"),
            "location",
        ),
        "source_refs": [basic_ref],
    }
    if str(getattr(mode, "value", mode)) == "public_portfolio":
        contact.pop("phone", None)
    links_ref = "personal-data/meta/public-links.md"
    contact["links"] = _public_profile_links(adapter, links_ref)
    timeline_rows = _timeline_rows(
        adapter,
        "personal-data/profile/career-timeline.md",
    )
    by_path: dict[str, list[Any]] = {}
    for record in records:
        by_path.setdefault(str(record.source.path or ""), []).append(record)
    experience: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    project_directories = (
        "/projects/",
        "/company-projects/",
        "/personal-projects/",
        "/community-projects/",
    )
    for path, linked in by_path.items():
        ids = [record.evidence_id for record in linked]
        refs = [path]
        title = str(linked[0].source.title or Path(path).stem.replace("-", " ").title())
        if "/work/" in path:
            work_fields = _profile_fields(adapter, path)
            organization = _plain_markdown_value(
                _field(work_fields, "公司", "organization", "company")
            )
            role = _plain_markdown_value(
                _field(work_fields, "当前岗位", "role", "title")
            )
            period = _field(work_fields, "任职时间", "period")
            start_date, end_date = _split_period(period) if period else ("", "")
            tokens = set(re.findall(r"[a-z0-9]+", f"{path} {title}".casefold()))
            timeline = next(
                (
                    row
                    for row in timeline_rows
                    if (
                        organization
                        and row["organization"].casefold() == organization.casefold()
                    )
                    or tokens
                    & set(re.findall(r"[a-z0-9]+", row["organization"].casefold()))
                ),
                timeline_rows[0] if len(timeline_rows) == 1 else {},
            )
            resolved_organization = (
                organization or timeline.get("organization", title)
            )
            if spec.variant is ResumeVariant.RECRUITER_ONE_PAGE:
                experience.append(
                    {
                        "organization": resolved_organization,
                        "role": role or timeline.get("role", ""),
                        "start_date": (
                            start_date or timeline.get("start_date", "")
                        ),
                        "end_date": end_date or timeline.get("end_date", ""),
                        "context": _plain_markdown_value(
                            _field(
                                work_fields,
                                "职业演进",
                                "career progression",
                            )
                        )
                        or None,
                        "evidence_ids": ids,
                        "source_refs": refs,
                    }
                )
            else:
                stages = _work_stage_profiles(
                    adapter,
                    path,
                    resolved_organization,
                    linked,
                    all_records,
                    mappings,
                    requirements,
                    mode,
                )
                if stages:
                    experience.extend(stages)
                else:
                    experience.append(
                        {
                            "organization": resolved_organization,
                            "role": role or timeline.get("role", ""),
                            "start_date": (
                                start_date or timeline.get("start_date", "")
                            ),
                            "end_date": (
                                end_date or timeline.get("end_date", "")
                            ),
                            "evidence_ids": ids,
                            "source_refs": refs,
                        }
                    )
        elif any(directory in path for directory in project_directories):
            context_record = (
                _context_record(
                    all_records,
                    path,
                    mappings,
                    requirements,
                    mode,
                )
                if spec.variant is not ResumeVariant.RECRUITER_ONE_PAGE
                else None
            )
            if context_record is not None:
                ref = provenance_ref(context_record)
                if ref:
                    refs.append(ref)
            projects.append(
                {
                    "name": title,
                    "context": (
                        context_record.safe_claim
                        if context_record is not None
                        else None
                    ),
                    "evidence_ids": ids,
                    "source_refs": refs,
                }
            )
    requirement_by_id = {
        item.requirement_id: item for item in requirements
    }
    skill_index: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        if not mapping.evidence_ids:
            continue
        requirement = requirement_by_id.get(mapping.requirement_id)
        if requirement is None:
            continue
        linked_records = [
            record for record in records
            if record.evidence_id in mapping.evidence_ids
        ]
        requirement_text = requirement.text
        candidates = [
            *requirement.keywords,
            *(skill for skill in KNOWN_SKILLS if text_mentions_skill(requirement_text, skill)),
        ]
        for candidate in candidates:
            skill = str(candidate).strip()
            supporting_records = [
                record
                for record in linked_records
                if skill
                and claim_supports_skill(
                    record.safe_claim,
                    skill,
                    section=str(record.source.section or ""),
                )
            ]
            if not supporting_records:
                continue
            key = skill.casefold()
            entry = skill_index.setdefault(key, {
                "text": skill,
                "evidence_ids": [],
                "source_refs": [],
            })
            entry["evidence_ids"].extend(
                record.evidence_id for record in supporting_records
            )
            entry["source_refs"].extend(
                str(record.source.path)
                for record in supporting_records
                if record.source.path
            )
    for record in records:
        claim = record.safe_claim.casefold()
        for skill in KNOWN_SKILLS:
            if not claim_supports_skill(
                record.safe_claim,
                skill,
                section=str(record.source.section or ""),
            ):
                continue
            key = skill.casefold()
            entry = skill_index.setdefault(
                key,
                {
                    "text": skill,
                    "evidence_ids": [],
                    "source_refs": [],
                },
            )
            entry["evidence_ids"].append(record.evidence_id)
            if record.source.path:
                entry["source_refs"].append(str(record.source.path))
    skill_items = []
    for entry in skill_index.values():
        entry["evidence_ids"] = list(dict.fromkeys(entry["evidence_ids"]))
        entry["source_refs"] = list(dict.fromkeys(entry["source_refs"]))
        skill_items.append(entry)
    education, honors = _education_and_honors(adapter)
    return {
        "contact": contact,
        "headline": _plain_markdown_value(
            _field(fields, "preferred_title", "preferred title", "求职方向")
        ),
        "headline_metadata": {"source_refs": [basic_ref]},
        "experience": experience,
        "projects": projects,
        "skills": [{
            "group": "Relevant Capabilities",
            "items": skill_items[: {
                ResumeVariant.RECRUITER_ONE_PAGE: 8,
                ResumeVariant.TECHNICAL_TWO_PAGE: 12,
                ResumeVariant.EXTENDED_THREE_PAGE: 16,
            }[spec.variant]],
            "source_refs": list(dict.fromkeys(
                ref for item in skill_items for ref in item["source_refs"]
            )),
        }] if skill_items else [],
        "education": education,
        "honors": honors,
    }




_ROLE_EVIDENCE_HEADING_RE = re.compile(
    r"\b(?:requirements?|qualifications?|responsibilit(?:y|ies)|preferred|"
    r"preserved excerpt|archived excerpt)\b|"
    r"(?:任职要求|任职资格|岗位职责|工作职责|要求摘录|保留摘录|摘录)",
    re.I,
)
_ROLE_TITLE_SUFFIXES = (
    "软件开发工程师",
    "软件工程师",
    "开发工程师",
    "算法工程师",
    "平台工程师",
    "工程师",
    "developer",
    "engineer",
)


def _normalize_role_label(value: str) -> str:
    linked = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    without_requisition = re.sub(
        r"[（(]\s*[A-Za-z]\d+\s*[)）]",
        "",
        linked,
    )
    return re.sub(
        r"[^a-z0-9+#\u4e00-\u9fff]+",
        "",
        without_requisition.casefold(),
    )


def _role_label_variants(title: str) -> set[str]:
    without_requisition = re.sub(
        r"[（(]\s*[A-Za-z]\d+\s*[)）]",
        "",
        title,
    ).strip()
    variants = {_normalize_role_label(without_requisition)}
    folded = without_requisition.casefold()
    for suffix in _ROLE_TITLE_SUFFIXES:
        if folded.endswith(suffix.casefold()):
            variants.add(_normalize_role_label(
                without_requisition[: -len(suffix)].strip()
            ))
    return {item for item in variants if item}


def _role_evidence_subsections(
    adapter: MarkdownCareerV1Adapter,
    document: SourceDocument,
    parent_identity: str,
) -> list[str]:
    selected: list[str] = []
    for section in document.sections:
        if not _ROLE_EVIDENCE_HEADING_RE.search(section.heading) or not any(
            ancestor.identity == parent_identity for ancestor in section.ancestors
        ):
            continue
        text = "\n".join(
            block.text.strip()
            for block in document.blocks
            if block.section_identity == section.identity
            and adapter.structural_block_is_safe(block)
        ).strip()
        if text:
            selected.append(text)
    return list(dict.fromkeys(selected))


def _role_hiring_scopes(
    adapter: MarkdownCareerV1Adapter,
    document: SourceDocument,
    role: RoleRef,
) -> list[str]:
    role_title = _normalize_role_label(role.title)
    exact_sections: list[str] = []
    for section in document.sections:
        if role_title not in _normalize_role_label(section.heading):
            continue
        nested = _role_evidence_subsections(
            adapter,
            document,
            section.identity,
        )
        direct = "\n".join(
            block.text.strip()
            for block in document.blocks
            if block.section_identity == section.identity
            and adapter.structural_block_is_safe(block)
        ).strip()
        exact_sections.extend(nested or ([direct] if direct else []))
    if exact_sections:
        return list(dict.fromkeys(item for item in exact_sections if item))

    variants = _role_label_variants(role.title)
    scoped: list[str] = []
    for block in document.blocks:
        if not adapter.structural_block_is_safe(block):
            continue
        if block.kind in {"list_item", "paragraph"}:
            labeled = re.match(
                r"^(.{1,80}?)[：:]\s*(.+?)\s*$",
                block.plain_text,
            )
            if labeled and any(
                variant in _normalize_role_label(labeled.group(1))
                for variant in variants
            ):
                scoped.append(block.text.strip())
        elif block.kind == "table" and any(
            variant in _normalize_role_label(" ".join(block.cells))
            for variant in variants
        ):
            scoped.append("- " + " — ".join(block.cells))
    return list(dict.fromkeys(scoped))


def _atomic_role_requirement_texts(text: str, role: RoleRef) -> list[str]:
    labeled = re.match(r"^(.{1,80}?)[：:]\s*(.+?)\s*$", text)
    if (
        not labeled
        or _normalize_role_label(labeled.group(1))
        not in _role_label_variants(role.title)
    ):
        return [text]
    body = re.sub(r"\s*\[[^\]]+\]\s*$", "", labeled.group(2)).strip()
    atoms: list[str] = []
    for clause in re.split(r"\s*[;；]\s*", body):
        clause = clause.strip().rstrip("。.")
        if not clause:
            continue
        modality = ""
        modality_match = re.search(r"\s*(优先|preferred)\s*$", clause, re.I)
        if modality_match:
            modality = modality_match.group(1)
            clause = clause[:modality_match.start()].strip()
        prefix = ""
        prefix_match = re.match(r"^(熟悉|精通|掌握|了解)\s*", clause)
        if prefix_match:
            prefix = prefix_match.group(1)
            clause = clause[prefix_match.end():]
        values = re.split(r"\s*(?:、|，|,|\band\b)\s*", clause, flags=re.I)
        for value in values:
            value = value.strip()
            if not value:
                continue
            atom = f"{prefix}{value}" if prefix else value
            if modality:
                atom = (
                    f"{atom}优先"
                    if modality == "优先"
                    else f"{atom} preferred"
                )
            atoms.append(atom)
    return list(dict.fromkeys(atoms)) or [text]




def _safe_structural_scope(
    adapter: MarkdownCareerV1Adapter,
    document: SourceDocument,
) -> str:
    """Rebuild deterministic parser input from safe structural leaves only."""

    events: list[tuple[int, int, str]] = []
    for section in document.sections:
        if (
            section.heading_ancestor_nodes
            and not section.flags.excluded_from_evidence
        ):
            heading_location = section.heading_ancestor_nodes[-1].location
            events.append(
                (
                    heading_location.start_byte,
                    0,
                    document.exact_text(heading_location).strip(),
                )
            )
    for block in document.blocks:
        if adapter.structural_block_is_safe(block):
            events.append(
                (
                    block.location.start_byte,
                    1,
                    document.exact_text(block.location).strip(),
                )
            )
    return "\n\n".join(
        text
        for _, _, text in sorted(events)
        if text
    )


def _tier_b_requirements(
    adapter: MarkdownCareerV1Adapter,
    company: CompanyRef | None,
    role: RoleRef | None,
) -> list[Requirement]:
    sources: dict[str, SourceDocument] = {}
    if role is not None:
        for ref in role.source_refs:
            path = re.split(r"#|:L\d+", ref, maxsplit=1)[0]
            if path.endswith("roles-and-hiring.md"):
                document = _seed_document(adapter, path)
                if document is not None:
                    sources.setdefault(path, document)
            role_dir = Path(path).parent
            jd_path = (role_dir / "job-description.md").as_posix()
            document = _seed_document(adapter, jd_path)
            if document is not None:
                sources.setdefault(jd_path, document)
    if company is not None:
        for path in adapter.load_company(company):
            if path.endswith("roles-and-hiring.md"):
                document = _seed_document(adapter, path)
                if document is not None:
                    sources.setdefault(path, document)
    inferred: list[Requirement] = []
    seen: set[str] = set()
    for source_ref, document in sources.items():
        scopes = (
            _role_hiring_scopes(adapter, document, role)
            if role is not None and source_ref.endswith("roles-and-hiring.md")
            else [_safe_structural_scope(adapter, document)]
        )
        scopes = [scope for scope in scopes if scope.strip()]
        for scope in scopes:
            parsed_items = list(parse_job_description(
                scope, source_ref=source_ref
            ).requirements)
            if not parsed_items and role is not None:
                raw = re.sub(r"^\s*[-*•]\s+", "", scope).strip()
                labeled = re.match(r"^(.{1,80}?)[：:]\s*(.+?)\s*$", raw)
                if (
                    labeled
                    and _normalize_role_label(labeled.group(1))
                    in _role_label_variants(role.title)
                ):
                    parsed_values = [(raw, "requirement", 0.65)]
                else:
                    parsed_values = []
            else:
                parsed_values = [
                    (parsed.text, parsed.category, parsed.confidence)
                    for parsed in parsed_items
                ]
            for parsed_text, category, confidence in parsed_values:
                for atomic_text in _atomic_role_requirement_texts(
                    parsed_text, role
                ) if role is not None else [parsed_text]:
                    normalized = re.sub(r"\s+", " ", atomic_text).casefold()
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    inferred.append(make_inferred_requirement(
                        atomic_text,
                        inference_basis=(
                            "Historical exact-role evidence; "
                            "current complete JD unavailable."
                        ),
                        inference_source=source_ref,
                        confidence=min(confidence, 0.7),
                        requirement_id=f"INF-{len(inferred) + 1:03d}",
                        category=category,
                    ))
    return inferred


def _visible_claim_ids(document: Any) -> list[str]:
    data = document.model_dump(mode="python")
    return [str(claim) for section in ("experience", "projects") for item in data[section] for bullet in item["bullets"] for claim in bullet["claim_ids"]]


def _questions_markdown(questions: Sequence[str]) -> str:
    lines = ["# Confirmation questions", ""]
    lines.extend(f"- {question}" for question in questions)
    if not questions:
        lines.append("- No confirmation questions remain.")
    return "\n".join(lines) + "\n"


def _audit_markdown(report: Any, target: TargetContext) -> str:
    data = report.model_dump(mode="json", exclude_none=False)
    lines = ["# Audit report", "", f"- Success: {'yes' if data['success'] else 'no'}", f"- Target basis: `{target.target_basis.value}`"]
    lines.extend(f"- Limitation: {item}" for item in target.limitations)
    lines.extend(["", "## Errors", *([f"- {item}" for item in data["errors"]] or ["- None."]), "", "## Warnings", *([f"- {item}" for item in data["warnings"]] or ["- None."])])
    return "\n".join(lines) + "\n"


def _variant_artifact_names(spec: ResumeVariantSpec) -> dict[str, str]:
    base = spec.base_name
    return {
        "document": f"{base}.document.json",
        "provenance": f"{base}.provenance.json",
        "validation": f"{base}.validation.json",
        "audit": f"{base}.audit.md",
        "markdown": f"{base}.md",
        "ats_text": f"{base}.txt",
        "html": f"{base}.html",
        "pdf": f"{base}.pdf",
        "preview": f"{base}.preview.png",
    }


def _document_headings(document: Any) -> tuple[str, ...]:
    labels = resume_labels(document.locale)
    headings = tuple(
        labels[field]
        for field in (
            "summary",
            "skills",
            "experience",
            "projects",
            "education",
            "honors",
        )
        if getattr(document, field)
    )
    return headings + ((labels["links"],) if document.contact.links else ())


def _inspection_for_document(document: Any) -> InspectionConfig:
    expected_links = tuple(
        [
            *(
                ["mailto:" + document.contact.email]
                if document.contact.email
                else []
            ),
            *(str(link.url) for link in document.contact.links),
        ]
    )
    policy = document.render_policy
    return InspectionConfig(
        target_pages=policy.target_pages,
        minimum_pages=policy.minimum_pages,
        expected_name=document.contact.name,
        expected_headings=_document_headings(document),
        expected_links=expected_links,
        minimum_body_font_pt=policy.minimum_body_font_pt,
        minimum_margin_mm=policy.minimum_margin_mm,
        require_mailto_link=bool(document.contact.email),
        require_https_link=bool(document.contact.links),
    )


def _compact_overflowing_variant(
    current: Any,
    report: Any,
    attempt: int,
    spec: ResumeVariantSpec,
) -> Any | None:
    checks = (
        report.checks
        if isinstance(getattr(report, "checks", None), Mapping)
        else {}
    )
    if checks.get("page_limit", True):
        return None
    return compact_resume_document(
        current,
        max(
            spec.target_pages * 6,
            spec.max_cost - attempt * 2,
        ),
    )


def _ir_identity(value: Any, default: str) -> str:
    identity = _ir_value(value, "identity", None)
    if identity is None:
        identity = _ir_value(value, "id", None)
    return str(identity or default)


def _ir_heading_items(value: Any) -> list[str]:
    result: list[str] = []
    for item in value or ():
        if isinstance(item, str):
            result.append(item)
            continue
        result.append(
            str(
                _ir_value(item, "heading", None)
                or _ir_value(item, "title", None)
                or _ir_value(item, "text", None)
                or item
            )
        )
    return result

def _ir_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _ir_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    names = (
        "block_kind",
        "kind",
        "inside_fence",
        "inside_blockquote",
        "inside_html",
        "inside_example",
        "inside_template",
        "inside_quoted",
        "negative_instruction",
        "secret_path",
        "secret_content",
        "effective_fact_policy",
        "effective_fact_state",
        "fact_policy",
        "effective_disclosure_policy",
        "effective_disclosure",
        "disclosure_policy",
        "start_line",
        "end_line",
        "start_byte",
        "end_byte",
        "line_start",
        "line_end",
        "byte_start",
        "byte_end",
    )
    return {name: getattr(value, name) for name in names if hasattr(value, name)}


def _ir_hash(value: Any) -> str:
    digest = str(value or "")
    return digest if digest.startswith("sha256:") else f"sha256:{digest}"


def _ir_span(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    nested = _ir_value(value, "location", None) or _ir_value(value, "span", None)
    raw = _ir_mapping(nested or value)
    aliases = {
        "start_line": ("start_line", "line_start"),
        "end_line": ("end_line", "line_end"),
        "start_byte": ("start_byte", "byte_start"),
        "end_byte": ("end_byte", "byte_end"),
    }
    result: dict[str, Any] = {}
    for target, names in aliases.items():
        for name in names:
            if raw.get(name) is not None:
                result[target] = int(raw[name])
                break
    return result if len(result) == 4 else None


def _ir_flags(value: Any) -> dict[str, Any]:
    raw = _ir_mapping(value)
    aliases = {
        "block_kind": ("block_kind", "kind"),
        "inside_fence": ("inside_fence",),
        "inside_blockquote": ("inside_blockquote", "inside_block_quote"),
        "inside_html": ("inside_html",),
        "is_example": ("is_example", "inside_example", "example"),
        "is_template": ("is_template", "inside_template", "template"),
        "is_quoted": ("is_quoted", "inside_quoted", "quoted"),
        "negative_instruction": ("negative_instruction",),
        "secret_path": ("secret_path",),
        "secret_content": ("secret_content",),
        "malformed": ("malformed",),
        "effective_fact_policy": (
            "effective_fact_policy",
            "fact_policy",
            "effective_fact_state",
        ),
        "effective_disclosure_policy": (
            "effective_disclosure_policy",
            "disclosure_policy",
            "effective_disclosure",
        ),
    }
    result: dict[str, Any] = {}
    for target, names in aliases.items():
        for name in names:
            if raw.get(name) is not None:
                item = raw[name]
                result[target] = getattr(item, "value", item)
                break
    return result




def _ir_relative_path(root: Path, value: Any) -> str:
    candidate = Path(str(value or ""))
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve(strict=True)
    else:
        resolved = (root / candidate).resolve(strict=True)
    if resolved.is_symlink():
        raise PipelineError(f"source document must not be a symlink: {resolved}")
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise PipelineError(f"source path escapes source root: {value}") from exc


def _source_map_from_root(root: str | Path) -> Any:
    """Build metadata-only SourceMapIR from one structural read per document."""

    from .ir import SourceMapIR
    from .markdown_structure import parse_markdown

    source_root = Path(root).expanduser().resolve(strict=True)
    if not source_root.is_dir() or source_root.is_symlink():
        raise PipelineError(f"source root must be a real directory: {root}")
    documents: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in {".md", ".markdown"}:
            continue
        relative_candidate = path.relative_to(source_root).as_posix()
        if any(
            re.search(
                r"(?:^|[-_.])(?:secret|secrets|credential|credentials|password|"
                r"passwords|private[-_]?key|token|tokens|\.env)(?:$|[-_.])",
                part,
                re.IGNORECASE,
            )
            for part in PurePosixPath(relative_candidate).parts
        ):
            continue
        if path.is_symlink():
            raise PipelineError(f"source document must not be a symlink: {path}")
        relative = _ir_relative_path(source_root, path)
        if relative in seen_paths:
            continue
        seen_paths.add(relative)
        document = parse_markdown(path, source_root=source_root)
        document_id = str(_ir_value(document, "document_id", f"document:{relative}"))
        navigation = getattr(document, "navigation_metadata", None)
        navigation_payload: Mapping[str, Any] = {}
        if callable(navigation):
            try:
                raw_navigation = navigation()
            except ValueError as exc:
                raise PipelineError(str(exc)) from exc
            if not isinstance(raw_navigation, Mapping):
                raise PipelineError("navigation metadata must be a mapping")
            navigation_payload = raw_navigation
        source_hash = _ir_hash(_ir_value(document, "source_hash"))
        document_span = _ir_span(
            _ir_value(document, "span", None)
            or _ir_value(document, "location", None)
        )
        fact_policy = _ir_value(
            document,
            "document_fact_policy",
            _ir_value(document, "document_fact_state", "F1"),
        )
        disclosure_policy = _ir_value(
            document,
            "document_disclosure_policy",
            _ir_value(document, "document_disclosure", "P0"),
        )
        document_payload: dict[str, Any] = {
            "document_id": document_id,
            "path": relative,
            "source_hash": source_hash,
            "document_fact_policy": getattr(fact_policy, "value", fact_policy),
            "document_disclosure_policy": getattr(disclosure_policy, "value", disclosure_policy),
            "validation_warnings": [
                str(item)
                for item in (
                    _ir_value(document, "validation_warnings", None)
                    or _ir_value(document, "warnings", ())
                )
            ],
        }
        if document_span is not None:
            document_payload["span"] = document_span
        documents.append(document_payload)

        all_sections = list(_ir_value(document, "sections", ()) or ())
        safe_section_ids = {
            str(item.get("identity"))
            for item in navigation_payload.get("sections", ())
            if isinstance(item, Mapping) and item.get("identity")
        }
        raw_sections = [
            section
            for section in all_sections
            if _ir_identity(section, "") in safe_section_ids
        ]
        raw_blocks = list(_ir_value(document, "blocks", ()) or ())
        section_ids: dict[int, str] = {}
        block_ids: dict[int, str] = {}
        for index, section in enumerate(raw_sections):
            section_ids[id(section)] = _ir_identity(
                section,
                f"{document_id}:section:{index + 1}",
            )
        for index, block in enumerate(raw_blocks):
            block_ids[id(block)] = _ir_identity(
                block,
                f"{document_id}:block:{index + 1}",
            )
        section_block_ids: dict[str, list[str]] = {value: [] for value in section_ids.values()}
        for block in raw_blocks:
            if not source_map_block_is_safe(block):
                continue
            block_id = block_ids[id(block)]
            section = _ir_value(block, "section", None)
            section_id = _ir_value(block, "section_id", None)
            if section_id is None:
                section_id = _ir_value(block, "section_identity", None)
            if section_id is None and section is not None:
                section_id = section_ids.get(id(section))
            if section_id is None:
                section_index = _ir_value(block, "section_index", None)
                if section_index is not None and int(section_index) < len(raw_sections):
                    section_id = section_ids[id(raw_sections[int(section_index)])]
            if section_id not in section_block_ids:
                continue
            block_span = _ir_span(
                _ir_value(block, "span", None)
                or _ir_value(block, "location", None)
            )
            if block_span is None:
                continue
            block_flags = _ir_flags(
                _ir_value(block, "structural_flags", None)
                or _ir_value(block, "flags", None)
                or block
            )
            block_flags.setdefault(
                "block_kind",
                str(_ir_value(block, "block_kind", _ir_value(block, "kind", "unknown"))),
            )
            block_fact = _ir_value(block, "effective_fact_policy", None) or _ir_value(block, "effective_fact_state", None)
            block_disclosure = _ir_value(block, "effective_disclosure_policy", None) or _ir_value(block, "effective_disclosure", None)
            if block_fact is not None:
                block_flags["effective_fact_policy"] = getattr(block_fact, "value", block_fact)
            if block_disclosure is not None:
                block_flags["effective_disclosure_policy"] = getattr(block_disclosure, "value", block_disclosure)
            block_payload: dict[str, Any] = {
                "block_id": block_id,
                "document_id": document_id,
                "span": block_span,
                "heading_ancestry": _ir_heading_items(
                    _ir_value(block, "heading_ancestry", ())
                    or _ir_value(block, "ancestors", ())
                ),
                "structural_flags": block_flags,
            }
            block_payload["section_id"] = section_id
            section_block_ids[section_id].append(block_id)
            blocks.append(block_payload)
        for index, section in enumerate(raw_sections):
            section_id = section_ids[id(section)]
            section_span = _ir_span(
                _ir_value(section, "span", None)
                or _ir_value(section, "location", None)
            )
            if section_span is None:
                continue
            heading = str(
                _ir_value(section, "heading", None)
                or _ir_value(section, "title", None)
                or f"Section {index + 1}"
            )
            ancestry = _ir_heading_items(
                _ir_value(section, "heading_ancestry", ())
                or _ir_value(section, "ancestors", ())
            )
            section_flags = _ir_flags(
                _ir_value(section, "structural_flags", None)
                or _ir_value(section, "flags", None)
                or section
            )
            section_flags.setdefault("block_kind", "section")
            section_fact = _ir_value(section, "effective_fact_policy", None) or _ir_value(section, "effective_fact_state", None)
            section_disclosure = _ir_value(section, "effective_disclosure_policy", None) or _ir_value(section, "effective_disclosure", None)
            if section_fact is not None:
                section_flags["effective_fact_policy"] = getattr(section_fact, "value", section_fact)
            if section_disclosure is not None:
                section_flags["effective_disclosure_policy"] = getattr(section_disclosure, "value", section_disclosure)
            sections.append(
                {
                    "section_id": section_id,
                    "document_id": document_id,
                    "span": section_span,
                    "heading": heading,
                    "heading_ancestry": ancestry,
                    "duplicate_index": int(
                        _ir_value(
                            section,
                            "duplicate_index",
                            _ir_value(section, "occurrence", 0),
                        )
                        or 0
                    ),
                    "block_ids": section_block_ids.get(section_id, []),
                    "structural_flags": section_flags,
                }
            )
    return SourceMapIR(documents=documents, sections=sections, blocks=blocks, proposals=[])


def _ir_unwrap(payload: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            return nested
    return payload
def _validate_ir_with_sources(
    value: Mapping[str, Any],
    source: str | Path | None,
    schema: str,
) -> Any:
    from .validation import (
        revalidate_evidence_input,
        revalidate_role_input,
    )

    if source is None:
        raise PipelineError(f"{schema} validation requires --source")
    source_map_payload = value.get("source_map") or value.get("source_map_ir")
    if not isinstance(source_map_payload, Mapping):
        raise PipelineError(f"{schema} validation requires source_map")
    normalized = _ir_unwrap(
        value,
        schema,
        schema.replace("-", "_"),
        "input",
        "evidence_input",
        "role_input",
    )
    source_map = _ir_unwrap(source_map_payload, "source_map", "source-map")
    if schema == "normalized-role-input":
        return revalidate_role_input(normalized, source_map, source)
    return revalidate_evidence_input(normalized, source_map, source)

def _materialize_extractive(
    value: Mapping[str, Any],
    source: str | Path | None,
) -> dict[str, Any]:
    from .ir import (
        ClaimMode,
        EvidenceCandidateIR,
        ProposalDomain,
        ProposalOwner,
        SemanticProposal,
        SourceMapIR,
        SourceReference,
    )
    from .markdown_structure import parse_markdown
    from .validation import revalidate_evidence_input, revalidate_source_map

    if source is None:
        raise PipelineError("materialize_extractive requires --source")
    source_map_payload = value.get("source_map") or value.get("source_map_ir")
    wrapper = value.get("materialize_extractive")
    if not isinstance(source_map_payload, Mapping) or not isinstance(wrapper, Mapping):
        raise PipelineError("materialize_extractive requires source_map and wrapper")
    marker = wrapper.get("profile_field_marker")
    input_id = wrapper.get("input_id")
    block_ids = wrapper.get("block_ids") or wrapper.get("selected_block_ids")
    evidence_ids = wrapper.get("evidence_ids")
    requirement_ids = wrapper.get("requirement_ids")
    if not isinstance(input_id, str) or not input_id:
        raise PipelineError("materialize_extractive requires input_id")
    if not isinstance(marker, str) or not marker:
        raise PipelineError("materialize_extractive requires profile_field_marker")
    if not isinstance(block_ids, list) or not block_ids:
        raise PipelineError("materialize_extractive requires selected block_ids")
    if not isinstance(evidence_ids, (list, Mapping)):
        raise PipelineError("materialize_extractive requires evidence_ids")
    if not isinstance(requirement_ids, (list, Mapping)):
        raise PipelineError("materialize_extractive requires requirement_ids")
    source_map = SourceMapIR.model_validate(
        _ir_unwrap(source_map_payload, "source_map", "source-map")
    )
    revalidate_source_map(source_map, source)
    documents = {item.document_id: item for item in source_map.documents}
    blocks = {item.block_id: item for item in source_map.blocks}
    parsed: dict[str, Any] = {}
    candidates: list[EvidenceCandidateIR] = []
    proposals = list(source_map.proposals)
    for index, selected_id in enumerate(block_ids):
        block = blocks.get(str(selected_id))
        if block is None:
            raise PipelineError(f"materialize_extractive unknown block ID: {selected_id!r}")
        flags = block.structural_flags
        fact = str(getattr(flags.effective_fact_policy, "value", flags.effective_fact_policy))
        disclosure = str(getattr(flags.effective_disclosure_policy, "value", flags.effective_disclosure_policy))
        if flags.blocked or fact in {"F3", "F4", "F5", "F6"} or disclosure == "P3":
            raise PipelineError(f"materialize_extractive blocked block: {selected_id!r}")
        document = documents.get(block.document_id)
        if document is None:
            raise PipelineError(f"materialize_extractive block has unknown document: {selected_id!r}")
        if isinstance(evidence_ids, Mapping):
            evidence_id = evidence_ids.get(str(selected_id))
        else:
            evidence_id = evidence_ids[index] if index < len(evidence_ids) else None
        if not isinstance(evidence_id, str) or not evidence_id:
            raise PipelineError(f"materialize_extractive missing evidence ID for block: {selected_id!r}")
        if isinstance(requirement_ids, Mapping):
            reqs = requirement_ids.get(str(selected_id), [])
        else:
            reqs = requirement_ids or []
        if not isinstance(reqs, list) or any(not isinstance(item, str) for item in reqs):
            raise PipelineError("materialize_extractive requirement_ids must be string lists")
        if document.path not in parsed:
            parsed[document.path] = parse_markdown(
                Path(source).expanduser().resolve(strict=True) / document.path,
                source_root=Path(source).expanduser().resolve(strict=True),
            )
        parsed_document = parsed[document.path]
        actual = next(
            (item for item in parsed_document.blocks if item.identity == block.block_id),
            None,
        )
        if actual is None:
            raise PipelineError(f"materialize_extractive block disappeared: {selected_id!r}")
        location = actual.location
        if (
            location.source_hash != document.source_hash
            or location.start_line != block.span.start_line
            or location.end_line != block.span.end_line
            or location.start_byte != block.span.start_byte
            or location.end_byte != block.span.end_byte
        ):
            raise PipelineError(f"materialize_extractive block span changed: {selected_id!r}")
        exact_quote = actual.exact_quote
        reference = SourceReference(
            path=document.path,
            source_hash=document.source_hash,
            span=block.span,
            exact_quote=exact_quote,
            structural_flags=flags,
            heading_ancestry=list(actual.heading_ancestry),
            section_id=block.section_id,
            block_id=block.block_id,
        )
        proposal_id = f"materialized:{evidence_id}"
        proposal = SemanticProposal(
            proposal_id=proposal_id,
            source=reference,
            domain=ProposalDomain.EVIDENCE,
            owner=ProposalOwner.UNKNOWN,
            proposed_claim=exact_quote,
            confidence=1.0,
            reasoning=f"mechanical extractive materialization for {marker}",
            claim_mode=ClaimMode.EXTRACTIVE,
            unresolved_questions=["candidate ownership requires independent confirmation"],
        )
        candidate = EvidenceCandidateIR(
            evidence_id=evidence_id,
            proposal_id=proposal_id,
            source=reference,
            proposed_claim=exact_quote,
            owner=ProposalOwner.UNKNOWN,
            confidence=1.0,
            reasoning=proposal.reasoning,
            claim_mode=ClaimMode.EXTRACTIVE,
            requirement_ids=reqs,
            unresolved_questions=["candidate ownership requires independent confirmation"],
        )
        proposals.append(proposal)
        candidates.append(candidate)
    augmented_map = source_map.model_copy(update={"proposals": proposals})
    revalidate_source_map(augmented_map, source)
    evidence = revalidate_evidence_input(
        {"schema_version": 1, "input_id": input_id, "domain": "evidence", "candidates": candidates},
        augmented_map,
        source,
    )
    return {
        "source_map": augmented_map,
        "evidence_input": evidence,
        "profile_field_marker": marker,
    }



def _write_stage_ir(value: Any, output: str | Path | None, source: str | Path | None = None) -> Any:
    if output is not None:
        if source is not None:
            validate_output_root(source, Path(output).parent)
        write_json(output, value)
    return value


def _approved_claim_evidence_records(
    approved: Any,
    evidence_input: Mapping[str, Any] | Any,
) -> list[dict[str, Any]]:
    """Adapt locked claims to composition only after origin resolution."""

    candidates = list(_ir_value(evidence_input, "candidates", ()) or ())
    by_id = {
        str(_ir_value(candidate, "evidence_id")): candidate
        for candidate in candidates
    }
    if not candidates:
        raise PipelineError("generate-from-ir requires a non-empty normalized evidence input")
    claims = _ir_value(approved, "claims", ()) or ()
    records: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = str(_ir_value(claim, "claim_id"))
        origin_ids = list(_ir_value(claim, "origin_evidence_ids", ()) or ())
        if not origin_ids:
            raise PipelineError(f"approved claim {claim_id!r} has no origin evidence IDs")
        origins = []
        for evidence_id in origin_ids:
            origin = by_id.get(str(evidence_id))
            if origin is None:
                raise PipelineError(
                    f"approved claim {claim_id!r} references unknown evidence {evidence_id!r}"
                )
            source = _ir_value(origin, "source", None)
            source_data = _ir_mapping(source)
            flags = _ir_mapping(_ir_value(source, "structural_flags", None))
            required = ("path", "source_hash", "span", "exact_quote")
            missing = [key for key in required if not source_data.get(key)]
            if missing:
                raise PipelineError(
                    f"evidence {evidence_id!r} source reference is incomplete: {missing}"
                )
            if not flags.get("effective_fact_policy") or not flags.get("effective_disclosure_policy"):
                raise PipelineError(
                    f"evidence {evidence_id!r} source reference lacks effective fact/disclosure policy"
                )
            section = source_data.get("section_id") or source_data.get("block_id")
            if not section:
                raise PipelineError(f"evidence {evidence_id!r} source reference lacks section or block identity")
            origins.append((source_data, flags, str(section)))
        source_data, flags, section = origins[0]
        origin = by_id[str(origin_ids[0])]
        contribution = list(_ir_value(origin, "contribution_qualifiers", ()) or ())
        metric = list(_ir_value(origin, "metric_qualifiers", ()) or ())
        contribution_text = "; ".join(
            str(_ir_value(item, "text", item)) for item in contribution
        ) or "approved"
        metric_text = "; ".join(str(_ir_value(item, "text", item)) for item in metric) or None
        records.append(
            {
                "evidence_id": claim_id,
                "claim_id": claim_id,
                "evidence_ids": [str(item) for item in origin_ids],
                "source": {
                    "path": str(source_data["path"]),
                    "section": section,
                    "source_hash": str(source_data["source_hash"]),
                    "source_type": "approved-claim",
                },
                "fact_state": str(flags["effective_fact_policy"]),
                "disclosure": str(flags["effective_disclosure_policy"]),
                "match_state": "已有直接证据",
                "contribution_scope": contribution_text,
                "metric_precision": metric_text,
                "safe_claim": str(_ir_value(claim, "approved_safe_claim")),
                "forbidden_expansions": [],
                "freshness": {"dynamic": False, "stale": False},
                "output_mode": "targeted_application",
            }
        )
    return records


def _minimal_generation_profile(
    claims: Sequence[Any],
    payload: Mapping[str, Any],
    records: Sequence[Any] = (),
) -> dict[str, Any]:
    """Build every visible profile value from locked claim IDs."""

    by_id = {str(_ir_value(claim, "claim_id")): claim for claim in claims}
    record_refs = {
        str(_ir_value(record, "evidence_id")): provenance_ref(record)
        for record in records
        if provenance_ref(record)
    }
    def refs_for(ids: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(record_refs[item] for item in ids if item in record_refs))

    def claim_text(claim_id: Any, *, label: str) -> str:
        if not isinstance(claim_id, str) or claim_id not in by_id:
            raise PipelineError(f"{label} references unknown claim ID: {claim_id!r}")
        claim = by_id[claim_id]
        if str(_ir_value(claim, "disclosure_decision")) != "allowed":
            raise PipelineError(f"{label} references a non-disclosure-approved claim")
        return str(_ir_value(claim, "approved_safe_claim"))

    profile_mapping = payload.get("candidate_profile_claims")
    if not isinstance(profile_mapping, Mapping) or not profile_mapping.get("name"):
        raise PipelineError("generate-from-ir requires candidate_profile_claims.name")
    profile_allowed = {"name", "summary", "email", "phone", "location", "links"}
    unknown_profile = sorted(set(profile_mapping).difference(profile_allowed))
    if unknown_profile:
        raise PipelineError(f"unknown candidate profile claim keys: {unknown_profile}")
    used: set[str] = set()
    values: dict[str, Any] = {}
    for key, raw_ids in profile_mapping.items():
        ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
        if not ids or any(not isinstance(item, str) for item in ids):
            raise PipelineError(f"candidate profile mapping {key!r} must contain claim IDs")
        texts = []
        for claim_id in ids:
            if claim_id in used:
                raise PipelineError(f"candidate profile claim ID reused: {claim_id!r}")
            used.add(claim_id)
            texts.append(claim_text(claim_id, label=f"candidate profile {key}"))
        values[key] = texts if key in {"summary", "links"} else texts[0]

    placements = payload.get("claim_placements")
    if not isinstance(placements, (list, Mapping)):
        raise PipelineError("generate-from-ir requires claim_placements")
    if isinstance(placements, Mapping):
        normalized_placements = []
        for claim_id, metadata in placements.items():
            if not isinstance(metadata, Mapping):
                raise PipelineError("claim_placements mapping values must be objects")
            normalized_placements.append({"claim_id": claim_id, **metadata})
    else:
        normalized_placements = list(placements)
    sections = {"summary", "skill", "experience", "project", "education", "honor"}
    placement_used: set[str] = set()
    metadata_owners: dict[str, tuple[str, str]] = {}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    seen_orders: set[tuple[str, str, int]] = set()
    metadata_keys = (
        "title_claim_id",
        "organization_claim_id",
        "period_claim_id",
        "context_claim_id",
    )
    for raw_placement in normalized_placements:
        if not isinstance(raw_placement, Mapping):
            raise PipelineError("claim_placements entries must be objects")
        placement = dict(raw_placement)
        allowed = {"claim_id", "section", "group_id", "order", *metadata_keys}
        unknown = sorted(set(placement).difference(allowed))
        if unknown:
            raise PipelineError(f"unknown claim placement keys: {unknown}")
        claim_id = placement.get("claim_id")
        section = placement.get("section")
        group_id = placement.get("group_id")
        order = placement.get("order")
        if not isinstance(claim_id, str) or claim_id not in by_id:
            raise PipelineError(f"claim placement references unknown claim ID: {claim_id!r}")
        if claim_id in used or claim_id in placement_used:
            raise PipelineError(f"claim ID is duplicated across profile/placements: {claim_id!r}")
        if section not in sections or not isinstance(group_id, str) or not group_id:
            raise PipelineError("claim placement requires closed section and stable group_id")
        if not isinstance(order, int) or order < 0:
            raise PipelineError("claim placement requires non-negative integer order")
        group_key = (section, group_id)
        order_key = (*group_key, order)
        if order_key in seen_orders:
            raise PipelineError(f"duplicate claim placement order: {order_key}")
        seen_orders.add(order_key)
        group = groups.setdefault(
            group_key,
            {"section": section, "group_id": group_id, "items": [], "metadata": {}},
        )
        for key in metadata_keys:
            metadata_id = placement.get(key)
            inherited = group["metadata"].get(key)
            if metadata_id is None and inherited is not None:
                placement[key] = inherited
                continue
            if metadata_id is None:
                continue
            if inherited is not None and inherited != metadata_id:
                raise PipelineError(f"claim placement metadata differs within group: {group_key}")
            owner = metadata_owners.get(str(metadata_id))
            if owner is not None and owner != group_key:
                raise PipelineError(f"claim placement metadata reused across groups: {metadata_id!r}")
            if metadata_id in used or metadata_id == claim_id:
                raise PipelineError(f"claim placement metadata ID is duplicated: {metadata_id!r}")
            metadata_owners[str(metadata_id)] = group_key
            group["metadata"][key] = metadata_id
            placement_used.add(str(metadata_id))
            claim_text(metadata_id, label="claim placement metadata")
        if section in {"skill", "experience", "project", "education", "honor"} and not placement.get("title_claim_id"):
            raise PipelineError(f"{section} placement requires title_claim_id")
        if section == "experience" and not placement.get("organization_claim_id"):
            raise PipelineError("experience placement requires organization_claim_id")
        placement_used.add(claim_id)
        group["items"].append(placement)

    all_ids = set(by_id)
    covered = used | placement_used
    if covered != all_ids:
        raise PipelineError(f"claim placements do not cover locked claims: {sorted(all_ids - covered)}")

    metadata_ids = used | placement_used
    summary: list[str] = []
    skills: list[dict[str, Any]] = []
    experience: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    honors: list[dict[str, Any]] = []
    for (section, group_id), group in sorted(groups.items(), key=lambda item: item[0]):
        items = sorted(group["items"], key=lambda item: item["order"])
        primary_ids = [str(item["claim_id"]) for item in items]
        metadata_group_ids = primary_ids + [
            str(item[key])
            for item in items
            for key in (
                "title_claim_id",
                "organization_claim_id",
                "period_claim_id",
                "context_claim_id",
            )
            if item.get(key)
        ]
        group_refs = refs_for(metadata_group_ids)
        if section == "summary":
            summary.extend(claim_text(item["claim_id"], label="summary placement") for item in items)
            continue
        title = claim_text(items[0]["title_claim_id"], label="placement title")
        organization = (
            claim_text(items[0]["organization_claim_id"], label="placement organization")
            if items[0].get("organization_claim_id") else None
        )
        context = (
            claim_text(items[0]["context_claim_id"], label="placement context")
            if items[0].get("context_claim_id") else None
        )
        period = (
            claim_text(items[0]["period_claim_id"], label="placement period")
            if items[0].get("period_claim_id") else None
        )
        primary_texts = [claim_text(item["claim_id"], label="placement claim") for item in items]
        if section == "skill":
            skills.append({
                "name": title,
                "items": primary_texts,
                "evidence_ids": primary_ids,
                "provenance_refs": group_refs,
            })
        elif section == "experience":
            experience.append({
                "organization": organization,
                "role": title,
                "location": None,
                "start_date": period or "",
                "end_date": "",
                "context": context,
                "evidence_ids": primary_ids,
                "provenance_refs": group_refs,
                "bullets": [],
            })
        elif section == "project":
            projects.append({
                "name": title,
                "role": organization,
                "context": context,
                "start_date": period,
                "end_date": None,
                "technologies": [],
                "evidence_ids": primary_ids,
                "provenance_refs": group_refs,
                "bullets": [],
            })
        elif section == "education":
            education.append({
                "institution": title,
                "degree": organization,
                "field": None,
                "start_date": period,
                "end_date": None,
                "details": primary_texts + ([context] if context else []),
                "provenance_refs": group_refs,
            })
        elif section == "honor":
            honors.append({
                "name": title,
                "issuer": organization,
                "date": period,
                "details": "；".join(primary_texts + ([context] if context else [])),
                "provenance_refs": group_refs,
            })
    target_data = payload.get("target_context")
    headline = target_data.get("role") if isinstance(target_data, Mapping) and target_data.get("role") else payload.get("role") or payload.get("role_title") or ""
    return {
        "contact": {key: values[key] for key in ("name", "email", "phone", "location", "links") if key in values},
        "headline": str(headline),
        "summary": summary or values.get("summary", []),
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": education,
        "honors": honors,
        "metadata_evidence_ids": sorted(metadata_ids),
        "provenance_refs": refs_for(sorted(metadata_ids)),
    }

class Pipeline:
    """Compose existing domain functions without reproducing their policy rules."""

    def __init__(self, adapter_factory: Any = MarkdownCareerV1Adapter) -> None:
        self._adapter_factory = adapter_factory

    def _adapter(self, source: Path) -> MarkdownCareerV1Adapter:
        return self._adapter_factory(source)
    def discover_source_structure(
        self,
        source: str | Path,
        *,
        output: str | Path | None = None,
    ) -> Any:
        source_map = _source_map_from_root(source)
        return _write_stage_ir(source_map, output, source)

    def validate_source_map(
        self,
        source: str | Path,
        source_map: Mapping[str, Any] | Any,
        *,
        output: str | Path | None = None,
    ) -> Any:
        from .validation import revalidate_source_map

        if isinstance(source_map, Mapping):
            source_map = _ir_unwrap(source_map, "source_map", "source-map")
        validated = revalidate_source_map(source_map, source)
        return _write_stage_ir(validated, output, source)

    def validate_role_input(
        self,
        value: Mapping[str, Any] | Any,
        *,
        source: str | Path | None = None,
        output: str | Path | None = None,
    ) -> Any:
        if not isinstance(value, Mapping):
            raise PipelineError("validate-role-input input must be a JSON object")
        validated = _validate_ir_with_sources(value, source, "normalized-role-input")
        return _write_stage_ir(validated, output, source)

    def validate_evidence_input(
        self,
        value: Mapping[str, Any] | Any,
        *,
        source: str | Path | None = None,
        output: str | Path | None = None,
    ) -> Any:
        if "materialize_extractive" in value:
            materialized = _materialize_extractive(value, source)
            return _write_stage_ir(materialized, output, source)
        validated = _validate_ir_with_sources(value, source, "normalized-evidence-input")
        return _write_stage_ir(validated, output, source)

    def approve_claims(
        self,
        value: Mapping[str, Any] | Any,
        *,
        source: str | Path | None = None,
        output: str | Path | None = None,
    ) -> Any:
        from .validation import approve_claims as approve_claims_ir

        if not isinstance(value, Mapping):
            raise PipelineError("approve-claims input must be a JSON object")
        evidence = _validate_ir_with_sources(value, source, "normalized-evidence-input")
        reviews: Any = (
            value.get("review_decisions")
            or value.get("reviews")
            or value.get("review_decision")
        )
        if reviews is None:
            raise PipelineError("approve-claims input requires review_decisions")
        approved = approve_claims_ir(
            evidence,
            reviews,
            approved_safe_claims=value.get("approved_safe_claims"),
            user_confirmations=value.get("user_confirmations"),
        )
        return _write_stage_ir(approved, output, source)

    def generate_from_ir(
        self,
        value: Mapping[str, Any] | Any,
        *,
        source: str | Path | None = None,
        output_root: str | Path | None = None,
        output: str | Path | None = None,
        include_extended_profile: bool | None = None,
    ) -> PipelineResult:
        """Compose variants using only immutable approved claim text."""

        from .ir import ApprovedClaimsIR
        from .validation import (
            approve_claims as approve_claims_ir,
            check_provenance_closure,
            lock_approved_claims,
            revalidate_evidence_input,
        )
        from .models import (
            JdCompleteness,
            OutputMode,
            TargetBasis,
            TargetContext,
        )

        if not isinstance(value, Mapping):
            raise PipelineError("generate-from-ir input must be a JSON object")
        payload = dict(value)
        approved_payload = _ir_unwrap(
            payload,
            "approved_claims",
            "approved_claims_ir",
            "approved-claims",
        )
        submitted: ApprovedClaimsIR = ApprovedClaimsIR.model_validate(approved_payload)
        request_data = payload.get("request")
        if not isinstance(request_data, Mapping):
            request_data = {}
        source_root = source or payload.get("source_root") or request_data.get("source_root")
        root = output_root or payload.get("output_root") or request_data.get("output_root")
        if source_root is None or root is None:
            raise PipelineError("generate-from-ir requires source_root and output_root metadata")
        source_path, destination_root = validate_output_root(source_root, root)
        source_map_payload = payload.get("source_map") or payload.get("source_map_ir")
        evidence_payload = payload.get("evidence_input") or payload.get("normalized_evidence_input")
        if not isinstance(source_map_payload, Mapping) or not isinstance(evidence_payload, Mapping):
            raise PipelineError("generate-from-ir requires source_map and normalized evidence input")
        source_map = _ir_unwrap(source_map_payload, "source_map", "source-map")
        evidence = revalidate_evidence_input(
            _ir_unwrap(evidence_payload, "evidence_input", "normalized-evidence-input"),
            source_map,
            source_path,
        )
        required_approval_inputs = ("review_decisions", "approved_safe_claims", "user_confirmations")
        missing_approval_inputs = [key for key in required_approval_inputs if key not in payload]
        if missing_approval_inputs:
            raise PipelineError(
                f"generate-from-ir requires approval inputs: {missing_approval_inputs}"
            )
        recomputed = approve_claims_ir(
            evidence,
            payload["review_decisions"],
            approved_safe_claims=payload["approved_safe_claims"],
            user_confirmations=payload["user_confirmations"],
        )
        canonical_submitted = json.dumps(
            submitted.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_recomputed = json.dumps(
            recomputed.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if canonical_submitted != canonical_recomputed:
            raise PipelineError("submitted approved_claims do not equal deterministic approval output")
        approved = lock_approved_claims(recomputed)
        closure = check_provenance_closure(
            approved,
            evidence,
            payload["review_decisions"],
            [claim.claim_id for claim in approved.claims],
        )
        if not closure["closed"]:
            raise PipelineError(
                f"approved claim provenance is not closed: {closure['missing']}"
            )
        claims = list(approved.claims)
        records = _approved_claim_evidence_records(approved, evidence)
        mode_value = payload.get("output_mode") or request_data.get("output_mode") or OutputMode.TARGETED_APPLICATION.value
        locale = str(payload.get("language") or request_data.get("language") or "zh-CN")
        template = str(payload.get("template") or request_data.get("template") or "adaptive")
        extended = (
            include_extended_profile
            if include_extended_profile is not None
            else bool(payload.get("include_extended_profile", request_data.get("include_extended_profile", False)))
        )
        target_data = payload.get("target_context") or request_data.get("target_context")
        if isinstance(target_data, Mapping):
            target = TargetContext.model_validate(target_data)
        else:
            target = TargetContext(
                target_basis=(
                    TargetBasis.COMPANY_ROLE_FAMILY
                    if payload.get("role") or request_data.get("role")
                    else TargetBasis.INSUFFICIENT_TARGET
                ),
                company=payload.get("company") or request_data.get("company"),
                role=payload.get("role") or request_data.get("role") or payload.get("role_title"),
                jd_completeness=JdCompleteness.UNAVAILABLE,
            )
        profile = _minimal_generation_profile(claims, payload, records)
        requirements = payload.get("requirements") or ()
        mappings = payload.get("mappings") or ()
        specs = (_RECRUITER_ONE_PAGE, _TECHNICAL_TWO_PAGE) + (
            (_EXTENDED_THREE_PAGE,) if extended else ()
        )
        run_dir = create_run_directory(destination_root, target.company, target.role)
        artifacts: list[Path] = []
        variant_manifest: list[dict[str, Any]] = []
        variant_summaries: dict[str, dict[str, Any]] = {}
        for spec in specs:
            variant_template = _template_for_variant(template, spec.variant)
            document = build_resume_document(
                profile,
                target,
                records,
                mappings,
                requirements,
                mode=mode_value,
                locale=locale,
                variant=spec.variant,
                target_pages=spec.target_pages,
                minimum_pages=1,
                template=variant_template,
            )
            names = _variant_artifact_names(spec)
            pdf_result = render_with_compaction(
                document,
                run_dir / names["pdf"],
                inspection_config=_inspection_for_document(document),
                template=variant_template,
                preview_path=run_dir / names["preview"],
                compact=lambda current, report, attempt, current_spec=spec: _compact_overflowing_variant(
                    current, report, attempt, current_spec
                ),
                max_attempts=5,
                margin_mm=12.0,
            )
            final_document = pdf_result.document
            visible_claim_ids = _visible_claim_ids(final_document)
            provenance = build_provenance(records, visible_claim_ids, mode=mode_value)
            audit = audit_resume(
                final_document,
                records,
                mappings,
                requirements,
                provenance,
                mode=mode_value,
            )
            artifacts.extend(
                [
                    write_json(run_dir / names["document"], final_document),
                    write_json(run_dir / names["provenance"], provenance),
                    write_json(run_dir / names["validation"], audit),
                    write_text(run_dir / names["audit"], _audit_markdown(audit, target)),
                    write_text(run_dir / names["markdown"], render_targeted_markdown(final_document)),
                    write_text(run_dir / names["ats_text"], render_ats_text(final_document)),
                    write_text(run_dir / names["html"], render_html(final_document, variant_template)),
                    Path(pdf_result.pdf_path),
                    *(Path(path) for path in pdf_result.preview_paths),
                ]
            )
            pdf_validation = pdf_result.validation
            pdf_success = bool(pdf_validation is not None and pdf_validation.success)
            variant_key = spec.variant.value
            variant_summaries[variant_key] = {
                "audit_success": audit.success,
                "pdf_success": pdf_success,
                "pages": pdf_validation.pages if pdf_validation is not None else None,
                "visible_claims": len(visible_claim_ids),
            }
            variant_manifest.append(
                {
                    "variant": variant_key,
                    "base_name": spec.base_name,
                    "template": variant_template,
                    "target_pages": spec.target_pages,
                    "actual_pages": pdf_validation.pages if pdf_validation is not None else None,
                    "underfilled": len(visible_claim_ids) < spec.target_pages * 6,
                    "visible_claims": len(visible_claim_ids),
                    "audit_success": audit.success,
                    "pdf_success": pdf_success,
                    "artifacts": {key: item for key, item in names.items() if key != "preview"},
                    "previews": [Path(path).name for path in pdf_result.preview_paths],
                }
            )
        manifest_path = write_json(
            run_dir / "resume-variants.json",
            {"schema_version": 1, "variants": variant_manifest},
        )
        artifacts.append(manifest_path)
        for path in artifacts:
            if path.exists():
                path.chmod(0o600)
        result = PipelineResult(
            "generate-from-ir",
            run_dir,
            tuple(dict.fromkeys(artifacts)),
            {
                "resume_variants": str(manifest_path),
                "variants": variant_summaries,
                "approved_claims": len(claims),
                "source_root": str(source_path),
            },
        )
        if output is not None:
            write_json(output, result.model_dump(mode="json"))
        return result


    def list_companies(self, source: str | Path) -> list[CompanyRef]:
        return self._adapter(_career_source_root(source)).list_companies()

    def list_roles(self, source: str | Path, company: str) -> list[RoleRef]:
        adapter = self._adapter(_career_source_root(source))
        return adapter.list_roles(_match_company(adapter, company))

    def generate(self, request: RunRequest | Mapping[str, Any]) -> PipelineResult:
        run_request = request if isinstance(request, RunRequest) else RunRequest.model_validate(request)
        run_request = run_request.model_copy(
            update={"source_root": _career_source_root(run_request.source_root)}
        )
        source, output_root = validate_output_root(run_request.source_root, run_request.output_root)
        adapter = self._adapter(source)
        manifest = adapter.manifest
        company = _match_company(adapter, run_request.company_ref)
        role = _match_role(adapter, company, run_request.role_ref)
        jd_text, jd_origin = _load_jd(run_request.jd)
        role_request = RoleRequest(company_ref=company, role_ref=role, jd=JdInput(text=jd_text or None))
        parsed_jd = parse_job_description(jd_text) if jd_text.strip() else None
        hiring_evidence = adapter.load_company(company).values() if company and not jd_text else ()
        target = resolve_target(
            role_request,
            jd_text=jd_text or None,
            hiring_evidence=hiring_evidence,
            jd_complete=(
                run_request.jd.complete
                if run_request.jd.complete is not None
                else bool(jd_text.strip())
            ),
            source_date=parsed_jd.published_date if parsed_jd else None,
        )
        target = _with_jd_metadata(target, parsed_jd, jd_origin)
        if target.target_basis == TargetBasis.INSUFFICIENT_TARGET and run_request.output_mode != OutputMode.MASTER_RESUME:
            choices = adapter.list_companies() if company is None else adapter.list_roles(company)
            raise SelectionRequired("Tier D requires a company/role selection unless master mode is requested", choices)
        requirements = (
            list(parsed_jd.requirements)
            if parsed_jd
            else _tier_b_requirements(adapter, company, role)
        )
        competencies = build_role_competencies(requirements)
        constraints = _application_constraints(
            parsed_jd.application_constraints if parsed_jd else (),
            run_request.application_constraints,
        )
        candidates = _load_verified_candidates(
            adapter,
            adapter.search_evidence(requirements),
        )
        records = [
            record
            for candidate in candidates
            if (
                record := build_evidence_record(
                    candidate,
                    candidate.requirement_ids,
                    mode=run_request.output_mode,
                )
            )
            is not None
        ]
        resume_candidates = _load_verified_candidates(
            adapter,
            adapter.search_evidence(
                [*requirements, *_resume_discovery_requirements()]
            ),
        )
        resume_records = [
            record
            for candidate in resume_candidates
            if (
                record := build_evidence_record(
                    candidate,
                    candidate.requirement_ids,
                    mode=run_request.output_mode,
                )
            )
            is not None
        ]
        mappings = build_evidence_mappings(
            requirements,
            candidates,
            mode=run_request.output_mode,
        )
        mappings = bind_experience_duration_diagnostics(
            mappings,
            requirements,
            records,
            run_request.experience_duration_diagnostics,
        )
        gaps = build_gaps(requirements, mappings)
        if target.target_basis == TargetBasis.EXACT_CURRENT_JD:
            explicit = [item for item in requirements if item.origin.value == "explicit"]
            covered = sum(1 for item in mappings if item.evidence_ids)
            denominator = len(explicit)
            target = target.model_copy(update={
                "explicit_requirement_coverage": (covered / denominator if denominator else 0.0),
                "coverage_calculation": {"covered_explicit_requirements": covered, "total_explicit_requirements": denominator, "calculation": "covered_explicit_requirements / total_explicit_requirements"},
            })
        recommendation = recommend_application(
            target,
            mappings,
            gaps,
            constraints,
            requirements=requirements,
            records=records,
        )
        interview_questions = [risk for mapping in mappings for risk in mapping.interview_risks]
        interview_questions.extend(f"How would you close gap {gap.gap_id}: {gap.reason}" for gap in gaps)
        dossier = RoleDossierIR(
            target_context=target, requirements=requirements, competencies=competencies,
            application_constraints=constraints, evidence_candidates=candidates,
            evidence_records=records, evidence_mappings=mappings, gaps=gaps,
            application_recommendation=recommendation,
            interview_questions=list(dict.fromkeys(interview_questions)),
            sources=_role_sources(
                manifest,
                company,
                role,
                jd_text,
                jd_origin,
                parsed_jd.source_url if parsed_jd else None,
            ),
            source_manifest=manifest,
            limitations=target.limitations,
        )
        run_dir = create_run_directory(
            output_root,
            company.company_id if company is not None else target.company,
            target.role,
        )
        role_dir = secure_directory(run_dir / "role-dossier", exist_ok=False)
        artifacts: list[Path] = []
        dossier_files = render_dossier_files(
            dossier,
            job_description=jd_text,
        )
        artifacts.extend(
            write_text(role_dir / name, dossier_files[name])
            for name in DOSSIER_FILES
        )
        artifacts.append(
            write_text(
                run_dir / "jd-snapshot.md",
                jd_text.rstrip() + ("\n" if jd_text else ""),
            )
        )
        questions = build_confirmation_questions(records, constraints)
        persisted_request = run_request.model_dump(
            mode="json",
            exclude_none=False,
        )
        persisted_request["jd"] = {
            "text": None,
            "url": None,
            "file": str(run_dir / "jd-snapshot.md") if jd_text else None,
        }
        shared_artifacts = {
            "run.json": {
                "schema_version": 1,
                "created_at": datetime.now(UTC),
                "request": persisted_request,
                "target_basis": target.target_basis,
                "run_id": run_dir.name,
            },
            "source-manifest.json": manifest,
            "target-context.json": target,
            "requirements.json": requirements,
            "competencies.json": competencies,
            "application-constraints.json": constraints,
            "evidence-map.json": mappings,
            "experience-duration-facts.json": _experience_duration_fact_index(records),
            "gaps.json": gaps,
            "application-recommendation.json": recommendation,
            "role-dossier-ir.json": _persistable_dossier(dossier),
        }
        for filename, value in shared_artifacts.items():
            artifacts.append(write_json(run_dir / filename, value))
        if run_request.export_roadmap_handoff:
            handoff = make_roadmap_handoff(
                gaps,
                explicitly_requested=True,
            )
            artifacts.append(
                write_json(run_dir / "roadmap-handoff.json", handoff)
            )
        artifacts.extend(
            [
                write_text(
                    run_dir / "confirmation-questions.md",
                    _questions_markdown(questions),
                ),
                write_text(
                    run_dir / "interview-questions.md",
                    _questions_markdown(dossier.interview_questions),
                ),
            ]
        )

        variant_manifest: list[dict[str, Any]] = []
        variant_summaries: dict[str, dict[str, Any]] = {}
        validation_errors: list[str] = []
        for spec in _requested_variant_specs(run_request):
            variant_template = _template_for_variant(
                run_request.template,
                spec.variant,
            )
            selected_records = _select_variant_records(
                adapter,
                resume_records,
                mappings,
                requirements,
                run_request.output_mode,
                spec,
            )
            profile = _candidate_profile(
                adapter,
                selected_records,
                resume_records,
                mappings,
                requirements,
                run_request.output_mode,
                spec,
            )
            document = build_resume_document(
                profile,
                target,
                selected_records,
                mappings,
                requirements,
                mode=run_request.output_mode,
                locale=run_request.language,
                variant=spec.variant,
                target_pages=spec.target_pages,
                minimum_pages=(
                    spec.target_pages
                    if len(selected_records) >= spec.target_pages * 6
                    else 1
                ),
                template=variant_template,
            )
            names = _variant_artifact_names(spec)
            pdf_result = render_with_compaction(
                document,
                run_dir / names["pdf"],
                inspection_config=_inspection_for_document(document),
                template=variant_template,
                preview_path=run_dir / names["preview"],
                compact=lambda current, report, attempt, current_spec=spec: (
                    _compact_overflowing_variant(
                        current,
                        report,
                        attempt,
                        current_spec,
                    )
                ),
                max_attempts=5,
                margin_mm=12.0,
            )
            final_document = pdf_result.document
            visible_claim_ids = _visible_claim_ids(final_document)
            provenance = build_provenance(
                selected_records,
                visible_claim_ids,
                mode=run_request.output_mode,
            )
            audit = audit_resume(
                final_document,
                selected_records,
                mappings,
                requirements,
                provenance,
                mode=run_request.output_mode,
            )
            artifacts.extend(
                [
                    write_json(
                        run_dir / names["document"],
                        final_document,
                    ),
                    write_json(
                        run_dir / names["provenance"],
                        provenance,
                    ),
                    write_json(
                        run_dir / names["validation"],
                        audit,
                    ),
                    write_text(
                        run_dir / names["audit"],
                        _audit_markdown(audit, target),
                    ),
                    write_text(
                        run_dir / names["markdown"],
                        render_targeted_markdown(final_document),
                    ),
                    write_text(
                        run_dir / names["ats_text"],
                        render_ats_text(final_document),
                    ),
                    write_text(
                        run_dir / names["html"],
                        render_html(final_document, variant_template),
                    ),
                    Path(pdf_result.pdf_path),
                    *(Path(path) for path in pdf_result.preview_paths),
                ]
            )
            pdf_validation = pdf_result.validation
            pdf_success = bool(
                pdf_validation is not None
                and pdf_validation.success
            )
            variant_key = spec.variant.value
            variant_summaries[variant_key] = {
                "audit_success": audit.success,
                "pdf_success": pdf_success,
                "pages": (
                    pdf_validation.pages
                    if pdf_validation is not None
                    else None
                ),
                "visible_claims": len(visible_claim_ids),
            }
            variant_manifest.append(
                {
                    "variant": variant_key,
                    "base_name": spec.base_name,
                    "template": variant_template,
                    "target_pages": spec.target_pages,
                    "actual_pages": (
                        pdf_validation.pages
                        if pdf_validation is not None
                        else None
                    ),
                    "underfilled": (
                        len(visible_claim_ids) < spec.target_pages * 6
                    ),
                    "visible_claims": len(visible_claim_ids),
                    "audit_success": audit.success,
                    "pdf_success": pdf_success,
                    "artifacts": {
                        key: value
                        for key, value in names.items()
                        if key != "preview"
                    },
                    "previews": [
                        Path(path).name
                        for path in pdf_result.preview_paths
                    ],
                }
            )
            if not audit.success:
                validation_errors.extend(
                    f"[{variant_key}] {error}"
                    for error in audit.errors
                )
            if not pdf_success and pdf_validation is not None:
                validation_errors.extend(
                    f"[{variant_key}] {error}"
                    for error in pdf_validation.errors
                )
        artifacts.append(
            write_json(
                run_dir / "resume-variants.json",
                {
                    "schema_version": 1,
                    "variants": variant_manifest,
                },
            )
        )
        for path in artifacts:
            if path.exists():
                path.chmod(0o600)
        if validation_errors:
            raise PipelineError(
                f"run retained at {run_dir}; validation failed: "
                + "; ".join(validation_errors)
            )
        return PipelineResult(
            "generate",
            run_dir,
            tuple(dict.fromkeys(artifacts)),
            {
                "target_basis": target.target_basis.value,
                "application_decision": recommendation.decision.value,
                "variants": variant_summaries,
                "limitations": target.limitations,
            },
        )

    def analyze_role(self, request: RunRequest | Mapping[str, Any]) -> PipelineResult:
        result = self.generate(request)
        return PipelineResult("analyze-role", result.run_dir, result.artifacts, result.summary)

    def build_evidence_map(self, run: str | Path) -> PipelineResult:
        run_dir = Path(run).resolve(strict=True)
        request = RunRequest.model_validate(read_json(run_dir / "run.json")["request"])
        adapter = self._adapter(request.source_root)
        requirements = [Requirement.model_validate(item) for item in read_json(run_dir / "requirements.json")]
        candidates = _load_verified_candidates(adapter, adapter.search_evidence(requirements))
        records = [
            record
            for candidate in candidates
            if (
                record := build_evidence_record(
                    candidate,
                    candidate.requirement_ids,
                    mode=request.output_mode,
                )
            )
            is not None
        ]
        mappings = build_evidence_mappings(requirements, candidates, mode=request.output_mode)
        mappings = bind_experience_duration_diagnostics(
            mappings,
            requirements,
            records,
            request.experience_duration_diagnostics,
        )
        mapping_path = write_json(run_dir / "evidence-map.json", mappings)
        duration_path = write_json(
            run_dir / "experience-duration-facts.json",
            _experience_duration_fact_index(records),
        )
        return PipelineResult(
            "build-evidence-map",
            run_dir,
            (mapping_path, duration_path),
            {"requirements": len(requirements), "mappings": len(mappings)},
        )

    def validate_content(self, run: str | Path) -> PipelineResult:
        from .models import (
            EvidenceMapping,
            ProvenanceRecord,
            Requirement,
            ResumeDocument,
        )
        run_dir = Path(run).resolve(strict=True)
        requirements = [
            Requirement.model_validate(item)
            for item in read_json(run_dir / "requirements.json")
        ]
        request = RunRequest.model_validate(
            read_json(run_dir / "run.json")["request"]
        )
        adapter = self._adapter(request.source_root)
        candidates = _load_verified_candidates(
            adapter,
            adapter.search_evidence(
                [*requirements, *_resume_discovery_requirements()]
            ),
        )
        records = [
            record
            for candidate in candidates
            if (
                record := build_evidence_record(
                    candidate,
                    candidate.requirement_ids,
                    mode=request.output_mode,
                )
            )
            is not None
        ]
        mappings = [
            EvidenceMapping.model_validate(item)
            for item in read_json(run_dir / "evidence-map.json")
        ]
        manifest = read_json(run_dir / "resume-variants.json")
        artifacts: list[Path] = []
        errors: list[str] = []
        warnings: list[str] = []
        variants: dict[str, bool] = {}
        for entry in manifest.get("variants", []):
            variant = str(entry["variant"])
            names = entry["artifacts"]
            document = ResumeDocument.model_validate(
                read_json(run_dir / names["document"])
            )
            provenance = [
                ProvenanceRecord.model_validate(item)
                for item in read_json(run_dir / names["provenance"])
            ]
            report = audit_resume(
                document,
                records,
                mappings,
                requirements,
                provenance,
                mode=request.output_mode,
            )
            path = write_json(
                run_dir / names["validation"],
                report,
            )
            artifacts.append(path)
            variants[variant] = report.success
            errors.extend(f"[{variant}] {error}" for error in report.errors)
            warnings.extend(
                f"[{variant}] {warning}" for warning in report.warnings
            )
        success = bool(variants) and all(variants.values())
        return PipelineResult(
            "validate-content",
            run_dir,
            tuple(artifacts),
            {
                "success": success,
                "variants": variants,
                "errors": errors,
                "warnings": warnings,
            },
        )

    def render(
        self,
        document_path: str | Path,
        output: str | Path | None = None,
    ) -> PipelineResult:
        from .models import ResumeDocument
        document_file = Path(document_path).resolve(strict=True)
        document = ResumeDocument.model_validate(read_json(document_file))
        default_name = (
            document_file.name.removesuffix(".document.json") + ".pdf"
            if document_file.name.endswith(".document.json")
            else document_file.with_suffix(".pdf").name
        )
        destination = (
            Path(output).expanduser().resolve(strict=False)
            if output
            else document_file.with_name(default_name)
        )
        run_manifest = document_file.parent / "run.json"
        if run_manifest.is_file():
            source_root = RunRequest.model_validate(
                read_json(run_manifest)["request"]
            ).source_root
            validate_output_root(source_root, destination.parent)
        secure_directory(destination.parent)
        result = render_with_compaction(
            document,
            destination,
            inspection_config=_inspection_for_document(document),
            template=document.render_policy.template,
            preview_path=destination.with_name(
                destination.stem + ".preview.png"
            ),
            max_attempts=1,
        )
        paths = (
            Path(result.pdf_path),
            *(Path(path) for path in result.preview_paths),
        )
        for path in paths:
            path.chmod(0o600)
        return PipelineResult(
            "render",
            destination.parent,
            paths,
            {
                "success": result.validation.success,
                "attempts": result.attempts,
            },
        )

    def inspect_pdf(
        self,
        pdf: str | Path,
        *,
        max_pages: int = 2,
        expected_name: str = "",
        document: str | Path | None = None,
    ) -> PipelineResult:
        path = Path(pdf).resolve(strict=True)
        if document is not None:
            from .models import ResumeDocument

            document_path = Path(document).resolve(strict=True)
            resume_document = ResumeDocument.model_validate(read_json(document_path))
            config = _inspection_for_document(resume_document)
        else:
            config = InspectionConfig(
                target_pages=max_pages,
                expected_name=expected_name,
            )
        report = inspect_pdf_file(path, config)
        return PipelineResult(
            "inspect-pdf",
            path.parent,
            (),
            report.model_dump(mode="json", exclude_none=True),
        )

    def export_roadmap_handoff(self, role: str | Path, output: str | Path, severities: Sequence[str]) -> PipelineResult:
        from .models import Gap
        base = Path(role).resolve(strict=True)
        run_dir = base.parent if base.name == "role-dossier" else base
        request = RunRequest.model_validate(read_json(run_dir / "run.json")["request"])
        validate_output_root(request.source_root, Path(output).expanduser().resolve(strict=False).parent)
        gaps = [Gap.model_validate(item) for item in read_json(run_dir / "gaps.json")]
        selected = [gap for gap in gaps if gap.severity is not None and gap.severity.value in severities]
        handoff = make_roadmap_handoff(selected, explicitly_requested=True, severities=severities)
        path = write_json(Path(output), handoff)
        return PipelineResult("export-roadmap-handoff", run_dir, (path,), {"items": len(handoff)})

    def refresh_match(self, role: str | Path) -> PipelineResult:
        from .models import EvidenceMapping
        base = Path(role).resolve(strict=True)
        run_dir = base.parent if base.name == "role-dossier" else base
        request = RunRequest.model_validate(read_json(run_dir / "run.json")["request"])
        adapter = self._adapter(request.source_root)
        requirements = [Requirement.model_validate(item) for item in read_json(run_dir / "requirements.json")]
        prior = [EvidenceMapping.model_validate(item) for item in read_json(run_dir / "evidence-map.json")]
        old_manifest = read_json(run_dir / "source-manifest.json")
        old_hashes = {
            (item.get("source_path"), item.get("section_anchor")): item.get("source_hash")
            for item in old_manifest.get("sections", [])
        }
        changed = {
            section.source_hash
            for section in adapter.manifest.sections
            if old_hashes.get((section.source_path, section.section_anchor)) != section.source_hash
        }
        candidates = _load_verified_candidates(adapter, adapter.search_evidence(requirements))
        records = [record for candidate in candidates if (record := build_evidence_record(candidate, candidate.requirement_ids, mode=request.output_mode))]
        result = refresh_evidence_match(prior, requirements, records, changed)
        path = write_json(run_dir / "evidence-map.json", result.mappings)
        duration_path = write_json(
            run_dir / "experience-duration-facts.json",
            _experience_duration_fact_index(records),
        )
        manifest_path = write_json(run_dir / "source-manifest.json", adapter.manifest)
        return PipelineResult(
            "refresh-match",
            run_dir,
            (path, duration_path, manifest_path),
            result.model_dump(mode="json"),
        )

    def refresh_role(self, role: str | Path) -> PipelineResult:
        base = Path(role).resolve(strict=True)
        run_dir = base.parent if base.name == "role-dossier" else base
        role_dir = run_dir / "role-dossier"
        request = RunRequest.model_validate(read_json(run_dir / "run.json")["request"])
        old_dossier = RoleDossierIR.model_validate(
            read_json(run_dir / "role-dossier-ir.json")
        )
        adapter = self._adapter(request.source_root)
        manifest = adapter.manifest
        company = _match_company(adapter, request.company_ref)
        role_ref = _match_role(adapter, company, request.role_ref)
        jd_text, jd_origin = _load_jd(request.jd)
        role_request = RoleRequest(
            company_ref=company,
            role_ref=role_ref,
            jd=JdInput(text=jd_text or None),
        )
        parsed = parse_job_description(jd_text) if jd_text.strip() else None
        hiring_evidence = (
            adapter.load_company(company).values() if company and not jd_text else ()
        )
        target = resolve_target(
            role_request,
            jd_text=jd_text or None,
            hiring_evidence=hiring_evidence,
            jd_complete=(
                request.jd.complete
                if request.jd.complete is not None
                else bool(jd_text.strip())
            ),
            source_date=parsed.published_date if parsed else None,
        )
        target = _with_jd_metadata(target, parsed, jd_origin)
        requirements = (
            list(parsed.requirements)
            if parsed
            else _tier_b_requirements(adapter, company, role_ref)
        )
        competencies = build_role_competencies(requirements)
        constraints = _application_constraints(
            parsed.application_constraints if parsed else (),
            request.application_constraints,
        )
        candidates = _load_verified_candidates(
            adapter, adapter.search_evidence(requirements)
        )
        records = [
            record
            for candidate in candidates
            if (
                record := build_evidence_record(
                    candidate,
                    candidate.requirement_ids,
                    mode=request.output_mode,
                )
            )
            is not None
        ]
        mappings = build_evidence_mappings(
            requirements, candidates, mode=request.output_mode
        )
        mappings = bind_experience_duration_diagnostics(
            mappings,
            requirements,
            records,
            request.experience_duration_diagnostics,
        )
        gaps = build_gaps(requirements, mappings)
        if target.target_basis == TargetBasis.EXACT_CURRENT_JD:
            denominator = len(
                [item for item in requirements if item.origin.value == "explicit"]
            )
            covered = sum(1 for item in mappings if item.evidence_ids)
            target = target.model_copy(update={
                "explicit_requirement_coverage": (
                    covered / denominator if denominator else 0.0
                ),
                "coverage_calculation": {
                    "covered_explicit_requirements": covered,
                    "total_explicit_requirements": denominator,
                    "calculation": (
                        "covered_explicit_requirements / "
                        "total_explicit_requirements"
                    ),
                },
            })
        recommendation = recommend_application(
            target,
            mappings,
            gaps,
            constraints,
            requirements=requirements,
            records=records,
        )
        interview_questions = [
            risk for mapping in mappings for risk in mapping.interview_risks
        ]
        interview_questions.extend(
            f"How would you close gap {gap.gap_id}: {gap.reason}" for gap in gaps
        )
        new_dossier = RoleDossierIR(
            target_context=target,
            requirements=requirements,
            competencies=competencies,
            application_constraints=constraints,
            evidence_candidates=candidates,
            evidence_records=records,
            evidence_mappings=mappings,
            gaps=gaps,
            application_recommendation=recommendation,
            interview_questions=list(dict.fromkeys(interview_questions)),
            sources=_role_sources(
                manifest,
                company,
                role_ref,
                jd_text,
                jd_origin,
                parsed.source_url if parsed else None,
            ),
            source_manifest=manifest,
            limitations=target.limitations,
        )
        changed = refresh_role_sections(old_dossier, new_dossier)
        owners = {
            "requirements": ("requirement-analysis.md",),
            "competencies": ("competency-model.md",),
            "anomalies": ("requirement-analysis.md", "sources.md"),
        }
        by_file: dict[str, list[str]] = {}
        for section in changed:
            for filename in owners[section]:
                by_file.setdefault(filename, []).append(section)
        artifacts: list[Path] = []
        for filename, sections in by_file.items():
            path = role_dir / filename
            text = path.read_text(encoding="utf-8")
            for section in sections:
                text = _replace_owned_section(text, section, changed[section])
            artifacts.append(write_text(path, text))
        state = {
            "role-dossier-ir.json": _persistable_dossier(new_dossier),
            "source-manifest.json": manifest,
            "target-context.json": target,
            "requirements.json": requirements,
            "competencies.json": competencies,
            "application-constraints.json": constraints,
        }
        for filename, value in state.items():
            artifacts.append(write_json(run_dir / filename, value))
        return PipelineResult(
            "refresh-role",
            run_dir,
            tuple(artifacts),
            {
                "changed_sections": sorted(changed),
                "preserved_unowned_content": True,
            },
        )


def generate(request: RunRequest | Mapping[str, Any]) -> PipelineResult:
    return Pipeline().generate(request)
def discover_source_structure(
    source: str | Path,
    *,
    output: str | Path | None = None,
) -> Any:
    return Pipeline().discover_source_structure(source, output=output)


def validate_source_map(
    source: str | Path,
    source_map: Mapping[str, Any] | Any,
    *,
    output: str | Path | None = None,
) -> Any:
    return Pipeline().validate_source_map(source, source_map, output=output)


def validate_role_input(
    value: Mapping[str, Any] | Any,
    *,
    source: str | Path | None = None,
    output: str | Path | None = None,
) -> Any:
    return Pipeline().validate_role_input(value, source=source, output=output)


def validate_evidence_input(
    value: Mapping[str, Any] | Any,
    *,
    source: str | Path | None = None,
    output: str | Path | None = None,
) -> Any:
    return Pipeline().validate_evidence_input(value, source=source, output=output)


def approve_claims(
    value: Mapping[str, Any] | Any,
    *,
    source: str | Path | None = None,
    output: str | Path | None = None,
) -> Any:
    return Pipeline().approve_claims(value, source=source, output=output)


def generate_from_ir(
    value: Mapping[str, Any] | Any,
    *,
    source: str | Path | None = None,
    output_root: str | Path | None = None,
    output: str | Path | None = None,
    include_extended_profile: bool | None = None,
) -> PipelineResult:
    return Pipeline().generate_from_ir(
        value,
        source=source,
        output_root=output_root,
        output=output,
        include_extended_profile=include_extended_profile,
    )


def analyze_role(request: RunRequest | Mapping[str, Any]) -> PipelineResult:
    return Pipeline().analyze_role(request)


def build_evidence_map(run: str | Path) -> PipelineResult:
    return Pipeline().build_evidence_map(run)


def validate_content(run: str | Path) -> PipelineResult:
    return Pipeline().validate_content(run)


def render(document: str | Path, output: str | Path | None = None) -> PipelineResult:
    return Pipeline().render(document, output)


def inspect_pdf(
    pdf: str | Path,
    *,
    max_pages: int = 2,
    expected_name: str = "",
    document: str | Path | None = None,
) -> PipelineResult:
    return Pipeline().inspect_pdf(
        pdf,
        max_pages=max_pages,
        expected_name=expected_name,
        document=document,
    )


def list_companies(source: str | Path) -> list[CompanyRef]:
    return Pipeline().list_companies(source)


def list_roles(source: str | Path, company: str) -> list[RoleRef]:
    return Pipeline().list_roles(source, company)


def refresh_role(role: str | Path) -> PipelineResult:
    return Pipeline().refresh_role(role)


def refresh_match(role: str | Path) -> PipelineResult:
    return Pipeline().refresh_match(role)


def export_roadmap_handoff(role: str | Path, output: str | Path, severities: Sequence[str] = ("Critical", "Major")) -> PipelineResult:
    return Pipeline().export_roadmap_handoff(role, output, severities)
