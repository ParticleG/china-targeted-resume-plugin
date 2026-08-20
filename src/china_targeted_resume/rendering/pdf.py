"""Print local resume HTML to PDF and raster previews."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from playwright.sync_api import sync_playwright

from .html import render_html


@dataclass(frozen=True, slots=True)
class PdfRenderResult:
    pdf_path: Path
    preview_paths: tuple[Path, ...]
    document: Any
    attempts: int = 1
    validation: Any | None = None

    @property
    def success(self) -> bool:
        if self.validation is None:
            return False
        if hasattr(self.validation, "success"):
            return bool(self.validation.success)
        if isinstance(self.validation, dict):
            return bool(self.validation.get("success", False))
        return False


@contextmanager
def _private_umask() -> Any:
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def _prepare_output(path: str | os.PathLike[str]) -> Path:
    output = Path(path).expanduser().absolute()
    if not output.parent.exists():
        with _private_umask():
            output.parent.mkdir(mode=0o700, parents=True)
    current = output.parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"output directory must not traverse a symlink: {current}")
        current = current.parent
    directory_mode = stat.S_IMODE(output.parent.stat().st_mode)
    if directory_mode & 0o077:
        raise PermissionError(f"output directory must be private (0700): {output.parent}")
    if output.is_symlink():
        raise ValueError(f"refusing to overwrite symlink output: {output}")
    if output.exists():
        if not output.is_file():
            raise ValueError(f"output is not a regular file: {output}")
        os.chmod(output, 0o600)
    return output


def _render_previews(pdf_path: Path, preview_path: str | os.PathLike[str], dpi: int) -> tuple[Path, ...]:
    if not 96 <= dpi <= 300:
        raise ValueError("preview dpi must be between 96 and 300")
    base = _prepare_output(preview_path)
    paths: list[Path] = []
    with pymupdf.open(pdf_path) as document:
        for index, page in enumerate(document):
            path = base if index == 0 else base.with_name(f"{base.stem}-{index + 1}{base.suffix}")
            path = _prepare_output(path)
            pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
            with _private_umask():
                pixmap.save(path)
            os.chmod(path, 0o600)
            paths.append(path)
    return tuple(paths)


def render_pdf(
    document: Any,
    output_path: str | os.PathLike[str],
    *,
    template: str = "human-readable",
    preview_path: str | os.PathLike[str] | None = None,
    preview_dpi: int = 150,
    margin_mm: float = 12.0,
    chromium_executable: str | os.PathLike[str] | None = None,
) -> PdfRenderResult:
    """Render one document locally; this function does not assert content validity."""
    if not 5.0 <= margin_mm <= 30.0:
        raise ValueError("margin_mm must be between 5 and 30")
    output = _prepare_output(output_path)
    html = render_html(document, template)
    launch_args: dict[str, Any] = {"headless": True}
    if chromium_executable is not None:
        launch_args["executable_path"] = str(chromium_executable)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_args)
        try:
            page = browser.new_page(locale="zh-CN", timezone_id="Asia/Shanghai")
            # Establish a local-file origin so Chromium may load the explicitly
            # selected /usr/share/fonts face without a network or temporary HTML file.
            page.goto(Path(__file__).resolve().as_uri(), wait_until="commit")
            page.set_content(html, wait_until="load")
            page.emulate_media(media="print")
            page.evaluate("() => document.fonts.ready")
            margin = f"{margin_mm:g}mm"
            with _private_umask():
                page.pdf(
                    path=str(output),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=False,
                    display_header_footer=False,
                    margin={"top": margin, "right": margin, "bottom": margin, "left": margin},
                    tagged=True,
                    outline=True,
                )
        finally:
            browser.close()

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Chromium did not produce a non-empty PDF")
    os.chmod(output, 0o600)
    previews = _render_previews(output, preview_path, preview_dpi) if preview_path is not None else ()
    return PdfRenderResult(output, previews, document=document)


def render_with_compaction(
    document: Any,
    output_path: str | os.PathLike[str],
    *,
    inspection_config: Any,
    template: str = "human-readable",
    preview_path: str | os.PathLike[str] | None = None,
    compact: Callable[[Any, Any, int], Any | None] | None = None,
    revised_documents: Iterable[Any] = (),
    max_attempts: int = 3,
    margin_mm: float = 12.0,
) -> PdfRenderResult:
    """Render, inspect, and optionally retry with bounded document revisions."""
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    from .inspect import inspect_pdf

    revisions = iter(revised_documents)
    current = document
    last: PdfRenderResult | None = None
    for attempt in range(1, max_attempts + 1):
        rendered = render_pdf(
            current,
            output_path,
            template=template,
            preview_path=preview_path,
            margin_mm=margin_mm,
        )
        if last is not None:
            stale_previews = set(last.preview_paths) - set(rendered.preview_paths)
            for stale_preview in stale_previews:
                stale_preview.unlink(missing_ok=True)
        report = inspect_pdf(rendered.pdf_path, inspection_config)
        last = PdfRenderResult(
            pdf_path=rendered.pdf_path,
            preview_paths=rendered.preview_paths,
            document=current,
            attempts=attempt,
            validation=report,
        )
        if last.success:
            return last
        if attempt == max_attempts:
            break
        try:
            revised = next(revisions)
        except StopIteration:
            revised = compact(current, report, attempt) if compact is not None else None
        if revised is None:
            break
        current = revised
    if last is None:
        raise RuntimeError("no render attempt was made")
    return last
