"""Render canonical resume documents with curated local assets only."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Mapping

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_ALLOWED_TEMPLATES = frozenset({"ats-simple", "human-readable"})
_FONT_ROOT = Path("/usr/share/fonts")
_FONT_NAMES = (
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJKsc-Regular.otf",
    "NotoSansSC-Regular.otf",
    "SourceHanSansSC-Regular.otf",
    "SourceHanSansCN-Regular.otf",
)


def _asset_root() -> Path:
    """Locate curated assets in a source checkout or installed data directory."""
    module = Path(__file__).resolve()
    candidates = [
        candidate
        for parent in module.parents
        for candidate in (parent / "assets", parent / "src" / "china_targeted_resume" / "assets")
    ]
    try:
        installed = distribution("china-targeted-resume")
        candidates.extend(
            (
                Path(installed.locate_file("assets")),
                Path(installed.locate_file("china_targeted_resume/assets")),
            )
        )
    except PackageNotFoundError:
        pass
    candidates.extend(
        (
            Path(sys.prefix) / "share" / "china-targeted-resume" / "assets",
            Path("/usr/local/share/china-targeted-resume/assets"),
            Path("/usr/share/china-targeted-resume/assets"),
        )
    )
    for candidate in candidates:
        if candidate.joinpath("templates").is_dir() and candidate.joinpath("styles").is_dir():
            return candidate.resolve()
    raise FileNotFoundError("project-local resume templates and styles were not found")


def _font_path() -> Path:
    if not _FONT_ROOT.is_dir():
        raise FileNotFoundError("/usr/share/fonts is unavailable")
    by_name = {path.name: path for path in sorted(_FONT_ROOT.rglob("*")) if path.is_file()}
    for name in _FONT_NAMES:
        if name in by_name:
            return by_name[name].resolve()
    for path in sorted(_FONT_ROOT.rglob("*")):
        lowered = path.name.lower()
        if path.is_file() and path.suffix.lower() in {".otf", ".ttf", ".ttc"} and (
            "notosanscjk" in lowered or "sourcehansanssc" in lowered or "sourcehansanscn" in lowered
        ):
            return path.resolve()
    raise FileNotFoundError("Noto Sans CJK SC or Source Han Sans SC is not installed under /usr/share/fonts")


def _document_context(document: Any) -> dict[str, Any]:
    if hasattr(document, "model_dump"):
        value = document.model_dump(mode="json")
    elif isinstance(document, Mapping):
        value = dict(document)
    else:
        raise TypeError("document must be a ResumeDocument or JSON mapping")
    if not isinstance(value, dict):
        raise TypeError("serialized ResumeDocument must be a JSON object")
    return value


def render_html(document: Any, template: str = "human-readable") -> str:
    """Render a ResumeDocument into self-contained HTML with a local CJK font."""
    if template not in _ALLOWED_TEMPLATES:
        raise ValueError(f"unknown template {template!r}; expected one of {sorted(_ALLOWED_TEMPLATES)}")

    root = _asset_root()
    template_path = root / "templates" / f"{template}.html.j2"
    base_path = root / "styles" / "base.css"
    theme_path = root / "styles" / f"{template}.css"
    required_assets = (
        template_path,
        root / "templates" / "ats-simple.html.j2",
        base_path,
        theme_path,
    )
    for path in required_assets:
        if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
            raise FileNotFoundError(f"required local rendering asset is missing or unsafe: {path}")

    font = _font_path()
    font_format = "opentype" if font.suffix.lower() == ".otf" else "truetype"
    font_css = (
        "@font-face { font-family: 'Resume CJK'; font-style: normal; font-weight: 100 900; "
        f"font-display: block; src: url('{font.as_uri()}') format('{font_format}'); }}\n"
        ":root { --font-sans: 'Resume CJK', sans-serif; --resume-font: 'Resume CJK', sans-serif; }\n"
        "html, body { font-family: var(--resume-font); }\n"
    )
    environment = Environment(
        loader=FileSystemLoader(str(root / "templates"), followlinks=False),
        autoescape=select_autoescape(("html", "xml"), default=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        auto_reload=False,
    )
    context = _document_context(document)
    context.update(
        base_css=base_path.read_text(encoding="utf-8") + "\n" + font_css,
        theme_css=theme_path.read_text(encoding="utf-8"),
    )
    return environment.get_template(template_path.name).render(**context)
