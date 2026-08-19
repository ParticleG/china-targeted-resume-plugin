from __future__ import annotations

import re

from china_targeted_resume.composition import compact_resume_document
from china_targeted_resume.models import ResumeDocument
from china_targeted_resume.rendering import render_html


SECTION_ORDER = ("contact", "summary", "skills", "experience", "projects", "education", "honors", "links")


def _resume_document() -> ResumeDocument:
    return ResumeDocument.model_validate(
        {
            "locale": "zh-CN",
            "target": {
                "company": "ACME Cloudworks",
                "role": "高级平台工程师",
                "target_basis": "exact-current-jd",
            },
            "contact": {
                "name": "林明",
                "phone": "+86 138 0000 0000",
                "email": "lin.ming@career-fixture.invalid",
                "location": "上海",
                "links": [{"label": "GitHub", "url": "https://career-fixture.invalid/lin"}],
            },
            "headline": "高级平台工程师",
            "summary": ["以可验证证据交付可靠的平台工程。"],
            "skills": [{"group": "平台", "items": ["Python", "Kubernetes", "Python"]}],
            "experience": [
                {
                    "organization": "示例科技",
                    "role": "平台工程师",
                    "location": "上海",
                    "start_date": "2022-01",
                    "end_date": "至今",
                    "context": "可靠性平台",
                    "bullets": [
                        {"text": "负责发布控制自动化。", "claim_ids": ["ev-high"], "priority": 1.0},
                        {"text": "整理低优先级内部工具文档。", "claim_ids": ["ev-low"], "priority": 0.05},
                    ],
                },
                {
                    "organization": "早期示例公司",
                    "role": "工程师",
                    "start_date": "2020-01",
                    "end_date": "2021-12",
                    "context": "可靠性平台",
                    "bullets": [{"text": "维护早期服务。", "claim_ids": ["ev-early"], "priority": 0.2}],
                },
            ],
            "projects": [
                {
                    "name": "运行时诊断",
                    "role": "负责人",
                    "context": "生产运行时",
                    "start_date": "2023-01",
                    "end_date": "2023-12",
                    "technologies": ["Python"],
                    "bullets": [{"text": "定位并修复可复现的运行时瓶颈。", "claim_ids": ["ev-project"], "priority": 0.8}],
                }
            ],
            "education": [
                {
                    "institution": "示例大学",
                    "degree": "工学学士",
                    "field": "计算机科学",
                    "start_date": "2016",
                    "end_date": "2020",
                    "details": [],
                }
            ],
            "honors": [{"name": "工程实践奖", "issuer": "示例大学", "date": "2020"}],
            "render_policy": {
                "target_pages": 1,
                "template": "human-readable",
                "minimum_body_font_pt": 10.0,
                "minimum_margin_mm": 12.0,
            },
            "provenance_refs": ["personal-data/profile.md#identity@hash"],
        }
    )


def _section_order(html: str) -> tuple[str, ...]:
    return tuple(re.findall(r'data-section-id="([^"]+)"', html))


def test_both_templates_share_single_column_semantic_read_order_and_local_cjk_font() -> None:
    document = _resume_document()
    rendered = {template: render_html(document, template) for template in ("ats-simple", "human-readable")}

    assert _section_order(rendered["ats-simple"]) == SECTION_ORDER
    assert _section_order(rendered["human-readable"]) == SECTION_ORDER
    for html in rendered.values():
        assert "@font-face" in html
        assert "font-family: 'Resume CJK'" in html
        assert "file:///usr/share/fonts/" in html
        assert 'data-minimum-body-font-pt="10.0"' in html
        assert 'data-minimum-margin-mm="12.0"' in html
        assert "mailto:lin.ming@career-fixture.invalid" in html
        assert "https://career-fixture.invalid/lin" in html
        assert "<img" not in html and "<svg" not in html
        assert all(label in html for label in ("Phone:", "Email:", "Location:"))
        assert "> to <" not in html
        assert "> – <" in html
        assert "<time>2022-01</time> <time>至今</time>" in html
        assert "<time>2020-01</time> – <time>2021-12</time>" in html


def test_one_page_compaction_removes_low_priority_content_before_touching_typography() -> None:
    document = _resume_document()
    compacted = compact_resume_document(document, max_cost=7)
    after_claims = [bullet.text for item in compacted.projects + compacted.experience for bullet in item.bullets]

    assert "整理低优先级内部工具文档。" not in after_claims
    assert "负责发布控制自动化。" in after_claims
    assert compacted.summary == document.summary
    assert compacted.skills == []
    assert compacted.render_policy.minimum_body_font_pt >= 10.0
    assert compacted.render_policy.minimum_margin_mm >= 12.0
    assert compacted.render_policy == document.render_policy
