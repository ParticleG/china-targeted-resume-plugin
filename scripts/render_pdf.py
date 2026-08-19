#!/usr/bin/env python3
"""Deterministic JSON wrapper for rendering and inspecting a resume PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from china_targeted_resume.models import ResumeDocument
from china_targeted_resume.rendering.inspect import InspectionConfig
from china_targeted_resume.rendering.pdf import render_with_compaction


def _load(path: str | None) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def _default_inspection(document: ResumeDocument) -> InspectionConfig:
    policy = document.render_policy
    expected_links = tuple(str(link.url) for link in document.contact.links)
    section_headings = (
        (document.summary, "Summary"),
        (document.skills, "Skills"),
        (document.experience, "Experience"),
        (document.projects, "Projects"),
        (document.education, "Education"),
        (document.honors, "Honors"),
        (document.contact.links, "Links"),
    )
    expected_headings = tuple(heading for content, heading in section_headings if content)
    return InspectionConfig(
        target_pages=policy.target_pages,
        expected_name=document.contact.name,
        expected_headings=expected_headings,
        expected_links=expected_links,
        minimum_body_font_pt=policy.minimum_body_font_pt,
        minimum_margin_mm=policy.minimum_margin_mm,
        require_mailto_link=document.contact.email is not None,
        require_https_link=bool(expected_links),
    )


def main() -> int:
    try:
        payload = _load(sys.argv[1] if len(sys.argv) > 1 else None)
        document = ResumeDocument.model_validate(payload["document"])
        revisions = [ResumeDocument.model_validate(item) for item in payload.get("revised_documents", [])]
        config_value = payload.get("inspection")
        config = InspectionConfig.from_mapping(config_value) if config_value is not None else _default_inspection(document)
        result = render_with_compaction(
            document,
            payload["output_pdf"],
            inspection_config=config,
            template=payload.get("template", document.render_policy.template),
            preview_path=payload.get("preview_png"),
            revised_documents=revisions,
            max_attempts=int(payload.get("max_attempts", 1 + len(revisions))),
            margin_mm=float(payload.get("margin_mm", document.render_policy.minimum_margin_mm)),
        )
        output = {
            "success": result.success,
            "pdf_path": str(result.pdf_path),
            "preview_paths": [str(path) for path in result.preview_paths],
            "attempts": result.attempts,
            "validation": result.validation.model_dump(mode="json") if result.validation is not None else None,
        }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if result.success else 2
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
