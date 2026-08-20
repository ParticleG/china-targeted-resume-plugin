"""Deterministic structural and visual-quality checks for rendered PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import pymupdf

from china_targeted_resume.models import ValidationReport

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PLACEHOLDER_RE = re.compile(
    r"\{\{.*?\}\}|"
    r"(?i:\b(?:TODO|TBD|FIXME|PLACEHOLDER|LOREM\s+IPSUM|YOUR[_ ](?:NAME|EMAIL))\b)|"
    r"\bTARGET\b|待填写|此处填写"
)
_BULLET_RE = re.compile(r"^\s*[•·▪◦‣⁃*-]\s+")
_DATE_LINE_RE = re.compile(
    r"(?:\b(?:19|20)\d{2}(?:[-./]\d{1,2})?\b|至今|\bpresent\b)",
    re.I,
)


@dataclass(frozen=True, slots=True)
class InspectionConfig:
    target_pages: int = 2
    minimum_pages: int = 1
    expected_name: str = ""
    expected_headings: tuple[str, ...] = ()
    expected_links: tuple[str, ...] = ()
    minimum_body_font_pt: float = 10.0
    minimum_margin_mm: float = 12.0
    require_mailto_link: bool = True
    require_https_link: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_pages <= self.target_pages <= 6:
            raise ValueError("page bounds must satisfy 1 <= minimum_pages <= target_pages <= 6")
        if not 10 <= self.minimum_body_font_pt <= 16:
            raise ValueError("minimum_body_font_pt must be between 10 and 16")
        if not 12 <= self.minimum_margin_mm <= 30:
            raise ValueError("minimum_margin_mm must be between 12 and 30")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InspectionConfig":
        allowed = {field.name for field in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown inspection settings: {sorted(unknown)}")
        normalized = dict(value)
        for key in ("expected_headings", "expected_links"):
            if key in normalized:
                normalized[key] = tuple(normalized[key])
        return cls(**normalized)


def _check(checks: dict[str, bool], errors: list[str], name: str, passed: bool, message: str) -> None:
    checks[name] = passed
    if not passed:
        errors.append(message)


def _uri_from_link(link: Mapping[str, Any]) -> str | None:
    uri = link.get("uri")
    return str(uri) if uri else None


def inspect_pdf(path: str | Path, config: InspectionConfig | Mapping[str, Any]) -> ValidationReport:
    """Inspect a PDF and return a fail-closed ValidationReport."""
    if isinstance(config, Mapping):
        config = InspectionConfig.from_mapping(config)
    pdf_path = Path(path)
    checks: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    fonts: set[str] = set()
    embedded_fonts: set[str] = set()
    links: set[str] = set()
    page_details: list[dict[str, Any]] = []
    all_lines: list[tuple[int, float, float, str, tuple[float, float, float, float]]] = []
    body_sizes: list[float] = []
    detached_column_lines: list[str] = []

    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        return ValidationReport(
            success=False,
            checks={"pdf_opened": False},
            errors=[f"PDF could not be opened: {exc}"],
            pages=0,
        )

    with document:
        _check(checks, errors, "pdf_opened", document.is_pdf and not document.is_encrypted, "file is not a readable, unencrypted PDF")
        if not document.is_pdf or document.is_encrypted:
            return ValidationReport(
                success=False,
                checks=checks,
                errors=list(errors),
                pages=document.page_count,
            )
        page_count = document.page_count
        _check(checks, errors, "page_minimum", page_count >= config.minimum_pages, f"PDF has {page_count} pages; target is at least {config.minimum_pages}")
        _check(checks, errors, "page_limit", page_count <= config.target_pages, f"PDF has {page_count} pages; target is at most {config.target_pages}")

        for page_number, page in enumerate(document):
            width, height = float(page.rect.width), float(page.rect.height)
            media = page.mediabox
            crop = page.cropbox
            a4_ok = abs(width - 595.28) <= 2.0 and abs(height - 841.89) <= 2.0
            boxes_ok = (
                float(media.x0) <= float(crop.x0) <= float(crop.x1) <= float(media.x1)
                and float(media.y0) <= float(crop.y0) <= float(crop.y1) <= float(media.y1)
            )
            page_ok = width > 0 and height > 0 and a4_ok and boxes_ok
            page_dict = page.get_text("dict", sort=False)
            page_lines: list[tuple[float, float, str, tuple[float, float, float, float]]] = []
            page_boxes: list[tuple[float, float, float, float]] = []
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    bbox = tuple(float(value) for value in line.get("bbox", (0, 0, 0, 0)))
                    if not text:
                        continue
                    page_lines.append((bbox[1], bbox[0], text, bbox))
                    page_boxes.append(bbox)
                    all_lines.append((page_number, bbox[1], bbox[0], text, bbox))
                    for span in spans:
                        span_text = str(span.get("text", "")).strip()
                        if span_text:
                            body_sizes.append(float(span.get("size", 0.0)))
                            fonts.add(str(span.get("font", "unknown")))

            for font in page.get_fonts(full=True):
                xref = int(font[0])
                font_type = str(font[2] or "")
                name = str(font[3] or font[4] or f"{font_type}@{xref}")
                fonts.add(name)
                if font_type.casefold() == "type3":
                    # Chromium represents subsetted CJK glyph programs as
                    # in-document Type3 CharProcs. They are self-contained and
                    # therefore satisfy the renderer-safe font requirement.
                    embedded_fonts.add(name)
                elif xref > 0:
                    try:
                        extracted = document.extract_font(xref)
                        if extracted and len(extracted) >= 4 and extracted[3]:
                            embedded_fonts.add(name)
                    except Exception:
                        pass
            for link in page.get_links():
                uri = _uri_from_link(link)
                if uri:
                    links.add(uri)

            for y, x, text, bbox in page_lines:
                if x < width * 0.62 or not _DATE_LINE_RE.search(text):
                    continue
                tolerance = max(6.0, bbox[3] - bbox[1])
                has_left_peer = any(
                    other_x < width * 0.55
                    and other_text != text
                    and abs(other_y - y) <= tolerance
                    for other_y, other_x, other_text, _other_bbox in page_lines
                )
                if has_left_peer:
                    detached_column_lines.append(
                        f"page {page_number + 1}: {text}"
                    )

            bounds_ok = all(
                -0.5 <= x0 <= x1 <= width + 0.5 and -0.5 <= y0 <= y1 <= height + 0.5
                for x0, y0, x1, y1 in page_boxes
            )
            page_ok = page_ok and bounds_ok
            margin_pt = config.minimum_margin_mm * 72.0 / 25.4
            if page_boxes:
                left = min(box[0] for box in page_boxes)
                top = min(box[1] for box in page_boxes)
                right = width - max(box[2] for box in page_boxes)
                bottom = height - max(box[3] for box in page_boxes)
                margins = (left, top, right, bottom)
                margins_ok = all(value >= margin_pt - 1.5 for value in margins)
            else:
                margins = (0.0, 0.0, 0.0, 0.0)
                margins_ok = False
            page_details.append(
                {
                    "page": page_number + 1,
                    "width_pt": round(width, 2),
                    "height_pt": round(height, 2),
                    "a4_ok": a4_ok,
                    "page_boxes_ok": boxes_ok,
                    "margins_pt": [round(value, 2) for value in margins],
                    "bounds_ok": bounds_ok,
                    "margins_ok": margins_ok,
                }
            )
            checks[f"page_{page_number + 1}_bounds"] = page_ok
            checks[f"page_{page_number + 1}_margins"] = margins_ok
            if not page_ok:
                errors.append(f"page {page_number + 1} is not A4, has invalid page boxes, or contains out-of-bounds text")
            if not margins_ok:
                errors.append(f"page {page_number + 1} violates the minimum {config.minimum_margin_mm:g} mm content margin")

            ordered = sorted(page_lines)
            for index, (y, _x, text, bbox) in enumerate(ordered):
                if y > height - 42 and (_BULLET_RE.match(text) or len(text) < 24):
                    warnings.append(f"page {page_number + 1}: possible orphan line near page bottom at y={y:.1f}")
                if index + 1 < len(ordered):
                    next_y, _next_x, next_text, next_bbox = ordered[index + 1]
                    vertical_overlap = min(bbox[3], next_bbox[3]) - max(bbox[1], next_bbox[1])
                    horizontal_overlap = min(bbox[2], next_bbox[2]) - max(bbox[0], next_bbox[0])
                    if vertical_overlap > 1 and horizontal_overlap > 1 and text != next_text:
                        warnings.append(f"page {page_number + 1}: possible overlapping text near y={y:.1f}")

        extracted_text = "\n".join(line[3] for line in all_lines)
        _check(checks, errors, "text_extracted", bool(extracted_text.strip()), "PDF contains no extractable text")
        _check(checks, errors, "expected_name", not config.expected_name or config.expected_name in extracted_text, "expected resume name is absent from extracted text")
        missing_headings = [heading for heading in config.expected_headings if heading not in extracted_text]
        _check(checks, errors, "expected_headings", not missing_headings, f"expected headings are absent: {missing_headings}")
        heading_positions = [extracted_text.find(heading) for heading in config.expected_headings]
        reading_order_ok = (
            all(position >= 0 for position in heading_positions)
            and heading_positions == sorted(heading_positions)
            and not detached_column_lines
        )
        _check(
            checks,
            errors,
            "reading_order",
            reading_order_ok,
            "expected headings are out of order or date metadata forms a detached right column",
        )

        expected_cjk = _CJK_RE.findall(config.expected_name + "".join(config.expected_headings))
        extracted_cjk = _CJK_RE.findall(extracted_text)
        cjk_ok = "�" not in extracted_text and (not expected_cjk or (bool(extracted_cjk) and set(expected_cjk).issubset(set(extracted_cjk))))
        _check(checks, errors, "cjk_extraction", cjk_ok, "CJK extraction is missing expected characters or contains replacement glyphs")
        _check(checks, errors, "fonts_embedded", bool(embedded_fonts), "no embedded font program was found")

        minimum_size = min(body_sizes, default=0.0)
        font_ok = bool(body_sizes) and minimum_size + 0.15 >= config.minimum_body_font_pt
        _check(checks, errors, "minimum_body_font", font_ok, f"minimum extracted font is {minimum_size:.2f} pt; configured minimum is {config.minimum_body_font_pt:.2f} pt")
        placeholder_matches = sorted(set(match.group(0) for match in _PLACEHOLDER_RE.finditer(extracted_text)))
        _check(checks, errors, "no_placeholders", not placeholder_matches, f"placeholder patterns remain: {placeholder_matches}")

        expected_links_ok = all(expected in links for expected in config.expected_links)
        _check(checks, errors, "expected_links", expected_links_ok, "one or more expected link annotations are absent")
        mailto_ok = not config.require_mailto_link or any(link.lower().startswith("mailto:") for link in links)
        https_ok = not config.require_https_link or any(link.lower().startswith("https://") for link in links)
        _check(checks, errors, "mailto_link", mailto_ok, "mailto link annotation is absent")
        _check(checks, errors, "https_link", https_ok, "HTTPS link annotation is absent")

    return ValidationReport(
        success=not errors,
        checks=checks,
        errors=errors,
        warnings=sorted(set(warnings)),
        pages=page_count,
        extracted_text=extracted_text,
        fonts=sorted(fonts),
        links=sorted(links),
        details={
            "embedded_fonts": sorted(embedded_fonts),
            "minimum_font_pt": round(min(body_sizes, default=0.0), 2),
            "placeholder_matches": placeholder_matches,
            "detached_column_lines": detached_column_lines,
            "pages": page_details,
        },
    )
