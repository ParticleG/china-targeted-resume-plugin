from __future__ import annotations

import json
from pathlib import Path

import pytest

from china_targeted_resume.adapters.markdown_career_v1 import (
    MarkdownCareerV1Adapter,
    SourceBoundaryError,
)
from china_targeted_resume.models import (
    DisclosureLevel,
    EvidenceMapping,
    EvidenceRecord,
    FactState,
    Freshness,
    OutputMode,
    RoleMatchState,
    SourceRef,
    SourceSpan,
)
from china_targeted_resume.pipeline import (
    _RECRUITER_ONE_PAGE,
    _TECHNICAL_TWO_PAGE,
    _candidate_profile,
    _deduplicate_candidates,
    _timeline_rows,
)


def _remove_documented_traversal(root: Path) -> None:
    path = root / "personal-data" / "meta" / "public-links.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(line for line in text.splitlines() if "../../../../outside-secret.md" not in line) + "\n",
        encoding="utf-8",
    )


def test_discovery_rejects_documented_traversal_before_indexing(synthetic_db_copy: Path) -> None:
    adapter = MarkdownCareerV1Adapter()

    with pytest.raises(SourceBoundaryError, match="traversal|absolute|escapes"):
        adapter.discover(synthetic_db_copy)


def test_discovery_rejects_symlink_escape(synthetic_db_copy: Path, tmp_path: Path) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    outside = tmp_path / "synthetic-outside-source.md"
    outside.write_text("# Synthetic outside source\n\nNo personal data.\n", encoding="utf-8")
    link = synthetic_db_copy / "personal-data" / "meta" / "escape-link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("filesystem does not support symlinks")

    with pytest.raises(SourceBoundaryError, match="symlink escapes"):
        MarkdownCareerV1Adapter(synthetic_db_copy)


def test_public_path_reader_rejects_parent_escape(synthetic_db_copy: Path) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)

    with pytest.raises(SourceBoundaryError, match="traversal|absolute"):
        adapter.parse_pipe_tables("../synthetic-outside.md")


def test_manifest_is_navigation_only_and_excludes_section_text_and_secrets(
    synthetic_db_copy: Path,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    manifest = MarkdownCareerV1Adapter(synthetic_db_copy).manifest
    serialized = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False)

    assert manifest.adapter == "markdown-career-v1"
    assert manifest.documents == sorted(manifest.documents)
    assert manifest.sections
    assert all(section.source_path in manifest.documents for section in manifest.sections)
    assert "Avery Quill" not in serialized
    assert "avery.quill@career-fixture.invalid" not in serialized
    assert "TOKEN-FICTIONAL-DO-NOT-USE-7QX" not in serialized
    assert "LICENSE_BLOB-FICTIONAL-9X9" not in serialized
    assert "Reduced all incidents by 90%" not in serialized
    assert not ({"body", "text", "content", "snippet"} & manifest.sections[0].model_dump().keys())


def test_company_and_domain_category_discovery_is_exact(synthetic_db_copy: Path) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)

    companies = adapter.list_companies()
    domains = {section.domain for section in adapter.manifest.sections}
    company_files = adapter.load_company("acme-cloudworks")

    assert [(company.company_id, company.display_name) for company in companies] == [
        ("acme-cloudworks", "Acme Cloudworks"),
        ("clockwork-capybara-robotics", "Clockwork Capybara Robotics"),
    ]
    assert domains == {
        "repository-navigation",
        "personal-data",
        "company-research",
        "role-research",
        "growth-roadmap",
    }
    assert set(company_files) == {
        "company-research/acme-cloudworks/README.md",
        "company-research/acme-cloudworks/business-and-products.md",
        "company-research/acme-cloudworks/organization-and-culture.md",
        "company-research/acme-cloudworks/overview.md",
        "company-research/acme-cloudworks/risks-and-open-questions.md",
        "company-research/acme-cloudworks/roles-and-hiring.md",
        "company-research/acme-cloudworks/sources.md",
        "company-research/acme-cloudworks/technology-and-engineering.md",
    }
    assert all(not ref.startswith("personal-data/") for company in companies for ref in company.source_refs)


def test_heading_table_and_link_role_styles_are_parsed_without_conflation(
    synthetic_db_copy: Path,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    hiring = synthetic_db_copy / "company-research" / "acme-cloudworks" / "roles-and-hiring.md"
    hiring.write_text(
        hiring.read_text(encoding="utf-8")
        + """

## Additional synthetic openings

| Role | Category | Detail |
|---|---|---|
| [Reliability Engineer](../../role-research/README.md) | Infrastructure | linked navigation row |
| Data Platform Engineer | Data | plain table row |
""",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)

    tables = adapter.parse_pipe_tables("company-research/acme-cloudworks/roles-and-hiring.md")
    roles = adapter.list_roles("acme-cloudworks")
    by_id = {role.role_id: role for role in roles}

    assert tables[-1]["rows"][0] == ["Role", "Category", "Detail"]
    assert tables[-1]["rows"][1][0].startswith("[Reliability Engineer]")
    assert by_id["acme-cloudworks-platform-engineer"].title.startswith("Platform Engineer")
    assert by_id["acme-cloudworks-reliability-engineer"].title == "Reliability Engineer"
    assert by_id["acme-cloudworks-data-platform-engineer"].title == "Data Platform Engineer"
    assert by_id["acme-cloudworks-reliability-engineer"].source_refs[0].startswith(
        "company-research/acme-cloudworks/roles-and-hiring.md:L"
    )


def test_evidence_search_is_isolated_to_personal_navigation_sections(
    synthetic_db_copy: Path, requirement_factory
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    requirement = requirement_factory(
        text="Operate distributed queue services",
        verbatim_quote="Operate distributed queue services",
        keywords=["queue", "service"],
    )

    candidates = adapter.search_evidence([requirement])

    assert candidates
    assert all(candidate.source.path.startswith("personal-data/") for candidate in candidates)
    assert all(candidate.body is not None for candidate in candidates)
    persisted = json.dumps(
        [candidate.model_dump(mode="json") for candidate in candidates], ensure_ascii=False
    )
    assert "TOKEN-FICTIONAL-DO-NOT-USE-7QX" not in persisted
    assert "LICENSE_BLOB-FICTIONAL-9X9" not in persisted
    assert "body" not in persisted
    assert "snippet" not in persisted
    assert "company-research/" not in persisted
    assert "growth-roadmap/" not in persisted


def test_resume_discovery_can_retrieve_source_backed_project_context(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    discovery = requirement_factory(
        text="bounded retries visible delivery state",
        verbatim_quote="bounded retries visible delivery state",
        keywords=["bounded retries", "delivery state"],
        category="resume-discovery",
    )
    role_requirement = requirement_factory(
        text="bounded retries visible delivery state",
        verbatim_quote="bounded retries visible delivery state",
        keywords=["bounded retries", "delivery state"],
        category="responsibility",
    )

    discovery_candidates = adapter.search_evidence([discovery])
    role_candidates = adapter.search_evidence([role_requirement])

    assert any(
        candidate.source.path == "personal-data/projects/lantern-queue.md"
        and candidate.source.section == "Background and goal"
        and "bounded retries" in candidate.proposed_claim
        for candidate in discovery_candidates
    )
    assert not any(
        candidate.source.path == "personal-data/projects/lantern-queue.md"
        and candidate.source.section == "Background and goal"
        for candidate in role_candidates
    )


def test_evidence_search_expands_slash_terms_and_prefers_work_sources(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    work = synthetic_db_copy / "personal-data/work/cpp-professional.md"
    work.write_text(
        "# Synthetic professional C++ record\n\n"
        "## Employment record\n\n"
        "#### Personal work\n\n"
        "- Implemented WaveLatch with C++.\n",
        encoding="utf-8",
    )
    personal_paths: set[str] = set()
    for index in range(8):
        relative = f"personal-data/projects/cpp-hobby-{index}.md"
        personal_paths.add(relative)
        (synthetic_db_copy / relative).write_text(
            "# Synthetic personal C++ project\n\n"
            "## Personal work\n\n"
            "- Implemented WaveLatch with C++.\n",
            encoding="utf-8",
        )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    requirement = requirement_factory(
        text="C/C++ WaveLatch implementation",
        verbatim_quote="C/C++ WaveLatch implementation",
        keywords=["C/C++", "WaveLatch"],
    )

    candidates = adapter.search_evidence([requirement])
    relevant = [
        candidate
        for candidate in candidates
        if candidate.source.path == "personal-data/work/cpp-professional.md"
        or candidate.source.path in personal_paths
    ]
    relevant_paths = {candidate.source.path for candidate in relevant}

    assert "c++" in adapter._meaningful_terms("C/C++")
    assert len(relevant) == 9
    assert "personal-data/work/cpp-professional.md" in relevant_paths
    assert relevant_paths & personal_paths == personal_paths
    work_candidate = next(
        candidate
        for candidate in relevant
        if candidate.source.path == "personal-data/work/cpp-professional.md"
    )
    assert work_candidate.match_state is RoleMatchState.DIRECT_EVIDENCE


def test_markerless_unknown_sections_fail_closed_while_known_work_is_admitted(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    unknown = synthetic_db_copy / "personal-data" / "misc" / "markerless.md"
    unknown.parent.mkdir()
    unknown.write_text(
        "# Markerless unknown source\n\n"
        "## Engineering experience\n\n"
        "- 使用 Python 与 Docker 构建大模型推理任务调度，并验证 GPU 资源状态。\n",
        encoding="utf-8",
    )
    education = (
        synthetic_db_copy
        / "personal-data"
        / "profile"
        / "education-and-honors.md"
    )
    education.write_text(
        education.read_text(encoding="utf-8")
        + "\n## 其他个人工程信息\n\n"
        "- HobbyCloud 仅是未分类的 markerless 个人信息。\n",
        encoding="utf-8",
    )
    known = synthetic_db_copy / "personal-data" / "work" / "markerless-chinese.md"
    known.write_text(
        "# Synthetic Chinese work record\n\n"
        "## 工作记录\n\n"
        "This incidental example contains F1, P0 but is not document-level gate metadata.\n\n"
        "#### 个人工作\n\n"
        "- 使用 Python 与 Docker 构建大模型推理任务调度，并验证 GPU 资源状态。\n",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    requirement = requirement_factory(
        text="负责 AI Infra 的大模型推理任务调度与 GPU 资源管理",
        verbatim_quote="负责 AI Infra 的大模型推理任务调度与 GPU 资源管理",
        keywords=["Python", "Docker", "GPU", "推理任务"],
    )
    hobby_requirement = requirement_factory(
        requirement_id="req-hobby-cloud",
        text="Use HobbyCloud",
        verbatim_quote="Use HobbyCloud",
        keywords=["HobbyCloud"],
    )

    candidates = adapter.search_evidence([requirement, hobby_requirement])
    known_candidates = [
        candidate
        for candidate in candidates
        if candidate.source.path == "personal-data/work/markerless-chinese.md"
    ]

    assert known_candidates
    assert all(candidate.fact_state is FactState.F2 for candidate in known_candidates)
    assert all(
        candidate.disclosure is DisclosureLevel.P1
        for candidate in known_candidates
    )
    assert all(
        candidate.match_state is RoleMatchState.DIRECT_EVIDENCE
        for candidate in known_candidates
    )
    assert all(
        candidate.source.path != "personal-data/misc/markerless.md"
        for candidate in candidates
    )
    assert all("HobbyCloud" not in candidate.proposed_claim for candidate in candidates)


def test_chinese_tables_populate_contact_timeline_and_public_profile_link(
    synthetic_db_copy: Path,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    basic = synthetic_db_copy / "personal-data" / "profile" / "basic-information.md"
    basic.write_text(
        "# 基础信息\n\n"
        "## 身份与联系方式\n\n"
        "| 字段 | 信息 |\n"
        "|---|---|\n"
        "| 姓名 | 林澄 |\n"
        "| 手机 | 13800000000 |\n"
        "| 邮箱 | [lin_cheng@career-fixture.invalid](mailto:lin_cheng@career-fixture.invalid) |\n"
        "| 所在地历史记录 | 杭州（记录日期待确认） |\n",
        encoding="utf-8",
    )
    links = synthetic_db_copy / "personal-data" / "meta" / "public-links.md"
    links.write_text(
        links.read_text(encoding="utf-8")
        + "\n## 其他公开入口\n\n"
        "| 名称 | URL | checked_at / outcome | 归属与使用边界 |\n"
        "|---|---|---|---|\n"
        "| 个人 GitHub 主页 | [https://github.example.invalid/lin](https://github.example.invalid/lin) | "
        "2026-08-10 / HTTP 200 可访问 | 仅用于虚构测试。 |\n"
        "| Personal profile | [https://unknown.example.invalid/lin](https://unknown.example.invalid/lin) | "
        "状态未知 | 不得作为已核验入口。 |\n",
        encoding="utf-8",
    )
    timeline = synthetic_db_copy / "personal-data" / "profile" / "career-timeline.md"
    timeline.write_text(
        "# 职业与实践时间线\n\n"
        "## 时间线\n\n"
        "| 时间 | 类型与来源 | 组织 / 项目 | 角色或阶段 | 主题 |\n"
        "|---|---|---|---|---|\n"
        "| 2022.08－2024.01 | 公司任职经历 | 星河云计算（虚构） | 软件工程师 | 平台工具 |\n"
        "| 2020.01－2020.06 | Coursework | 不应成为雇主（虚构） | 学员 | 课程 |\n"
        "| 2024.02－至今 | 公司任职经历 | 星河云计算（虚构） | 平台与系统软件工程师 | AI Infra |\n",
        encoding="utf-8",
    )
    work = synthetic_db_copy / "personal-data" / "work" / "chinese-experience.md"
    work.write_text(
        "# 星河云计算工作经历\n\n"
        "## 概览\n\n"
        "- **公司**：星河云计算（虚构）\n"
        "- **任职时间**：2022.08－至今\n"
        "- **当前岗位**：平台与系统软件工程师\n",
        encoding="utf-8",
    )
    education = (
        synthetic_db_copy
        / "personal-data"
        / "profile"
        / "education-and-honors.md"
    )
    education.write_text(
        "# 教育、荣誉与证书\n\n"
        "## 教育经历\n\n"
        "### 星桥大学\n\n"
        "| 字段 | 已记录事实 |\n"
        "|---|---|\n"
        "| 学校 | 星桥大学（虚构） |\n"
        "| 专业 | 软件系统 |\n"
        "| 学历层次 | 本科 |\n"
        "| 时间 | 2018.09－2022.07 |\n\n"
        "## 荣誉\n\n"
        "### 虚构系统设计奖（2020）\n\n"
        "- 等级：一等奖。\n",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    section = next(
        section
        for section in adapter.manifest.sections
        if section.source_path == "personal-data/work/chinese-experience.md"
    )
    record = EvidenceRecord(
        evidence_id="evidence.chinese-work",
        requirement_ids=["req-platform"],
        source=SourceRef(
            path=section.source_path,
            title=section.title,
            section=section.section,
            source_hash=section.source_hash,
            source_type="career-source",
        ),
        source_span=SourceSpan(
            start_line=section.start_line or 1,
            end_line=section.end_line or 1,
        ),
        fact_state=FactState.F2,
        disclosure=DisclosureLevel.P1,
        match_state=RoleMatchState.DIRECT_EVIDENCE,
        contribution_scope="Synthetic source-faithful claim.",
        safe_claim="使用 Python 构建平台工具。",
        forbidden_expansions=[],
        freshness=Freshness(dynamic=False),
    )

    profile = _candidate_profile(
        adapter,
        [record],
        [record],
        [],
        [],
        OutputMode.TARGETED_APPLICATION,
        _RECRUITER_ONE_PAGE,
    )

    assert profile["contact"]["name"] == "林澄"
    assert profile["contact"]["email"] == "lin_cheng@career-fixture.invalid"
    assert profile["contact"]["phone"] == "13800000000"
    assert profile["contact"]["location"] is None
    assert {
        "label": "个人 GitHub 主页",
        "url": "https://github.example.invalid/lin",
        "source_refs": ["personal-data/meta/public-links.md"],
    } in profile["contact"]["links"]
    assert all(
        link["url"] != "https://unknown.example.invalid/lin"
        for link in profile["contact"]["links"]
    )
    assert _timeline_rows(
        adapter,
        "personal-data/profile/career-timeline.md",
    ) == [
        {
            "start_date": "2022.08",
            "end_date": "至今",
            "organization": "星河云计算（虚构）",
            "role": "平台与系统软件工程师",
        }
    ]
    assert profile["experience"] == [
        {
            "organization": "星河云计算（虚构）",
            "role": "平台与系统软件工程师",
            "start_date": "2022.08",
            "end_date": "至今",
            "evidence_ids": ["evidence.chinese-work"],
            "source_refs": ["personal-data/work/chinese-experience.md"],
            "context": None,
        }
    ]
    assert profile["education"] == [
        {
            "institution": "星桥大学（虚构）",
            "degree": "本科",
            "field": "软件系统",
            "start_date": "2018.09",
            "end_date": "2022.07",
            "source_refs": [
                "personal-data/profile/education-and-honors.md"
            ],
        }
    ]
    assert profile["honors"] == [
        {
            "name": "虚构系统设计奖",
            "date": "2020",
            "source_refs": [
                "personal-data/profile/education-and-honors.md"
            ],
        }
    ]

def test_recruiter_profile_keeps_career_context_but_omits_project_context(
    synthetic_db_copy: Path,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    work_path = "personal-data/work/recruiter-context.md"
    (
        synthetic_db_copy / work_path
    ).write_text(
        "# 星桥平台工作经历\n\n"
        "## 概览\n\n"
        "- **公司**：星桥平台（虚构）\n"
        "- **任职时间**：2022.01－至今\n"
        "- **当前岗位**：平台工程师\n"
        "- **职业演进**：从后端工程逐步扩展到平台交付与可靠性建设\n",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    project_path = "personal-data/company-projects/context-fixture.md"

    def record(
        evidence_id: str,
        path: str,
        section: str,
        claim: str,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=evidence_id,
            source=SourceRef(
                path=path,
                title="Synthetic Context Fixture",
                section=section,
                source_hash=f"{evidence_id}-hash",
                source_type="career-source",
            ),
            source_span=SourceSpan(start_line=1, end_line=1),
            fact_state=FactState.F2,
            disclosure=DisclosureLevel.P1,
            match_state=RoleMatchState.DIRECT_EVIDENCE,
            contribution_scope="Synthetic source-faithful claim.",
            safe_claim=claim,
            freshness=Freshness(dynamic=False),
        )

    work = record(
        "evidence.recruiter-work",
        work_path,
        "Personal work",
        "Built platform delivery controls for internal services.",
    )
    project = record(
        "evidence.recruiter-project",
        project_path,
        "Personal work",
        "Implemented deterministic project delivery checks.",
    )
    project_context = record(
        "evidence.recruiter-project-context",
        project_path,
        "Background and goals",
        "The project provides a controlled environment for delivery experiments.",
    )
    selected = [work, project]
    all_records = [work, project, project_context]

    recruiter = _candidate_profile(
        adapter,
        selected,
        all_records,
        [],
        [],
        OutputMode.TARGETED_APPLICATION,
        _RECRUITER_ONE_PAGE,
    )
    technical = _candidate_profile(
        adapter,
        selected,
        all_records,
        [],
        [],
        OutputMode.TARGETED_APPLICATION,
        _TECHNICAL_TWO_PAGE,
    )

    assert recruiter["experience"][0]["context"] == (
        "从后端工程逐步扩展到平台交付与可靠性建设"
    )
    assert recruiter["projects"][0]["context"] is None
    assert technical["projects"][0]["context"] == project_context.safe_claim



def test_candidate_profile_skills_reference_only_selected_evidence(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    source_path = "personal-data/company-projects/cpp-platform.md"
    record = EvidenceRecord(
        evidence_id="evidence.selected",
        requirement_ids=["req-cpp"],
        source=SourceRef(
            path=source_path,
            title="Synthetic C++ Platform",
            section="Personal work",
            source_hash="synthetic-cpp-hash",
            source_type="career-source",
        ),
        source_span=SourceSpan(start_line=1, end_line=1),
        fact_state=FactState.F2,
        disclosure=DisclosureLevel.P1,
        match_state=RoleMatchState.DIRECT_EVIDENCE,
        contribution_scope="Synthetic source-faithful claim.",
        safe_claim="Implemented a C++ platform component.",
        freshness=Freshness(dynamic=False),
    )
    requirement = requirement_factory(
        requirement_id="req-cpp",
        text="C/C++ development",
        verbatim_quote="C/C++ development",
        keywords=[],
    )
    mapping = EvidenceMapping(
        requirement_id="req-cpp",
        match_state=RoleMatchState.DIRECT_EVIDENCE,
        evidence_ids=["evidence.selected", "evidence.not-selected"],
        selection_reason="Synthetic selection.",
    )

    profile = _candidate_profile(
        adapter,
        [record],
        [record],
        [mapping],
        [requirement],
        OutputMode.TARGETED_APPLICATION,
        _RECRUITER_ONE_PAGE,
    )

    assert profile["skills"] == [
        {
            "group": "Relevant Capabilities",
            "items": [
                {
                    "text": "C++",
                    "evidence_ids": ["evidence.selected"],
                    "source_refs": [source_path],
                }
            ],
            "source_refs": [source_path],
        }
    ]


def test_candidate_deduplication_keeps_match_state_scoped_to_requirements(
    candidate_factory,
) -> None:
    direct = candidate_factory(
        candidate_id="candidate-direct",
        requirement_ids=["req-direct"],
        match_state=RoleMatchState.DIRECT_EVIDENCE,
    )
    transferable = candidate_factory(
        candidate_id="candidate-transferable",
        requirement_ids=["req-transferable"],
        match_state=RoleMatchState.TRANSFERABLE_EXPERIENCE,
    )

    deduplicated = _deduplicate_candidates([direct, transferable])

    assert {
        candidate.match_state: candidate.requirement_ids
        for candidate in deduplicated
    } == {
        RoleMatchState.DIRECT_EVIDENCE: ["req-direct"],
        RoleMatchState.TRANSFERABLE_EXPERIENCE: ["req-transferable"],
    }


def test_cluster_requirements_retrieve_swarm_platform_as_transferable_evidence(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    directory = synthetic_db_copy / "personal-data/company-projects"
    directory.mkdir()
    source = directory / "swarm-platform.md"
    source.write_text(
        "# Synthetic workspace platform\n\n"
        "## Personal work\n\n"
        "- Modeled Docker Swarm services and controlled compute-resource "
        "creation and release from workspace lifecycle state.\n",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    requirement = requirement_factory(
        text=(
            "Build and maintain distributed training systems for a large-scale "
            "GPU cluster."
        ),
        verbatim_quote=(
            "Build and maintain distributed training systems for a large-scale "
            "GPU cluster."
        ),
        keywords=["distributed training", "GPU cluster"],
    )

    candidates = [
        candidate
        for candidate in adapter.search_evidence([requirement])
        if candidate.source.path
        == "personal-data/company-projects/swarm-platform.md"
    ]

    assert candidates
    assert all(
        candidate.match_state is RoleMatchState.TRANSFERABLE_EXPERIENCE
        for candidate in candidates
    )


def test_inference_operations_do_not_become_direct_low_latency_training_evidence(
    synthetic_db_copy: Path,
    requirement_factory,
) -> None:
    _remove_documented_traversal(synthetic_db_copy)
    source = synthetic_db_copy / "personal-data" / "work" / "inference-operations.md"
    source.write_text(
        "# Synthetic inference operations\n\n"
        "## 个人工作\n\n"
        "- 维护模型推理实例发现、负载状态采集和健康检查。\n",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    requirement = requirement_factory(
        text=(
            "构建机器人实时控制的低延迟推理流水线，并应用量化、蒸馏和"
            "模型编译优化推理性能。"
        ),
        verbatim_quote=(
            "构建机器人实时控制的低延迟推理流水线，并应用量化、蒸馏和"
            "模型编译优化推理性能。"
        ),
        keywords=["推理", "低延迟", "量化", "蒸馏", "模型编译"],
    )

    candidates = [
        candidate
        for candidate in adapter.search_evidence([requirement])
        if candidate.source.path == "personal-data/work/inference-operations.md"
    ]

    assert candidates
    assert all(
        candidate.match_state is RoleMatchState.TRANSFERABLE_EXPERIENCE
        for candidate in candidates
    )
