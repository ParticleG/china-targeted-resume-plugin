from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pytest


from china_targeted_resume.composition import compact_resume_document
from china_targeted_resume.models import ResumeDocument, ValidationReport
from china_targeted_resume.rendering import render_html
from china_targeted_resume.rendering.inspect import InspectionConfig, inspect_pdf
from china_targeted_resume.rendering.pdf import PdfRenderResult, render_with_compaction

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



def _blank_pdf(path: Path, pages: int) -> None:
    document = pymupdf.open()
    try:
        for _ in range(pages):
            document.new_page(width=595.28, height=841.89)
        document.save(path)
    finally:
        document.close()


def test_exact_page_inspection_reports_underfill_and_overflow_separately(tmp_path: Path) -> None:
    one_page = tmp_path / "one-page.pdf"
    two_pages = tmp_path / "two-pages.pdf"
    _blank_pdf(one_page, 1)
    _blank_pdf(two_pages, 2)

    exact_one_page = InspectionConfig(target_pages=1, minimum_pages=1)
    one_page_report = inspect_pdf(one_page, exact_one_page)
    overflow_report = inspect_pdf(two_pages, exact_one_page)
    underfill_report = inspect_pdf(one_page, InspectionConfig(target_pages=2, minimum_pages=2))

    assert one_page_report.checks["page_minimum"] and one_page_report.checks["page_limit"]
    assert overflow_report.checks["page_minimum"] and not overflow_report.checks["page_limit"]
    assert not underfill_report.checks["page_minimum"] and underfill_report.checks["page_limit"]


def test_inspection_page_bounds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="minimum_pages"):
        InspectionConfig(target_pages=1, minimum_pages=2)


@pytest.mark.parametrize("final_success", [True, False])
def test_compaction_result_exposes_the_last_rendered_document(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, final_success: bool) -> None:
    initial = _resume_document()
    revised = initial.model_copy(update={"headline": "修订后的高级平台工程师"})
    rendered_documents: list[ResumeDocument] = []
    reports = iter(
        [
            ValidationReport(success=False, errors=["first attempt rejected"]),
            ValidationReport(success=final_success, errors=[] if final_success else ["last attempt rejected"]),
        ]
    )

    def fake_render(document: ResumeDocument, output_path: str | Path, **_: object) -> PdfRenderResult:
        rendered_documents.append(document)
        return PdfRenderResult(Path(output_path), (), document=document)

    monkeypatch.setattr("china_targeted_resume.rendering.pdf.render_pdf", fake_render)
    monkeypatch.setattr("china_targeted_resume.rendering.inspect.inspect_pdf", lambda *_: next(reports))

    result = render_with_compaction(
        initial,
        tmp_path / "resume.pdf",
        inspection_config=InspectionConfig(target_pages=1),
        revised_documents=[revised],
        max_attempts=2,
    )

    assert rendered_documents == [initial, revised]
    assert result.document is revised
    assert result.success is final_success


def test_render_retry_removes_only_stale_numbered_previews(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    initial = _resume_document()
    revised = initial.model_copy(update={"headline": "Compact retry"})
    preview = tmp_path / "resume.preview.png"
    numbered_preview = tmp_path / "resume.preview-2.png"
    attempts = 0

    def fake_render(
        document: ResumeDocument,
        output_path: str | Path,
        **_: object,
    ) -> PdfRenderResult:
        nonlocal attempts
        attempts += 1
        preview.write_text(f"attempt {attempts}", encoding="utf-8")
        previews = (preview,)
        if attempts == 1:
            numbered_preview.write_text("stale second page", encoding="utf-8")
            previews = (preview, numbered_preview)
        return PdfRenderResult(Path(output_path), previews, document=document)

    reports = iter(
        [
            ValidationReport(success=False, errors=["first attempt rejected"]),
            ValidationReport(success=True),
        ]
    )
    monkeypatch.setattr(
        "china_targeted_resume.rendering.pdf.render_pdf",
        fake_render,
    )
    monkeypatch.setattr(
        "china_targeted_resume.rendering.inspect.inspect_pdf",
        lambda *_: next(reports),
    )

    result = render_with_compaction(
        initial,
        tmp_path / "resume.pdf",
        preview_path=preview,
        inspection_config=InspectionConfig(target_pages=2),
        revised_documents=[revised],
        max_attempts=2,
    )

    assert result.preview_paths == (preview,)
    assert preview.read_text(encoding="utf-8") == "attempt 2"
    assert not numbered_preview.exists()