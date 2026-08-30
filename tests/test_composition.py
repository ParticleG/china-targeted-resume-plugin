from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json


from china_targeted_resume.adapters.markdown_career_v1 import MarkdownCareerV1Adapter
from china_targeted_resume.audit import (
    audit_ats,
    audit_hr,
    audit_privacy,
    audit_resume,
    audit_technical,
    audit_truth,
)
from china_targeted_resume.composition import (
    build_resume_document,
    contains_placeholder,
    rank_evidence,
    resume_claim_is_substantive,
    resume_claim_priority,
    render_ats_text,
    render_targeted_markdown,
)
from china_targeted_resume.models import EvidenceRecord, OutputMode, ResumeVariant
from china_targeted_resume.provenance import build_confirmation_questions
from china_targeted_resume.pipeline import (
    _EXTENDED_THREE_PAGE,
    _RECRUITER_ONE_PAGE,
    _TECHNICAL_TWO_PAGE,
    _select_resume_records,
    _select_variant_records,
    _template_for_variant,
)


PROFILE_REF = "personal-data/profile/identity.md#identity@profilehash"
WORK_REF = "personal-data/work/platform.md#outcomes@workhash"


def _profile() -> dict[str, object]:
    return {
        "provenance_refs": [PROFILE_REF],
        "contact": {
            "name": "林明",
            "phone": "+86 138 0000 0000",
            "email": "lin.ming@career-fixture.invalid",
            "location": "上海",
            "links": [{"label": "GitHub", "url": "https://career-fixture.invalid/lin"}],
            "provenance_refs": [PROFILE_REF],
        },
        "experience": [
            {
                "organization": "示例科技",
                "role": "平台工程师",
                "start_date": "2022-01",
                "end_date": "至今",
                "context": "云平台基础设施",
                "evidence_ids": ["ev-platform", "ev-runtime", "ev-private"],
                "provenance_refs": [WORK_REF],
            }
        ],
    }


def _target(role: str = "高级平台工程师") -> dict[str, object]:
    return {
        "target_basis": "exact-current-jd",
        "company": "ACME Cloudworks",
        "role": role,
        "source_refs": ["role-research/acme/jd.md#requirements@jdhash"],
    }


def _evidence(
    evidence_id: str,
    claim: str,
    *,
    requirement_ids: list[str] | None = None,
    fact_state: str = "F1",
    disclosure: str = "P0",
    match_state: str = "已有直接证据",
    source_path: str = "personal-data/work/platform.md",
    source_section: str = "outcomes",
    source_hash: str = "workhash",
    contribution_scope: str = "Personally owned the described implementation; metric is team-level where stated.",
    freshness: dict[str, object] | None = None,
) -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "evidence_id": evidence_id,
            "requirement_ids": requirement_ids or [],
            "source": {
                "path": source_path,
                "section": source_section,
                "source_hash": source_hash,
            },
            "fact_state": fact_state,
            "disclosure": disclosure,
            "match_state": match_state,
            "contribution_scope": contribution_scope,
            "safe_claim": claim,
            "freshness": freshness or {"dynamic": False, "stale": False},
        }
    )


def _all_bullets(document: object) -> list[object]:
    return [
        bullet
        for section in (document.experience, document.projects)
        for container in section
        for bullet in container.bullets
    ]


def test_target_changes_selection_order_but_never_rewrites_safe_facts() -> None:
    records = [
        _evidence("ev-platform", "Personally automated release controls for the platform.", requirement_ids=["req-platform"]),
        _evidence("ev-runtime", "Personally reduced a measured runtime bottleneck.", requirement_ids=["req-runtime"], source_hash="runtimehash"),
    ]
    mappings = [
        {"requirement_id": "req-platform", "evidence_ids": ["ev-platform"], "resume_priority": 1.0},
        {"requirement_id": "req-runtime", "evidence_ids": ["ev-runtime"], "resume_priority": 1.0},
    ]
    platform_requirements = [
        {"requirement_id": "req-platform", "priority": "critical"},
        {"requirement_id": "req-runtime", "priority": "low"},
    ]
    runtime_requirements = [
        {"requirement_id": "req-platform", "priority": "low"},
        {"requirement_id": "req-runtime", "priority": "critical"},
    ]

    platform = build_resume_document(_profile(), _target("平台工程师"), records, mappings, platform_requirements)
    runtime = build_resume_document(_profile(), _target("运行时工程师"), records, mappings, runtime_requirements)
    platform_claims = [bullet.text for bullet in _all_bullets(platform)]
    runtime_claims = [bullet.text for bullet in _all_bullets(runtime)]

    assert platform_claims == [records[0].safe_claim, records[1].safe_claim]
    assert runtime_claims == [records[1].safe_claim, records[0].safe_claim]
    assert set(platform_claims) == set(runtime_claims) == {record.safe_claim for record in records}
    assert "2022-01 至今" in render_targeted_markdown(platform)


def test_disclosure_and_fact_state_matrix_is_fail_closed_and_p2_is_targeted_only() -> None:
    records = [
        _evidence("ev-f1", "Verified public-safe platform claim."),
        _evidence("ev-f4", "Unverified claim must become a question.", fact_state="F4"),
        _evidence("ev-f5", "Conflicting claim must become a question.", fact_state="F5"),
        _evidence("ev-f6", "Secret claim must never persist.", fact_state="F6"),
        _evidence("ev-p2", "Application-only customer-safe claim.", disclosure="P2"),
        _evidence("ev-p3", "Private claim must never persist.", disclosure="P3"),
    ]

    targeted = build_resume_document(_profile(), _target(), records, mode=OutputMode.TARGETED_APPLICATION)
    portfolio = build_resume_document(_profile(), _target(), records, mode=OutputMode.PUBLIC_PORTFOLIO)
    targeted_text = render_ats_text(targeted)
    portfolio_text = render_ats_text(portfolio)


    assert records[0].safe_claim in targeted_text and records[0].safe_claim in portfolio_text
    assert records[4].safe_claim in targeted_text and records[4].safe_claim not in portfolio_text
    for record in (records[1], records[2], records[3], records[5]):
        assert record.safe_claim not in targeted_text
        assert record.safe_claim not in portfolio_text
        assert record.safe_claim not in json.dumps(targeted.model_dump(mode="json"), ensure_ascii=False)
        assert record.safe_claim not in json.dumps(portfolio.model_dump(mode="json"), ensure_ascii=False)

    questions = "\n".join(build_confirmation_questions(records))
    assert records[1].safe_claim in questions
    assert records[2].safe_claim in questions
    assert records[3].safe_claim not in questions
    assert records[5].safe_claim not in questions


def test_extended_profile_uses_readable_body_type() -> None:
    document = build_resume_document(
        _profile(),
        _target(),
        [_evidence("ev-platform", "Personally automated release controls.")],
        variant=ResumeVariant.EXTENDED_THREE_PAGE,
        target_pages=3,
    )

    assert document.render_policy.minimum_body_font_pt == 12.5


def test_project_context_warning_is_variant_aware_and_reported_once() -> None:
    records = [
        _evidence(
            f"ev-project-{index}",
            f"Implemented verified project capability {index}.",
            source_path="personal-data/company-projects/platform.md",
            source_section="Personal work",
        )
        for index in range(2)
    ]
    profile = _profile()
    profile["projects"] = [
        {
            "name": "Platform project",
            "evidence_ids": [record.evidence_id for record in records],
            "source_refs": ["personal-data/company-projects/platform.md"],
        }
    ]
    technical = build_resume_document(
        profile,
        _target(),
        records,
        variant=ResumeVariant.TECHNICAL_TWO_PAGE,
    )
    recruiter = build_resume_document(
        profile,
        _target(),
        records,
        variant=ResumeVariant.RECRUITER_ONE_PAGE,
        target_pages=1,
    )

    technical_context_warnings = [
        warning
        for warning in audit_technical(technical, records).warnings
        if "technical.project_context" in warning
    ]
    recruiter_context_warnings = [
        warning
        for warning in audit_technical(recruiter, records).warnings
        if "technical.project_context" in warning
    ]

    assert len(technical_context_warnings) == 1
    assert recruiter_context_warnings == []


def test_extended_selection_budget_cannot_exceed_density_ceiling() -> None:
    maximum_selected_claims = (
        _EXTENDED_THREE_PAGE.work_bullets
        + _EXTENDED_THREE_PAGE.project_limit
        * _EXTENDED_THREE_PAGE.project_bullets
    )

    assert maximum_selected_claims <= (
        _EXTENDED_THREE_PAGE.target_pages * 10
    )


def test_stale_dynamic_evidence_and_placeholder_claims_are_omitted() -> None:
    records = [
        _evidence(
            "ev-current",
            "Current public link and current dynamic fact.",
            fact_state="F3",
            freshness={"dynamic": True, "checked_at": datetime.now(UTC), "stale": False},
        ),
        _evidence(
            "ev-stale",
            "Stale dynamic fact.",
            fact_state="F3",
            freshness={"dynamic": True, "checked_at": "2020-01-01T00:00:00Z", "stale": True},
        ),
        _evidence("ev-placeholder", "Delivered TODO percent improvement."),
    ]

    document = build_resume_document(_profile(), _target(), records)
    text = render_ats_text(document)

    assert records[0].safe_claim in text
    assert records[1].safe_claim not in text
    assert records[2].safe_claim not in text
    assert not contains_placeholder(text)
    assert "TODO" not in render_targeted_markdown(document)
    assert records[1].safe_claim in "\n".join(build_confirmation_questions(records))


def test_qualified_metrics_and_team_attribution_are_preserved_verbatim() -> None:
    claims = [
        "Team throughput improved by approximately 18% during the measured stage.",
        "Observed latency remained in the 40–55 ms range in the staging environment.",
    ]
    records = [
        _evidence("ev-platform", claims[0], contribution_scope="Team outcome; personally owned release automation only."),
        _evidence("ev-runtime", claims[1], source_hash="runtimehash", contribution_scope="Measurement was team-run; no sole attribution."),
    ]
    document = build_resume_document(_profile(), _target(), records)
    rendered = render_targeted_markdown(document)

    assert document.summary == []
    assert [bullet.text for bullet in _all_bullets(document)] == claims
    assert all(claim in rendered for claim in claims)
    assert "improved throughput by 18%" not in rendered
    assert "reduced latency to 40 ms" not in rendered
    assert audit_technical(document, records).success


def test_every_visible_fact_has_provenance_and_company_research_is_rejected_as_personal_evidence() -> None:
    records = [_evidence("ev-platform", "Personally automated release controls for the platform.")]
    document = build_resume_document(_profile(), _target(), records)

    valid = audit_truth(document, records, mode=OutputMode.TARGETED_APPLICATION)
    assert valid.success, valid.errors
    assert valid.checks["every_visible_fact_has_provenance"]

    research = _evidence(
        "ev-research",
        "ACME operates a large cloud platform.",
        source_path="company-research/acme-cloudworks/profile.md",
        source_section="overview",
        source_hash="companyhash",
    )
    unsafe = build_resume_document(_profile(), _target(), [research])
    report = audit_truth(unsafe, [research], mode=OutputMode.TARGETED_APPLICATION)

    assert not report.success
    assert not report.checks["company_research_not_personal_evidence"]
    assert any("company_research_fact" in error for error in report.errors)


def test_audits_warn_on_underfill_and_detect_targeted_regressions() -> None:
    record = _evidence("ev-platform", "Personally automated release controls for the platform.")
    document = build_resume_document(_profile(), _target(), [record])

    reports = {
        "ats": audit_ats(document),
        "hr": audit_hr(document),
        "technical": audit_technical(document, [record]),
        "truth": audit_truth(document, [record], mode="targeted_application"),
        "privacy": audit_privacy(document, mode="targeted_application"),
    }
    assert reports["hr"].success
    assert not reports["hr"].checks["sufficient_density"]
    assert any(
        "density_underfill" in warning
        for warning in reports["hr"].warnings
    )
    assert all(report.success for report in reports.values())
    combined = audit_resume(document, [record], mode="targeted_application")
    assert combined.success
    assert combined.checks == {
        "ats": True,
        "hr": True,
        "technical": True,
        "truth": True,
        "privacy": True,
    }

    placeholder = deepcopy(document.model_dump(mode="python"))
    placeholder["headline"] = "TODO TARGET"
    assert not audit_ats(placeholder).success

    private = deepcopy(document.model_dump(mode="python"))
    private["contact"]["links"] = [{"label": "internal", "url": "ssh://10.0.0.4/private/log"}]
    privacy = audit_privacy(private, mode="targeted_application")
    assert not privacy.success
    assert not privacy.checks["no_internal_urls"]
    assert not privacy.checks["no_private_material"]

    expanded = deepcopy(document.model_dump(mode="python"))
    expanded["experience"][0]["bullets"][0]["text"] = "Single-handedly automated every release and improved uptime by 99%."
    truth = audit_truth(expanded, [record], mode="targeted_application")
    technical = audit_technical(expanded, [record])
    assert not truth.success and not truth.checks["safe_claim_unchanged"]
    assert not technical.success and not technical.checks["metric_wording_preserved"]


def test_hr_audit_warns_on_underfilled_technical_and_extended_documents() -> None:
    record = _evidence("ev-platform", "Personally automated release controls for the platform.")
    document = build_resume_document(_profile(), _target(), [record])

    technical = deepcopy(document.model_dump(mode="python"))
    technical["render_policy"]["target_pages"] = 2
    extended = deepcopy(technical)
    extended["render_policy"]["target_pages"] = 3

    for candidate, minimum in ((technical, 12), (extended, 18)):
        report = audit_hr(candidate)
        assert report.success
        assert not report.checks["sufficient_density"]
        assert report.checks["reasonable_density"]
        assert any(
            "density_underfill" in warning and str(minimum) in warning
            for warning in report.warnings
        )


def test_resume_selection_skips_audit_metadata_and_standalone_intro_claims() -> None:
    intro = _evidence(
        "ev-intro",
        "Work spans the following process and system boundaries:",
        source_path="personal-data/work/platform.md",
        source_section="Architecture and responsibilities",
    )
    metadata = _evidence(
        "ev-metadata",
        "项目性质：公司内部推理实例发现与负载采集服务。",
        source_path="personal-data/company-projects/inference.md",
        source_section="概览",
    )
    scope_metadata = _evidence(
        "ev-scope-metadata",
        "职责方向：推理实例发现、渠道映射、滞回控制和运维控制台。",
        source_path="personal-data/company-projects/inference.md",
        source_section="个人工作",
    )
    boundary = _evidence(
        "ev-boundary",
        "Current checkout evidence only proves that entrypoints exist; it does not prove production enablement.",
        source_path="personal-data/company-projects/editor.md",
        source_section="Engineering verification",
    )
    taxonomy = _evidence(
        "ev-taxonomy",
        "Docker Swarm service：模板支持的集群调度形态。",
        source_path="personal-data/company-projects/platform.md",
        source_section="计算与存储面",
    )
    diagram = _evidence(
        "ev-diagram",
        "text Host process └─ local service ├─ worker └─ renderer",
        source_path="personal-data/company-projects/editor.md",
        source_section="Architecture",
    )
    inference = _evidence(
        "ev-inference",
        "Implemented inference-instance discovery, load collection, gateway controls, and operational visualization.",
        fact_state="F2",
        match_state="可迁移经验",
        source_path="personal-data/company-projects/inference.md",
    )
    contribution_metadata = _evidence(
        "ev-contribution-metadata",
        "个人贡献：模板建模、调度约束、状态对账和运维编排。",
        source_path="personal-data/company-projects/platform.md",
        source_section="概览",
    )
    representative_mapping = _evidence(
        "ev-representative-mapping",
        "Coder/Terraform/Docker platform provides workspace lifecycle management.",
        source_path="personal-data/work/platform.md",
        source_section="系统架构与职责范围",
    )
    record_structure = _evidence(
        "ev-record-structure",
        "问题：共享状态访问会被锁内网络请求阻塞。",
        source_path="personal-data/company-projects/inference.md",
        source_section="锁竞争与网络延迟",
    )
    upstream_inventory = _evidence(
        "ev-upstream-inventory",
        "The control service reads model state but does not implement inference.",
        source_path="personal-data/company-projects/inference.md",
        source_section="upstream inference layer",
    )
    redundant_team_scope = _evidence(
        "ev-redundant-team-scope",
        "2 人小组：带领 2 人小组开展兼容性研究。",
        source_path="personal-data/work/platform.md",
        source_section="个人工作",
    )
    platform = _evidence(
        "ev-platform-substantive",
        "Built versioned workspace lifecycle and compute-resource controls for a Docker Swarm platform.",
        fact_state="F2",
        match_state="可迁移经验",
        source_path="personal-data/company-projects/platform.md",
    )
    records = [
        intro,
        metadata,
        scope_metadata,
        boundary,
        taxonomy,
        inference,
        diagram,
        platform,
        contribution_metadata,
        representative_mapping,
        record_structure,
        upstream_inventory,
        redundant_team_scope,
    ]
    mapping = {
        "requirement_id": "req-ai-infra",
        "evidence_ids": [record.evidence_id for record in records],
        "resume_priority": 1.0,
    }

    selected = _select_resume_records(
        records,
        [mapping],
        [{"requirement_id": "req-ai-infra", "priority": "critical"}],
        OutputMode.TARGETED_APPLICATION,
        total_limit=2,
    )

    assert [record.evidence_id for record in selected] == [
        "ev-inference",
        "ev-platform-substantive",
    ]
    assert {record.evidence_id for record in rank_evidence(records)} == {
        record.evidence_id for record in records
    }


def test_resume_selection_limits_each_source_to_preserve_breadth() -> None:
    concentrated = [
        _evidence(
            f"ev-concentrated-{index}",
            f"Delivered concentrated platform outcome {index}.",
            source_path="personal-data/work/platform.md",
        )
        for index in range(3)
    ]
    broader = _evidence(
        "ev-broader-platform",
        "Implemented lifecycle controls for a second relevant platform.",
        fact_state="F2",
        match_state="可迁移经验",
        source_path="personal-data/company-projects/platform.md",
    )
    records = [*concentrated, broader]
    mapping = {
        "requirement_id": "req-platform",
        "evidence_ids": [record.evidence_id for record in records],
        "resume_priority": 1.0,
    }

    selected = _select_resume_records(
        records,
        [mapping],
        [{"requirement_id": "req-platform", "priority": "critical"}],
        OutputMode.TARGETED_APPLICATION,
        total_limit=3,
    )

    assert sum(
        record.source.path == "personal-data/work/platform.md"
        for record in selected
    ) == 2
    assert broader in selected


def test_variant_selection_deduplicates_normalized_visible_claims_globally() -> None:
    records = [
        _evidence(
            "ev-project-a",
            "Built   release controls\nfor the platform.",
            source_path="personal-data/company-projects/release-a.md",
            source_section="Personal work",
        ),
        _evidence(
            "ev-project-b",
            "built release controls for the platform.",
            source_path="personal-data/company-projects/release-b.md",
            source_section="Personal work",
        ),
    ]

    selected = _select_variant_records(
        MarkdownCareerV1Adapter(),
        records,
        [],
        [],
        OutputMode.TARGETED_APPLICATION,
        _RECRUITER_ONE_PAGE,
    )

    assert len(selected) == 1
    assert " ".join(selected[0].safe_claim.split()).casefold() == (
        "built release controls for the platform."
    )

def test_targeted_variant_uses_only_mapped_confirmed_practice() -> None:
    mapped = _evidence(
        "ev-mapped",
        "Implemented role-relevant release controls.",
        source_path="personal-data/company-projects/relevant.md",
        source_section="Personal work",
    )
    unmapped = _evidence(
        "ev-unmapped",
        "Implemented an unrelated community utility.",
        source_path="personal-data/community-projects/unrelated.md",
        source_section="Personal work",
    )
    study_only = _evidence(
        "ev-study",
        "Studied Kubernetes workload concepts.",
        match_state="有知识无实践",
        source_path="personal-data/personal-projects/study.md",
        source_section="Personal work",
    )
    mapping = {
        "requirement_id": "req-release",
        "evidence_ids": ["ev-mapped", "ev-study"],
        "resume_priority": 1.0,
    }

    selected = _select_variant_records(
        MarkdownCareerV1Adapter(),
        [mapped, unmapped, study_only],
        [mapping],
        [{"requirement_id": "req-release", "priority": "required"}],
        OutputMode.TARGETED_APPLICATION,
        _TECHNICAL_TWO_PAGE,
    )

    assert selected == [mapped]


def test_adaptive_template_resolves_to_concrete_single_column_variants() -> None:
    assert (
        _template_for_variant("adaptive", ResumeVariant.RECRUITER_ONE_PAGE)
        == "ats-simple"
    )
    assert (
        _template_for_variant("adaptive", ResumeVariant.TECHNICAL_TWO_PAGE)
        == "human-readable"
    )
    assert (
        _template_for_variant("adaptive", ResumeVariant.EXTENDED_THREE_PAGE)
        == "human-readable"
    )


def test_claim_quality_never_displaces_more_relevant_professional_evidence() -> None:
    professional = _evidence(
        "ev-professional-ai-infra",
        (
            "Implemented paginated model-gateway channel discovery and "
            "synchronized inference load state."
        ),
        source_path="personal-data/company-projects/inference.md",
        source_section="Control service",
    )
    unrelated_community = _evidence(
        "ev-community-client",
        "Implemented dependency injection for a desktop automation client.",
        source_path="personal-data/community-projects/maa-client.md",
        source_section="Personal work",
    )
    records = [professional, unrelated_community]
    mapping = {
        "requirement_id": "req-ai-infra",
        "evidence_ids": [record.evidence_id for record in records],
        "resume_priority": 1.0,
    }

    selected = _select_resume_records(
        records,
        [mapping],
        [{"requirement_id": "req-ai-infra", "priority": "critical"}],
        OutputMode.TARGETED_APPLICATION,
        total_limit=1,
    )

    assert selected == [professional]


def test_resume_claim_classification_uses_section_and_predicate_structure() -> None:
    excluded = [
        _evidence(
            "ev-overview",
            "Implemented a service.",
            source_section="Overview",
        ),
        _evidence(
            "ev-stack",
            "Docker, Docker Compose, Docker Swarm",
            source_section="Technology stack",
        ),
        _evidence(
            "ev-field-inventory",
            "数据与状态：SQLAlchemy、SQLite、MySQL、JSON、LRU",
            source_section="Data model",
        ),
        _evidence(
            "ev-background-problem",
            "Different inference runtimes require layered discovery.",
            source_section="Background and goals",
        ),
        _evidence(
            "ev-upstream-boundary",
            "上游设备通信能力不归为个人自研。",
            source_section="Personal work",
        ),
        _evidence(
            "ev-context-dependent-decision",
            (
                "将竞品研究拆为交互、上下文、通信和工程化约束，"
                "避免只复刻界面而忽略底层数据流。"
            ),
            source_section="关键难点与决策",
        ),
    ]
    preferred = [
        _evidence(
            "ev-personal-work",
            "Implemented paginated channel discovery and synchronized load state.",
            source_section="Personal work",
        ),
        _evidence(
            "ev-chinese-personal-work",
            "建设基于 Coder、Terraform 与 Docker Swarm 的研发云工作区体系。",
            source_section="个人工作",
        ),
        _evidence(
            "ev-results",
            "14 independently versioned workspace templates.",
            source_section="Results and metrics",
        ),
        _evidence(
            "ev-verification",
            "Candidate validation covered restart, mounts, and persistent data.",
            source_section="Engineering and verification",
        ),
    ]

    assert all(not resume_claim_is_substantive(record) for record in excluded)
    assert [
        resume_claim_priority(record) for record in preferred
    ] == [4, 4, 4, 3]


def test_resume_claim_predicate_keeps_qualified_achievement() -> None:
    qualified = _evidence(
        "ev-qualified",
        (
            "Team throughput improved by approximately 18% during the measured "
            "stage; test environment and sample scope remain pending confirmation."
        ),
        source_section="Results and metrics",
    )

    assert resume_claim_is_substantive(qualified)


def test_resume_claim_predicate_rejects_checkout_delivery_boundary() -> None:
    boundary = _evidence(
        "ev-checkout-boundary",
        "不把本地 checkout 计为完整交付",
        source_section="Engineering verification",
    )

    assert not resume_claim_is_substantive(boundary)


def test_technical_audit_rejects_non_substantive_visible_claim() -> None:
    boundary = _evidence(
        "ev-visible-boundary",
        (
            "Current checkout evidence only proves that entrypoints exist; "
            "it does not prove production enablement."
        ),
        source_section="Engineering verification",
    )
    document = build_resume_document(_profile(), _target(), [boundary])

    report = audit_technical(document, [boundary])

    assert not report.success
    assert not report.checks["visible_claims_substantive"]
    assert any("technical.resume_readiness" in error for error in report.errors)


def test_adjacent_domain_gap_never_turns_transferable_evidence_into_robotics_experience() -> None:
    transferable = _evidence(
        "ev-platform",
        "Built transferable distributed-systems tooling for a cloud platform.",
        match_state="可迁移经验",
    )
    document = build_resume_document(_profile(), _target("机器人平台工程师"), [transferable])
    visible = render_ats_text(document)

    assert transferable.safe_claim in visible
    assert "robotics experience" not in visible.casefold()
    assert "机器人经验" not in visible
    assert document.experience[0].bullets[0].text == transferable.safe_claim


def test_equal_evidence_prefers_professional_sources_over_personal_projects() -> None:
    personal = _evidence(
        "ev-personal",
        "Built a personal platform prototype.",
        source_path="personal-data/personal-projects/prototype.md",
    )
    company = _evidence(
        "ev-company",
        "Built a company platform component.",
        source_path="personal-data/company-projects/platform.md",
    )
    work = _evidence(
        "ev-work",
        "Delivered a platform capability in an employment role.",
        source_path="personal-data/work/platform.md",
    )

    ranked = rank_evidence([personal, company, work])

    assert [record.evidence_id for record in ranked] == [
        "ev-work",
        "ev-company",
        "ev-personal",
    ]
