"""Deterministic orchestration for targeted-resume runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import re
from pathlib import Path
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
)
from .dossier import DOSSIER_FILES, refresh_role as refresh_role_sections, render_dossier_files
from .evidence import build_evidence_map as build_evidence_mappings, build_evidence_record, refresh_match as refresh_evidence_match
from .gaps import build_gaps
from .io import create_run_directory, jsonable, read_json, secure_directory, validate_output_root, write_json, write_text
from .models import (
    CompanyRef, JdInput, OutputMode, Requirement, ResumeVariant,
    RoleDossierIR, RoleRef, RoleRequest, RunRequest, SourceRef, TargetBasis,
    TargetContext,
)
from .provenance import build_confirmation_questions, build_provenance
from .roadmap_handoff import export_roadmap_handoff as make_roadmap_handoff
from .requirements import make_inferred_requirement
from .target_resolution import resolve_target
from .rendering.html import render_html
from .rendering.inspect import InspectionConfig, inspect_pdf as inspect_pdf_file
from .rendering.pdf import render_with_compaction

_MAX_JD_BYTES = 2 * 1024 * 1024
_KNOWN_SKILLS = (
    "Megatron-LM", "Distributed systems", "Incident response", "TypeScript",
    "JavaScript", "PostgreSQL", "Kubernetes", "TensorFlow", "DeepSpeed",
    "Prometheus", "Networking", "PyTorch", "Python", "Docker", "Linux",
    "Grafana", "MySQL", "Redis", "gRPC", "ROS 2", "CUDA", "FSDP",
    "DDP", "GPU", "HTTP", "API", "CI/CD", "C++", "C#", "Rust", "Java",
    "JAX", "Go", "Terraform", "Coder", "Docker Swarm", "Flask",
    "SQLAlchemy", "CMake", "vcpkg", "Electron", "Vue", "tree-sitter",
    "CTags", "WebSocket", "NETCONF",
)



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
    text = _seed_text(adapter, source_path)
    headings = list(
        re.finditer(
            r"^###\s+(?:阶段|stage\b).+$",
            text,
            re.M | re.I,
        )
    )
    ranges: list[tuple[int, int]] = []
    for index, heading in enumerate(headings):
        start_line = text.count("\n", 0, heading.start()) + 1
        end_offset = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else len(text)
        )
        end_line = text.count("\n", 0, end_offset) + 1
        ranges.append((start_line, end_line))
    return ranges


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
        include_unmapped=True,
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


def _seed_text(adapter: MarkdownCareerV1Adapter, relative: str) -> str:
    if relative not in set(adapter.manifest.documents):
        return ""
    path = (adapter.root / relative).resolve(strict=True)
    if not path.is_relative_to(adapter.root) or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


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
    text = _seed_text(adapter, relative)
    fields = {
        _normalized_field_key(key): value.strip()
        for key, value in re.findall(
            r"^-\s*(?:\*\*)?([^:*：]+?)(?:\*\*)?\s*[:：]\s*(.+?)\s*$",
            text,
            flags=re.M,
        )
    }
    if relative in set(adapter.manifest.documents):
        for table in adapter.parse_pipe_tables(relative):
            for row in table["rows"][1:]:
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    fields[_normalized_field_key(_plain_markdown_value(row[0]))] = row[1].strip()
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
    text = _seed_text(adapter, relative)
    links = [
        {"label": label, "url": url, "source_refs": [relative]}
        for label, url in re.findall(
            r"^-\s*Active,\s*P0:\s*\[([^]]+)\]\((https://[^)]+)\)",
            text,
            flags=re.M | re.I,
        )
    ]
    if relative in set(adapter.manifest.documents):
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
    text = _seed_text(adapter, relative)
    education: list[dict[str, Any]] = []
    legacy = re.search(
        r"^-\s*([^,]+),\s*([^,]+),\s*(\d{4}-\d{2})\s+to\s+(\d{4}-\d{2});\s*F[12],\s*P[012]\.",
        text,
        flags=re.M,
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
    honors = [
        {
            "name": name.strip(),
            "date": year,
            "source_refs": [relative],
        }
        for name, year in re.findall(
            r"^-\s*([^;]+),\s*(\d{4});\s*F[12],\s*P[012]\.",
            text,
            flags=re.M,
        )
    ][:2]
    if not honors:
        honors = [
            {
                "name": title.strip(),
                "date": year,
                "source_refs": [relative],
            }
            for title, year in re.findall(
                r"^###\s+(.+?)\s*[（(](\d{4})[)）]\s*$",
                text,
                flags=re.M,
            )
        ][:2]
    return education, honors


def _work_stage_metadata(
    adapter: MarkdownCareerV1Adapter,
    source_path: str,
) -> list[dict[str, Any]]:
    text = _seed_text(adapter, source_path)
    headings = list(
        re.finditer(
            r"^###\s+((?:阶段|stage\b).+)$",
            text,
            re.M | re.I,
        )
    )
    stages: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        end_offset = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else len(text)
        )
        chunk = text[heading.end() : end_offset]
        period_match = re.search(r"^\s*\*\*([^*\n]+)\*\*", chunk, re.M)
        start_date, end_date = (
            _split_period(period_match.group(1))
            if period_match is not None
            else ("", "")
        )
        heading_text = _plain_markdown_value(heading.group(1))
        role = re.split(r"[:：]", heading_text, maxsplit=1)[-1].strip()
        stages.append(
            {
                "start_line": text.count("\n", 0, heading.start()) + 1,
                "end_line": text.count("\n", 0, end_offset) + 1,
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
        evidence_text = " ".join(
            record.safe_claim for record in linked_records
        ).casefold()
        requirement_text = requirement.text.casefold()
        candidates = [
            *requirement.keywords,
            *(skill for skill in _KNOWN_SKILLS if skill.casefold() in requirement_text),
        ]
        for candidate in candidates:
            skill = str(candidate).strip()
            if not skill or skill.casefold() not in evidence_text:
                continue
            key = skill.casefold()
            entry = skill_index.setdefault(key, {
                "text": skill,
                "evidence_ids": [],
                "source_refs": [],
            })
            entry["evidence_ids"].extend(
                record.evidence_id for record in linked_records
            )
            entry["source_refs"].extend(
                str(record.source.path)
                for record in linked_records
                if record.source.path
            )
    for record in records:
        claim = record.safe_claim.casefold()
        for skill in _KNOWN_SKILLS:
            if skill.casefold() not in claim:
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




_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
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


def _role_evidence_subsections(section: list[str]) -> list[str]:
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(section):
        match = _MARKDOWN_HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2)))
    selected: list[str] = []
    for position, (start, level, title) in enumerate(headings[1:], 1):
        if not _ROLE_EVIDENCE_HEADING_RE.search(title):
            continue
        end = len(section)
        for next_start, next_level, _ in headings[position + 1:]:
            if next_level <= level:
                end = next_start
                break
        selected.append("\n".join(section[start:end]).strip())
    return [item for item in selected if item]


def _role_hiring_scopes(text: str, role: RoleRef) -> list[str]:
    lines = text.splitlines()
    role_title = _normalize_role_label(role.title)
    exact_sections: list[str] = []
    for start, line in enumerate(lines):
        heading = _MARKDOWN_HEADING_RE.match(line)
        if not heading or role_title not in _normalize_role_label(heading.group(2)):
            continue
        level = len(heading.group(1))
        end = len(lines)
        for index in range(start + 1, len(lines)):
            next_heading = _MARKDOWN_HEADING_RE.match(lines[index])
            if next_heading and len(next_heading.group(1)) <= level:
                end = index
                break
        section = lines[start:end]
        exact_sections.extend(
            _role_evidence_subsections(section) or ["\n".join(section).strip()]
        )
    if exact_sections:
        return list(dict.fromkeys(item for item in exact_sections if item))

    variants = _role_label_variants(role.title)
    scoped_lines: list[str] = []
    for line in lines:
        labeled = re.match(
            r"^\s*[-*•]\s+(?:\*\*)?(.{1,80}?)(?:\*\*)?\s*[:：]\s*(.+?)\s*$",
            line,
        )
        if labeled and _normalize_role_label(labeled.group(1)) in variants:
            scoped_lines.append(line.strip())
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if any(_normalize_role_label(cell) in variants for cell in cells):
            scoped_lines.append("- " + " — ".join(cells))
    return list(dict.fromkeys(scoped_lines))


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




def _tier_b_requirements(
    adapter: MarkdownCareerV1Adapter,
    company: CompanyRef | None,
    role: RoleRef | None,
) -> list[Requirement]:
    sources: dict[str, str] = {}
    if role is not None:
        for ref in role.source_refs:
            path = re.split(r"#|:L\d+", ref, maxsplit=1)[0]
            if path.endswith("roles-and-hiring.md"):
                text = _seed_text(adapter, path)
                if text:
                    sources.setdefault(path, text)
            role_dir = Path(path).parent
            jd_path = (role_dir / "job-description.md").as_posix()
            text = _seed_text(adapter, jd_path)
            if text:
                sources.setdefault(jd_path, text)
    if company is not None:
        for path, text in adapter.load_company(company).items():
            if path.endswith("roles-and-hiring.md"):
                sources.setdefault(path, text)
    inferred: list[Requirement] = []
    seen: set[str] = set()
    for source_ref, text in sources.items():
        scopes = (
            _role_hiring_scopes(text, role)
            if role is not None and source_ref.endswith("roles-and-hiring.md")
            else [text]
        )
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
    headings = tuple(
        label
        for field, label in (
            ("summary", "Summary"),
            ("skills", "Skills"),
            ("experience", "Experience"),
            ("projects", "Projects"),
            ("education", "Education"),
            ("honors", "Honors"),
        )
        if getattr(document, field)
    )
    return headings + (("Links",) if document.contact.links else ())


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


class Pipeline:
    """Compose existing domain functions without reproducing their policy rules."""

    def __init__(self, adapter_factory: Any = MarkdownCareerV1Adapter) -> None:
        self._adapter_factory = adapter_factory

    def _adapter(self, source: Path) -> MarkdownCareerV1Adapter:
        return self._adapter_factory(source)

    def list_companies(self, source: str | Path) -> list[CompanyRef]:
        return self._adapter(Path(source)).list_companies()

    def list_roles(self, source: str | Path, company: str) -> list[RoleRef]:
        adapter = self._adapter(Path(source))
        return adapter.list_roles(_match_company(adapter, company))

    def generate(self, request: RunRequest | Mapping[str, Any]) -> PipelineResult:
        run_request = request if isinstance(request, RunRequest) else RunRequest.model_validate(request)
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
            jd_complete=bool(jd_text.strip()),
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
        constraints = list(parsed_jd.application_constraints) if parsed_jd else []
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
        gaps = build_gaps(requirements, mappings)
        if target.target_basis == TargetBasis.EXACT_CURRENT_JD:
            explicit = [item for item in requirements if item.origin.value == "explicit"]
            covered = sum(1 for item in mappings if item.evidence_ids)
            denominator = len(explicit)
            target = target.model_copy(update={
                "explicit_requirement_coverage": (covered / denominator if denominator else 0.0),
                "coverage_calculation": {"covered_explicit_requirements": covered, "total_explicit_requirements": denominator, "calculation": "covered_explicit_requirements / total_explicit_requirements"},
            })
        recommendation = recommend_application(target, mappings, gaps, constraints)
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
                template=run_request.template,
            )
            names = _variant_artifact_names(spec)
            pdf_result = render_with_compaction(
                document,
                run_dir / names["pdf"],
                inspection_config=_inspection_for_document(document),
                template=run_request.template,
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
                        render_html(final_document, run_request.template),
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
        mappings = build_evidence_mappings(requirements, candidates, mode=request.output_mode)
        path = write_json(run_dir / "evidence-map.json", mappings)
        return PipelineResult("build-evidence-map", run_dir, (path,), {"requirements": len(requirements), "mappings": len(mappings)})

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
    ) -> PipelineResult:
        path = Path(pdf).resolve(strict=True)
        report = inspect_pdf_file(
            path,
            InspectionConfig(
                target_pages=max_pages,
                expected_name=expected_name,
            ),
        )
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
        manifest_path = write_json(run_dir / "source-manifest.json", adapter.manifest)
        return PipelineResult("refresh-match", run_dir, (path, manifest_path), result.model_dump(mode="json"))

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
            jd_complete=bool(jd_text.strip()),
            source_date=parsed.published_date if parsed else None,
        )
        target = _with_jd_metadata(target, parsed, jd_origin)
        requirements = (
            list(parsed.requirements)
            if parsed
            else _tier_b_requirements(adapter, company, role_ref)
        )
        competencies = build_role_competencies(requirements)
        constraints = list(parsed.application_constraints) if parsed else []
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
            target, mappings, gaps, constraints
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
) -> PipelineResult:
    return Pipeline().inspect_pdf(
        pdf,
        max_pages=max_pages,
        expected_name=expected_name,
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
