"""Single-read, policy-aware Markdown structure and exact source spans.

The source body retained by :class:`SourceDocument` is process-local proof
material.  Persistent navigation data must be produced with
:meth:`SourceDocument.navigation_metadata`, which never includes source text.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token

from china_targeted_resume.models import DisclosureLevel, FactState


_FACT_RE = re.compile(r"(?<![A-Za-z0-9])(F[1-6])(?![A-Za-z0-9])", re.I)
_DISCLOSURE_RE = re.compile(r"(?<![A-Za-z0-9])(P[0-3])(?![A-Za-z0-9])", re.I)
_FACT_LABEL_RE = re.compile(
    r"(?:fact(?:\s+(?:status|state|level))?|事实(?:状态|级别|等级))"
    r"[^\n]{0,48}?(F[1-6])(?![A-Za-z0-9])",
    re.I,
)
_DISCLOSURE_LABEL_RE = re.compile(
    r"(?:publicity|disclosure(?:\s+(?:status|level))?|公开(?:状态|级别|等级|范围))"
    r"[^\n]{0,48}?(P[0-3])(?![A-Za-z0-9])",
    re.I,
)
_SENSITIVE_PATH_RE = re.compile(
    r"(?:^|[-_.])(?:secret|secrets|credential|credentials|password|passwords|"
    r"private[-_]?key|token|tokens|\.env)(?:$|[-_.])",
    re.I,
)
_SECRET_CONTENT_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|client[_ -]?secret)\b\s*[:=]|"
    r"\b(?:sk|ghp|xox[baprs])_[A-Za-z0-9_-]{12,}|"
    r"\b(?:TOKEN|LICENSE_BLOB)-FICTIONAL-[A-Za-z0-9_-]+)",
    re.I,
)
_CONTACT_RE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d))"
)
_EXAMPLE_HEADING_RE = re.compile(
    r"(?:^|\b)(?:examples?|samples?|counterexamples?|negative examples?|"
    r"示例|样例|范例|举例|反例|错误示例)(?:\b|$)",
    re.I,
)
_TEMPLATE_HEADING_RE = re.compile(
    r"(?:^|\b)(?:templates?|boilerplate|fill[- ]?in|占位模板|模板|范本)(?:\b|$)",
    re.I,
)
_EXAMPLE_BLOCK_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:examples?|samples?|counterexamples?|"
    r"示例|样例|范例|反例|错误示例)\s*[:：]",
    re.I,
)
_TEMPLATE_BLOCK_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:templates?|boilerplate|占位模板|模板|范本)\s*[:：]",
    re.I,
)
_NEGATIVE_RE = re.compile(
    r"(?:\b(?:do\s+not|don't|must\s+not|never\s+(?:claim|infer|include)|"
    r"not\s+evidence|negative\s+instructions?)\b|"
    r"(?:不得|不要|禁止|切勿)(?:声称|推断|写入|纳入|作为|使用)|"
    r"(?:不是|不作为|不得作为)(?:候选人)?(?:证据|事实|经历))",
    re.I,
)
_HTML_CONTAINER_RE = re.compile(
    r"<\s*(/?)\s*(details|summary|div|section|article|aside|template|pre|figure)\b[^>]*>",
    re.I,
)
_LINK_RE = re.compile(r"!?\[([^]\n]*)\]\(([^)\s]+)(?:\s+[\"'][^\n]*[\"'])?\)")
_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>]+)>", re.I)


class MarkdownStructureError(ValueError):
    """The source cannot safely be represented by the structural boundary."""


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Inclusive one-based lines and an exact half-open UTF-8 byte span."""

    path: str
    source_hash: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("source lines must be ordered and one-based")
        if self.start_byte < 0 or self.end_byte < self.start_byte:
            raise ValueError("source bytes must be an ordered half-open span")

    def contains_line(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    def contains(self, other: SourceLocation) -> bool:
        return (
            self.path == other.path
            and self.source_hash == other.source_hash
            and self.start_byte <= other.start_byte
            and other.end_byte <= self.end_byte
        )


@dataclass(frozen=True, slots=True)
class HeadingAncestor:
    """A duplicate-safe node in a block's complete heading ancestry."""

    identity: str
    heading: str
    level: int
    location: SourceLocation
    occurrence: int = 0
    anchor: str = ""
    fact_state: FactState | None = None
    disclosure: DisclosureLevel | None = None

    @property
    def title(self) -> str:
        return self.heading


@dataclass(frozen=True, slots=True)
class StructuralFlags:
    """Structural trust flags evaluated before retrieval."""

    inside_fence: bool = False
    inside_blockquote: bool = False
    inside_html: bool = False
    inside_example: bool = False
    inside_template: bool = False
    inside_quoted: bool = False
    negative_instruction: bool = False
    secret_path: bool = False
    secret_content: bool = False
    malformed: bool = False
    exclusion_reasons: tuple[str, ...] = ()

    @property
    def excluded_from_evidence(self) -> bool:
        return bool(self.exclusion_reasons)

    @property
    def inside_block_quote(self) -> bool:
        return self.inside_blockquote

    @property
    def example(self) -> bool:
        return self.inside_example

    @property
    def is_example(self) -> bool:
        return self.inside_example

    @property
    def template(self) -> bool:
        return self.inside_template

    @property
    def is_template(self) -> bool:
        return self.inside_template

    @property
    def quoted(self) -> bool:
        return self.inside_quoted

    @property
    def is_quoted(self) -> bool:
        return self.inside_quoted


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    """A source-backed leaf block with policy and structural context."""

    identity: str
    kind: str
    location: SourceLocation
    heading_ancestry: tuple[str, ...]
    heading_ancestor_nodes: tuple[HeadingAncestor, ...]
    flags: StructuralFlags
    text: str
    plain_text: str
    section_identity: str | None = None
    fact_state: FactState | None = None
    disclosure: DisclosureLevel | None = None
    effective_fact_state: FactState | None = None
    effective_disclosure: DisclosureLevel | None = None
    list_depth: int = 0
    table_identity: str | None = None
    table_location: SourceLocation | None = None
    row_index: int | None = None
    cells: tuple[str, ...] = ()
    fact_policy_explicit: bool = False
    disclosure_policy_explicit: bool = False

    @property
    def block_kind(self) -> str:
        return self.kind

    @property
    def exact_quote(self) -> str:
        return self.text

    @property
    def heading_path(self) -> tuple[str, ...]:
        return self.heading_ancestry

    @property
    def effective_fact_policy(self) -> FactState:
        return self.effective_fact_state or FactState.F5

    @property
    def effective_disclosure_policy(self) -> DisclosureLevel:
        return self.effective_disclosure or DisclosureLevel.P3

    @property
    def has_explicit_fact_policy(self) -> bool:
        return self.fact_policy_explicit

    @property
    def has_explicit_disclosure_policy(self) -> bool:
        return self.disclosure_policy_explicit

    @property
    def eligible_for_evidence(self) -> bool:
        return not self.flags.excluded_from_evidence


def source_map_block_is_safe(block: MarkdownBlock) -> bool:
    """Return whether block metadata may enter a persistent source map."""
    flags = block.flags
    if (
        flags.inside_fence
        or flags.inside_blockquote
        or flags.inside_html
        or flags.inside_example
        or flags.inside_template
        or flags.inside_quoted
        or flags.negative_instruction
        or flags.secret_path
        or flags.secret_content
        or flags.malformed
    ):
        return False
    return not (
        block.has_explicit_fact_policy
        and block.effective_fact_policy is FactState.F6
        or block.has_explicit_disclosure_policy
        and block.effective_disclosure_policy is DisclosureLevel.P3
    )


@dataclass(frozen=True, slots=True)
class MarkdownSection:
    """A heading section; ``blocks`` contains directly owned blocks only."""

    identity: str
    heading: str
    level: int
    anchor: str
    occurrence: int
    location: SourceLocation
    content_location: SourceLocation
    ancestors: tuple[HeadingAncestor, ...]
    heading_ancestry: tuple[str, ...]
    heading_ancestor_nodes: tuple[HeadingAncestor, ...]
    flags: StructuralFlags
    blocks: tuple[MarkdownBlock, ...] = ()
    fact_state: FactState | None = None
    disclosure: DisclosureLevel | None = None
    effective_fact_state: FactState | None = None
    effective_disclosure: DisclosureLevel | None = None

    @property
    def title(self) -> str:
        return self.heading

    @property
    def section_anchor(self) -> str:
        return self.anchor

    @property
    def heading_path(self) -> tuple[str, ...]:
        return self.heading_ancestry

    @property
    def effective_fact_policy(self) -> FactState:
        return self.effective_fact_state or FactState.F5

    @property
    def effective_disclosure_policy(self) -> DisclosureLevel:
        return self.effective_disclosure or DisclosureLevel.P3

    @property
    def has_explicit_fact_policy(self) -> bool:
        return self.effective_fact_state is not None

    @property
    def has_explicit_disclosure_policy(self) -> bool:
        return self.effective_disclosure is not None


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """An exact source revision and its parsed structural tree."""

    path: str
    source_hash: str
    source_bytes: bytes = field(repr=False)
    text: str = field(repr=False)
    sections: tuple[MarkdownSection, ...]
    blocks: tuple[MarkdownBlock, ...]
    warnings: tuple[str, ...] = ()
    document_fact_state: FactState | None = None
    document_disclosure: DisclosureLevel | None = None
    _line_offsets: tuple[int, ...] = field(default=(0, 0), repr=False)

    @classmethod
    def from_path(
        cls, path: Path, *, source_root: Path | None = None
    ) -> SourceDocument:
        return parse_markdown(path, source_root=source_root)

    @classmethod
    def from_bytes(cls, data: bytes, *, path: str) -> SourceDocument:
        return parse_markdown_bytes(data, path=path)

    @property
    def validation_warnings(self) -> tuple[str, ...]:
        return self.warnings

    @property
    def document_fact_policy(self) -> FactState:
        return self.document_fact_state or FactState.F5

    @property
    def document_disclosure_policy(self) -> DisclosureLevel:
        return self.document_disclosure or DisclosureLevel.P3

    def exact_bytes(self, location: SourceLocation) -> bytes:
        self._validate_location(location)
        return self.source_bytes[location.start_byte : location.end_byte]

    def exact_text(self, location: SourceLocation) -> str:
        return self.exact_bytes(location).decode("utf-8")

    def quote(self, location: SourceLocation) -> str:
        return self.exact_text(location)

    def location_for_lines(self, start_line: int, end_line: int) -> SourceLocation:
        line_count = max(1, len(self._line_offsets) - 1)
        if start_line < 1 or end_line < start_line or end_line > line_count:
            raise ValueError("line range exceeds source document")
        return SourceLocation(
            path=self.path,
            source_hash=self.source_hash,
            start_line=start_line,
            end_line=end_line,
            start_byte=self._line_offsets[start_line - 1],
            end_byte=self._line_offsets[end_line],
        )

    def text_for_lines(self, start_line: int, end_line: int) -> str:
        return self.exact_text(self.location_for_lines(start_line, end_line))

    def section_for_line(self, line: int) -> MarkdownSection | None:
        direct = [
            item for item in self.sections if item.content_location.contains_line(line)
        ]
        if direct:
            return max(direct, key=lambda item: item.level)
        containing = [item for item in self.sections if item.location.contains_line(line)]
        return max(containing, key=lambda item: item.level, default=None)

    def block_for_span(self, start_line: int, end_line: int) -> MarkdownBlock | None:
        exact = [
            item
            for item in self.blocks
            if item.location.start_line == start_line
            and item.location.end_line == end_line
        ]
        if exact:
            return min(exact, key=lambda item: item.location.end_byte - item.location.start_byte)
        containing = [
            item
            for item in self.blocks
            if item.location.start_line <= start_line <= end_line <= item.location.end_line
        ]
        return min(
            containing,
            key=lambda item: item.location.end_byte - item.location.start_byte,
            default=None,
        )
    def block_by_identity(self, identity: str) -> MarkdownBlock | None:
        return next(
            (block for block in self.blocks if block.identity == identity),
            None,
        )

    def section_by_identity(self, identity: str) -> MarkdownSection | None:
        return next(
            (section for section in self.sections if section.identity == identity),
            None,
        )

    def owning_section(
        self, block: MarkdownBlock
    ) -> MarkdownSection | None:
        if block.section_identity is None:
            return None
        return self.section_by_identity(block.section_identity)


    def eligible_blocks(self) -> tuple[MarkdownBlock, ...]:
        return tuple(item for item in self.blocks if item.eligible_for_evidence)

    def navigation_metadata(self) -> dict[str, object]:
        """Return persistable structure without source bodies or quotes."""
        if _secret_path(self.path):
            raise MarkdownStructureError(
                "sensitive-looking source paths cannot become navigation metadata"
            )


        return {
            "path": self.path,
            "source_hash": self.source_hash,
            "warnings": list(self.warnings),
            "document_fact_policy": self.document_fact_policy.value,
            "document_disclosure_policy": (
                self.document_disclosure_policy.value
            ),
            "sections": [
                {
                    "identity": item.identity,
                    "heading": item.heading,
                    "level": item.level,
                    "anchor": item.anchor,
                    "occurrence": item.occurrence,
                    "start_line": item.location.start_line,
                    "end_line": item.location.end_line,
                    "start_byte": item.location.start_byte,
                    "end_byte": item.location.end_byte,
                    "heading_ancestry": list(item.heading_path),
                    "effective_fact_policy": (
                        item.effective_fact_policy.value
                    ),
                    "effective_disclosure_policy": (
                        item.effective_disclosure_policy.value
                    ),
                }
                for item in self.sections
                if not item.flags.excluded_from_evidence
                and not item.flags.secret_path
                and not item.flags.secret_content
                and all(
                    _CONTACT_RE.search(heading) is None
                    and _SECRET_CONTENT_RE.search(heading) is None
                    for heading in item.heading_path
                )
                and item.effective_fact_state is not FactState.F6
                and item.effective_disclosure is not DisclosureLevel.P3
            ],
        }

    def _validate_location(self, location: SourceLocation) -> None:
        if location.path != self.path or location.source_hash != self.source_hash:
            raise ValueError("source location belongs to another document revision")
        if location.end_byte > len(self.source_bytes):
            raise ValueError("source location exceeds source bytes")


@dataclass(frozen=True, slots=True)
class _Heading:
    heading: str
    level: int
    start_line0: int
    heading_end_line0: int
    content_end_line0: int
    section_end_line0: int
    identity: str
    anchor: str
    occurrence: int
    fact_state: FactState | None
    disclosure: DisclosureLevel | None
    ancestors: tuple[HeadingAncestor, ...]
    ancestry: tuple[HeadingAncestor, ...]
    effective_fact_state: FactState | None
    effective_disclosure: DisclosureLevel | None


@dataclass(frozen=True, slots=True)
class _Interval:
    start_line0: int
    end_line0: int
    malformed: bool = False

    def overlaps(self, start_line0: int, end_line0: int) -> bool:
        return self.start_line0 < end_line0 and start_line0 < self.end_line0


@dataclass(frozen=True, slots=True)
class _Locations:
    path: str
    source_hash: str
    data: bytes
    line_offsets: tuple[int, ...]

    def from_map(self, source_map: Sequence[int] | None) -> SourceLocation:
        if source_map is None or len(source_map) != 2:
            raise MarkdownStructureError("Markdown token lacks a source map")
        return self.from_zero_based(int(source_map[0]), int(source_map[1]))

    def from_zero_based(self, start_line0: int, end_line0: int) -> SourceLocation:
        line_count = max(1, len(self.line_offsets) - 1)
        if start_line0 < 0 or end_line0 <= start_line0 or end_line0 > line_count:
            raise MarkdownStructureError(
                f"invalid Markdown source map [{start_line0}, {end_line0})"
            )
        return SourceLocation(
            path=self.path,
            source_hash=self.source_hash,
            start_line=start_line0 + 1,
            end_line=end_line0,
            start_byte=self.line_offsets[start_line0],
            end_byte=self.line_offsets[end_line0],
        )

    def text(self, location: SourceLocation) -> str:
        return self.data[location.start_byte : location.end_byte].decode("utf-8")


class MarkdownStructureService:
    """Stateless façade that performs exactly one byte read per parse call."""

    def parse(
        self, path: Path, *, source_root: Path | None = None
    ) -> SourceDocument:
        return parse_markdown(path, source_root=source_root)

    def parse_bytes(self, data: bytes, *, path: str) -> SourceDocument:
        return parse_markdown_bytes(data, path=path)


DEFAULT_MARKDOWN_STRUCTURE_SERVICE = MarkdownStructureService()


def parse_markdown(
    path: Path, *, source_root: Path | None = None
) -> SourceDocument:
    """Read a Markdown file exactly once, then bind all spans to those bytes."""

    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_file():
        raise MarkdownStructureError(f"Markdown source is not a regular file: {candidate}")
    if source_root is None:
        display_path = candidate.name
    else:
        root = Path(source_root).expanduser().resolve(strict=True)
        if not candidate.is_relative_to(root):
            raise MarkdownStructureError("Markdown source escapes configured source root")
        display_path = candidate.relative_to(root).as_posix()
    try:
        with candidate.open("rb") as stream:
            data = stream.read()
    except OSError as exc:
        raise MarkdownStructureError(f"Markdown source is unreadable: {display_path}") from exc
    return parse_markdown_bytes(data, path=display_path)


def parse_markdown_bytes(data: bytes, *, path: str) -> SourceDocument:
    """Parse already-read bytes without newline or Unicode normalization."""

    if not isinstance(data, bytes):
        raise TypeError("Markdown source must be bytes")
    normalized_path = PurePosixPath(path).as_posix()
    source_path = PurePosixPath(normalized_path)
    if (
        not normalized_path
        or normalized_path == "."
        or source_path.is_absolute()
        or ".." in source_path.parts
    ):
        raise MarkdownStructureError("source path must be a safe relative POSIX path")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MarkdownStructureError(
            f"Markdown source is not valid UTF-8 at byte {exc.start}: {normalized_path}"
        ) from exc

    source_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
    offsets = _line_offsets(data)
    line_count = max(1, len(offsets) - 1)
    locations = _Locations(normalized_path, source_hash, data, offsets)
    parser = MarkdownIt("commonmark", {"html": True})
    parser.enable("table")
    try:
        tokens = parser.parse(text)
    except Exception as exc:
        raise MarkdownStructureError(f"Markdown parser rejected {normalized_path}: {exc}") from exc

    warnings: list[str] = []
    fences, fence_warnings = _fence_intervals(text, tokens, line_count)
    html, html_warnings = _html_intervals(text, line_count)
    warnings.extend(fence_warnings)
    warnings.extend(html_warnings)
    quotes = _blockquote_intervals(tokens, line_count)
    fact_markers, disclosure_markers = _document_policy_markers(
        tokens, locations, fences, html, quotes
    )
    document_fact, policy_warnings = _resolve_markers(
        fact_markers, FactState, "document fact policy"
    )
    warnings.extend(policy_warnings)
    document_disclosure, policy_warnings = _resolve_markers(
        disclosure_markers,
        DisclosureLevel,
        "document disclosure policy",
    )
    warnings.extend(policy_warnings)
    if document_fact is None:
        warnings.append("document fact policy omitted; effective default is F5")
    if document_disclosure is None:
        warnings.append(
            "document disclosure policy omitted; effective default is P3"
        )
    headings = _headings(
        tokens,
        locations,
        line_count,
        document_fact,
        document_disclosure,
        warnings,
    )
    sections = _sections(headings, locations, fences, html, quotes)
    blocks = _blocks(
        tokens,
        locations,
        headings,
        document_fact,
        document_disclosure,
        fences,
        html,
        quotes,
        warnings,
    )
    if not sections:
        location = locations.from_zero_based(0, line_count)
        identity = "section." + hashlib.sha256(
            f"{normalized_path}\0implicit-document".encode()
        ).hexdigest()[:20]
        blocks = tuple(
            replace(block, section_identity=identity) for block in blocks
        )
        in_fence = any(block.flags.inside_fence for block in blocks)
        in_quote = any(block.flags.inside_blockquote for block in blocks)
        in_html = any(block.flags.inside_html for block in blocks)
        example = any(block.flags.inside_example for block in blocks)
        template = any(block.flags.inside_template for block in blocks)
        quoted = any(block.flags.inside_quoted for block in blocks)
        negative = any(block.flags.negative_instruction for block in blocks)
        malformed = any(block.flags.malformed for block in blocks)
        secret_path = _secret_path(normalized_path)
        reasons = _reasons(
            inside_fence=in_fence,
            inside_blockquote=in_quote,
            inside_html=in_html,
            inside_example=example,
            inside_template=template,
            inside_quoted=quoted,
            negative_instruction=negative,
            secret_path=secret_path,
            secret_content=False,
            malformed=malformed,
            kind="section",
            fact=document_fact,
            disclosure=document_disclosure,
        )
        title = PurePosixPath(normalized_path).stem.replace("-", " ").strip()
        sections = (
            MarkdownSection(
                identity=identity,
                heading=title,
                level=0,
                anchor=_anchor_base(title),
                occurrence=0,
                location=location,
                content_location=location,
                ancestors=(),
                heading_ancestry=(),
                heading_ancestor_nodes=(),
                flags=_flags(
                    reasons,
                    in_fence,
                    in_quote,
                    in_html,
                    example,
                    template,
                    quoted,
                    negative,
                    secret_path,
                    False,
                    malformed,
                ),
                fact_state=None,
                disclosure=None,
                effective_fact_state=document_fact,
                effective_disclosure=document_disclosure,
            ),
        )
    by_section: dict[str, list[MarkdownBlock]] = {}
    for block in blocks:
        if block.section_identity is not None:
            by_section.setdefault(block.section_identity, []).append(block)
    sections = tuple(
        replace(item, blocks=tuple(by_section.get(item.identity, ())))
        for item in sections
    )
    return SourceDocument(
        path=normalized_path,
        source_hash=source_hash,
        source_bytes=data,
        text=text,
        sections=sections,
        blocks=blocks,
        warnings=tuple(dict.fromkeys(warnings)),
        document_fact_state=document_fact,
        document_disclosure=document_disclosure,
        _line_offsets=offsets,
    )


def _line_offsets(data: bytes) -> tuple[int, ...]:
    offsets = [0]
    offsets.extend(index + 1 for index, value in enumerate(data) if value == 0x0A)
    if offsets[-1] != len(data):
        offsets.append(len(data))
    if len(offsets) == 1:
        offsets.append(0)
    return tuple(offsets)


def _rank(value: FactState | DisclosureLevel) -> int:
    return int(value.value[1])


def _restrictive(*values):
    return max((item for item in values if item is not None), key=_rank, default=None)


def _resolve_markers(markers: Iterable[str], enum_type, context: str):
    values = {enum_type(marker.upper()) for marker in markers}
    if not values:
        return None, []
    resolved = max(values, key=_rank)
    if len(values) == 1:
        return resolved, []
    joined = ",".join(sorted(item.value for item in values))
    return resolved, [f"conflicting {context} markers ({joined}); resolved to {resolved.value}"]

def _document_policy_markers(
    tokens: Sequence[Token],
    locations: _Locations,
    fences: Sequence[_Interval],
    html: Sequence[_Interval],
    quotes: Sequence[_Interval],
) -> tuple[list[str], list[str]]:
    """Read labeled document policy only from safe top-level metadata blocks."""

    facts: list[str] = []
    disclosures: list[str] = []
    quote_depth = 0
    headings: list[tuple[int, bool]] = []
    for index, token in enumerate(tokens):
        if token.type == "blockquote_open":
            quote_depth += 1
            continue
        if token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
            continue
        if token.type == "heading_open" and quote_depth == 0:
            try:
                level = int(token.tag.removeprefix("h"))
            except ValueError:
                continue
            while headings and headings[-1][0] >= level:
                headings.pop()
            heading = _plain(_inline(tokens, index))
            inherited_exclusion = headings[-1][1] if headings else False
            excluded = inherited_exclusion or bool(
                _EXAMPLE_HEADING_RE.search(heading)
                or _TEMPLATE_HEADING_RE.search(heading)
                or _NEGATIVE_RE.search(heading)
            )
            headings.append((level, excluded))
            continue
        if (
            quote_depth
            or (headings and headings[-1][1])
            or (headings and headings[-1][0] > 2)
            or token.type not in {"paragraph_open", "tr_open"}
            or token.map is None
        ):
            continue
        try:
            location = locations.from_map(token.map)
        except MarkdownStructureError:
            continue
        start0, end0 = location.start_line - 1, location.end_line
        if any(
            interval.overlaps(start0, end0)
            for interval in (*fences, *html, *quotes)
        ):
            continue
        raw = locations.text(location)
        facts.extend(_FACT_LABEL_RE.findall(raw))
        disclosures.extend(_DISCLOSURE_LABEL_RE.findall(raw))
    return facts, disclosures


def _plain(value: str) -> str:
    value = _LINK_RE.sub(lambda match: match.group(1), value)
    value = _AUTOLINK_RE.sub(lambda match: match.group(1), value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"(?<!\\)[*_`~]", "", value)
    value = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+)", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _anchor_base(heading: str) -> str:
    value = re.sub(
        r"[^\w\- \u0080-\U0010ffff]", "", heading.casefold(), flags=re.UNICODE
    )
    return re.sub(r"\s+", "-", value.strip()) or "section"


def _inline(tokens: Sequence[Token], index: int) -> str:
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1].content
    return ""


def _headings(
    tokens: Sequence[Token],
    locations: _Locations,
    line_count: int,
    document_fact: FactState | None,
    document_disclosure: DisclosureLevel | None,
    warnings: list[str],
) -> tuple[_Heading, ...]:
    raw: list[dict[str, object]] = []
    stack: list[HeadingAncestor] = []
    anchors: dict[str, int] = {}
    quote_depth = 0
    previous_level: int | None = None
    for index, token in enumerate(tokens):
        if token.type == "blockquote_open":
            quote_depth += 1
            continue
        if token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
            continue
        if token.type != "heading_open" or quote_depth:
            continue
        try:
            location = locations.from_map(token.map)
            level = int(token.tag.removeprefix("h"))
        except (MarkdownStructureError, ValueError) as exc:
            warnings.append(f"malformed heading token: {exc}")
            continue
        heading = _plain(_inline(tokens, index)) or "Untitled section"
        while stack and stack[-1].level >= level:
            stack.pop()
        if previous_level is not None and level > previous_level + 1:
            warnings.append(
                f"heading level jumps from h{previous_level} to h{level} at line {location.start_line}"
            )
        previous_level = level
        fact, found = _resolve_markers(
            _FACT_RE.findall(heading), FactState, f"heading fact policy at line {location.start_line}"
        )
        warnings.extend(found)
        disclosure, found = _resolve_markers(
            _DISCLOSURE_RE.findall(heading),
            DisclosureLevel,
            f"heading disclosure policy at line {location.start_line}",
        )
        warnings.extend(found)
        base = _anchor_base(heading)
        occurrence = anchors.get(base, 0)
        anchors[base] = occurrence + 1
        anchor = base if occurrence == 0 else f"{base}-{occurrence}"
        identity = "section." + hashlib.sha256(
            f"{locations.path}\0{location.start_byte}\0{level}\0{heading}".encode()
        ).hexdigest()[:20]
        node = HeadingAncestor(
            identity=identity,
            heading=heading,
            level=level,
            location=location,
            occurrence=occurrence,
            anchor=anchor,
            fact_state=fact,
            disclosure=disclosure,
        )
        ancestors = tuple(stack)
        ancestry = (*ancestors, node)
        raw.append(
            {
                "heading": heading,
                "level": level,
                "start": location.start_line - 1,
                "heading_end": location.end_line,
                "identity": identity,
                "anchor": anchor,
                "occurrence": occurrence,
                "fact": fact,
                "disclosure": disclosure,
                "ancestors": ancestors,
                "ancestry": ancestry,
                "effective_fact": _restrictive(
                    document_fact, *(item.fact_state for item in ancestry)
                ),
                "effective_disclosure": _restrictive(
                    document_disclosure, *(item.disclosure for item in ancestry)
                ),
            }
        )
        stack.append(node)
    result: list[_Heading] = []
    for index, item in enumerate(raw):
        content_end = int(raw[index + 1]["start"]) if index + 1 < len(raw) else line_count
        section_end = line_count
        for later in raw[index + 1 :]:
            if int(later["level"]) <= int(item["level"]):
                section_end = int(later["start"])
                break
        result.append(
            _Heading(
                heading=str(item["heading"]),
                level=int(item["level"]),
                start_line0=int(item["start"]),
                heading_end_line0=int(item["heading_end"]),
                content_end_line0=max(int(item["heading_end"]), content_end),
                section_end_line0=max(int(item["heading_end"]), section_end),
                identity=str(item["identity"]),
                anchor=str(item["anchor"]),
                occurrence=int(item["occurrence"]),
                fact_state=item["fact"],
                disclosure=item["disclosure"],
                ancestors=item["ancestors"],
                ancestry=item["ancestry"],
                effective_fact_state=item["effective_fact"],
                effective_disclosure=item["effective_disclosure"],
            )
        )
    return tuple(result)


def _sections(
    headings: Sequence[_Heading],
    locations: _Locations,
    fences: Sequence[_Interval],
    html: Sequence[_Interval],
    quotes: Sequence[_Interval],
) -> tuple[MarkdownSection, ...]:
    result: list[MarkdownSection] = []
    secret_path = _secret_path(locations.path)
    for item in headings:
        location = locations.from_zero_based(item.start_line0, item.section_end_line0)
        content = locations.from_zero_based(item.start_line0, item.content_end_line0)
        ancestry_text = " / ".join(node.heading for node in item.ancestry)
        example = _EXAMPLE_HEADING_RE.search(ancestry_text) is not None
        negative = _NEGATIVE_RE.search(ancestry_text) is not None
        template = (
            _TEMPLATE_HEADING_RE.search(ancestry_text) is not None or negative
        )
        in_html = any(
            interval.overlaps(item.start_line0, item.content_end_line0)
            for interval in html
        )
        in_fence = any(
            interval.overlaps(item.start_line0, item.content_end_line0)
            for interval in fences
        )
        in_quote = any(
            interval.overlaps(item.start_line0, item.content_end_line0)
            for interval in quotes
        )
        secret_content = _SECRET_CONTENT_RE.search(item.heading) is not None
        malformed = any(
            interval.malformed
            and interval.overlaps(item.start_line0, item.content_end_line0)
            for interval in (*fences, *html)
        )
        reasons = _reasons(
            inside_fence=in_fence,
            inside_blockquote=in_quote,
            inside_html=in_html,
            inside_example=example,
            inside_template=template,
            inside_quoted=False,
            negative_instruction=negative,
            secret_path=secret_path,
            secret_content=secret_content,
            malformed=malformed,
            kind="section",
            fact=item.effective_fact_state,
            disclosure=item.effective_disclosure,
        )
        result.append(
            MarkdownSection(
                identity=item.identity,
                heading=item.heading,
                level=item.level,
                anchor=item.anchor,
                occurrence=item.occurrence,
                location=location,
                content_location=content,
                ancestors=item.ancestors,
                heading_ancestry=tuple(
                    ancestor.heading for ancestor in item.ancestry
                ),
                heading_ancestor_nodes=item.ancestry,
                flags=_flags(
                    reasons,
                    in_fence,
                    in_quote,
                    in_html,
                    example,
                    template,
                    False,
                    negative,
                    secret_path,
                    secret_content,
                    malformed,
                ),
                fact_state=item.fact_state,
                disclosure=item.disclosure,
                effective_fact_state=item.effective_fact_state,
                effective_disclosure=item.effective_disclosure,
            )
        )
    return tuple(result)


def _blocks(
    tokens: Sequence[Token],
    locations: _Locations,
    headings: Sequence[_Heading],
    document_fact: FactState | None,
    document_disclosure: DisclosureLevel | None,
    fences: Sequence[_Interval],
    html: Sequence[_Interval],
    quotes: Sequence[_Interval],
    warnings: list[str],
) -> tuple[MarkdownBlock, ...]:
    starts = [item.start_line0 for item in headings]
    result: list[MarkdownBlock] = []
    quote_depth = list_depth = item_depth = table_depth = row_depth = 0
    tables: list[tuple[str, SourceLocation, int]] = []
    for index, token in enumerate(tokens):
        kind: str | None = None
        inline_content: str | None = None
        inline_html = False
        cells: tuple[str, ...] = ()
        table_identity: str | None = None
        table_location: SourceLocation | None = None
        row_index: int | None = None
        if token.type == "blockquote_open":
            quote_depth += 1
            continue
        if token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
            continue
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            list_depth += 1
            continue
        if token.type in {"bullet_list_close", "ordered_list_close"}:
            list_depth = max(0, list_depth - 1)
            continue
        if token.type == "table_open":
            table_depth += 1
            try:
                table_location = locations.from_map(token.map)
                table_identity = _block_identity("table", locations.path, table_location)
                tables.append((table_identity, table_location, 0))
            except MarkdownStructureError as exc:
                warnings.append(str(exc))
            continue
        if token.type == "table_close":
            table_depth = max(0, table_depth - 1)
            if tables:
                tables.pop()
            continue
        if token.type == "tr_open":
            row_depth += 1
            if tables:
                table_identity, table_location, row_index = tables[-1]
                cells = _table_cells(tokens, index)
                tables[-1] = (table_identity, table_location, row_index + 1)
                kind = "table"
        elif token.type == "tr_close":
            row_depth = max(0, row_depth - 1)
            continue
        elif token.type == "list_item_open":
            item_depth += 1
            continue
        elif token.type == "list_item_close":
            item_depth = max(0, item_depth - 1)
            continue
        elif token.type == "paragraph_open":
            if table_depth == 0 and row_depth == 0:
                kind = "list_item" if item_depth > 0 else "paragraph"
                inline_content = _inline(tokens, index)
                inline_html = _inline_has_html(tokens, index)
        elif token.type == "fence":
            kind = "fence"
            inline_content = token.content
        elif token.type == "code_block":
            kind = "indented_code"
            inline_content = token.content
        elif token.type == "html_block":
            kind = "html"
            inline_content = token.content
            inline_html = True
        if kind is None:
            continue
        block = _make_block(
            token=token,
            kind=kind,
            locations=locations,
            headings=headings,
            heading_starts=starts,
            quote_depth=quote_depth,
            list_depth=max(list_depth, 1 if kind == "list_item" else 0),
            document_fact=document_fact,
            document_disclosure=document_disclosure,
            fences=fences,
            html=html,
            quotes=quotes,
            warnings=warnings,
            inline_content=inline_content,
            inline_html=inline_html,
            table_identity=table_identity,
            table_location=table_location,
            row_index=row_index,
            cells=cells,
        )
        if block is not None:
            result.append(block)
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.location.start_byte,
                item.location.end_byte,
                item.kind,
            ),
        )
    )


def _make_block(
    *,
    token: Token,
    kind: str,
    locations: _Locations,
    headings: Sequence[_Heading],
    heading_starts: Sequence[int],
    quote_depth: int,
    list_depth: int,
    document_fact: FactState | None,
    document_disclosure: DisclosureLevel | None,
    fences: Sequence[_Interval],
    html: Sequence[_Interval],
    quotes: Sequence[_Interval],
    warnings: list[str],
    inline_content: str | None,
    inline_html: bool,
    table_identity: str | None,
    table_location: SourceLocation | None,
    row_index: int | None,
    cells: tuple[str, ...],
) -> MarkdownBlock | None:
    try:
        location = locations.from_map(token.map)
    except MarkdownStructureError as exc:
        warnings.append(f"{kind}: {exc}")
        return None
    raw = locations.text(location)
    plain = (
        "; ".join(_plain(cell) for cell in cells)
        if cells
        else _plain(inline_content if inline_content is not None else raw)
    )
    heading = _heading_at(headings, heading_starts, location.start_line - 1)
    fact, found = _resolve_markers(
        _FACT_RE.findall(raw), FactState, f"block fact policy at line {location.start_line}"
    )
    warnings.extend(found)
    disclosure, found = _resolve_markers(
        _DISCLOSURE_RE.findall(raw),
        DisclosureLevel,
        f"block disclosure policy at line {location.start_line}",
    )
    warnings.extend(found)
    resolved_fact = _restrictive(
        heading.effective_fact_state if heading else document_fact, fact
    )
    resolved_disclosure = _restrictive(
        heading.effective_disclosure if heading else document_disclosure,
        disclosure,
    )
    effective_fact = resolved_fact or FactState.F5
    effective_disclosure = resolved_disclosure or DisclosureLevel.P3
    start0, end0 = location.start_line - 1, location.end_line
    fence_hits = [item for item in fences if item.overlaps(start0, end0)]
    html_hits = [item for item in html if item.overlaps(start0, end0)]
    quote_hits = [
        item for item in quotes if item.overlaps(start0, end0)
    ]
    in_fence = kind == "fence" or bool(fence_hits)
    in_html = kind == "html" or inline_html or bool(html_hits)
    ancestry = heading.ancestry if heading else ()
    ancestry_text = " / ".join(item.heading for item in ancestry)
    example = bool(
        _EXAMPLE_HEADING_RE.search(ancestry_text) or _EXAMPLE_BLOCK_RE.search(raw)
    )
    negative = bool(
        _NEGATIVE_RE.search(ancestry_text) or _NEGATIVE_RE.search(plain)
    )
    template = bool(
        _TEMPLATE_HEADING_RE.search(ancestry_text)
        or _TEMPLATE_BLOCK_RE.search(raw)
        or negative
    )
    inside_quote = quote_depth > 0 or bool(quote_hits)
    quoted = inside_quote or _wholly_quoted(plain)
    secret_path = _secret_path(locations.path)
    secret_content = _SECRET_CONTENT_RE.search(raw) is not None
    malformed = any(item.malformed for item in (*fence_hits, *html_hits))
    reasons = _reasons(
        inside_fence=in_fence,
        inside_blockquote=inside_quote,
        inside_html=in_html,
        inside_example=example,
        inside_template=template,
        inside_quoted=quoted,
        negative_instruction=negative,
        secret_path=secret_path,
        secret_content=secret_content,
        malformed=malformed,
        kind=kind,
        fact=effective_fact,
        disclosure=effective_disclosure,
    )
    return MarkdownBlock(
        identity=_block_identity(kind, locations.path, location),
        kind=kind,
        location=location,
        heading_ancestry=tuple(item.heading for item in ancestry),
        heading_ancestor_nodes=ancestry,
        flags=_flags(
            reasons,
            in_fence,
            inside_quote,
            in_html,
            example,
            template,
            quoted,
            negative,
            secret_path,
            secret_content,
            malformed,
        ),
        text=raw,
        plain_text=plain,
        section_identity=heading.identity if heading else None,
        fact_state=fact,
        disclosure=disclosure,
        effective_fact_state=effective_fact,
        effective_disclosure=effective_disclosure,
        list_depth=list_depth,
        table_identity=table_identity,
        table_location=table_location,
        row_index=row_index,
        cells=cells,
        fact_policy_explicit=resolved_fact is not None,
        disclosure_policy_explicit=resolved_disclosure is not None,
    )


def _heading_at(
    headings: Sequence[_Heading], starts: Sequence[int], line0: int
) -> _Heading | None:
    index = bisect_right(starts, line0) - 1
    return headings[index] if index >= 0 else None


def _table_cells(tokens: Sequence[Token], start: int) -> tuple[str, ...]:
    result: list[str] = []
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.type == "tr_open":
            depth += 1
        elif token.type == "tr_close":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and token.type in {"th_open", "td_open"}:
            result.append(
                _inline(tokens, index).strip().replace(r"\|", "|")
            )
    return tuple(result)


def _inline_has_html(tokens: Sequence[Token], index: int) -> bool:
    if index + 1 >= len(tokens) or tokens[index + 1].type != "inline":
        return False
    return any(
        child.type == "html_inline" for child in (tokens[index + 1].children or ())
    )


def _block_identity(kind: str, path: str, location: SourceLocation) -> str:
    digest = hashlib.sha256(
        f"{path}\0{location.start_byte}\0{location.end_byte}\0{kind}".encode()
    ).hexdigest()[:20]
    return f"block.{digest}"


def _secret_path(path: str) -> bool:
    return any(_SENSITIVE_PATH_RE.search(item) for item in PurePosixPath(path).parts)


def _wholly_quoted(value: str) -> bool:
    value = value.strip()
    if len(value) < 2:
        return False
    pairs = {"\"": "\"", "'": "'", "“": "”", "‘": "’", "「": "」", "『": "』", "《": "》"}
    return value[0] in pairs and value[-1] == pairs[value[0]]


def _reasons(
    *,
    inside_fence: bool,
    inside_blockquote: bool,
    inside_html: bool,
    inside_example: bool,
    inside_template: bool,
    inside_quoted: bool,
    negative_instruction: bool,
    secret_path: bool,
    secret_content: bool,
    malformed: bool,
    kind: str,
    fact: FactState | None,
    disclosure: DisclosureLevel | None,
) -> tuple[str, ...]:
    result: list[str] = []
    if secret_path:
        result.append("secret_path")
    if secret_content:
        result.append("secret_content")
    if fact is FactState.F6:
        result.append("fact_policy_F6")
    if disclosure is DisclosureLevel.P3:
        result.append("disclosure_policy_P3")
    if inside_fence:
        result.append("fenced_content")
    if inside_blockquote:
        result.append("blockquote")
    if inside_html:
        result.append("html")
    if inside_example:
        result.append("example")
    if inside_template:
        result.append("template")
    if inside_quoted:
        result.append("quoted_material")
    if negative_instruction:
        result.append("negative_instruction")
    if kind in {"fence", "indented_code"}:
        result.append("code")
    if malformed:
        result.append("malformed_markdown")
    return tuple(dict.fromkeys(result))


def _flags(
    reasons: tuple[str, ...],
    inside_fence: bool,
    inside_blockquote: bool,
    inside_html: bool,
    inside_example: bool,
    inside_template: bool,
    inside_quoted: bool,
    negative_instruction: bool,
    secret_path: bool,
    secret_content: bool,
    malformed: bool,
) -> StructuralFlags:
    return StructuralFlags(
        inside_fence=inside_fence,
        inside_blockquote=inside_blockquote,
        inside_html=inside_html,
        inside_example=inside_example,
        inside_template=inside_template,
        inside_quoted=inside_quoted,
        negative_instruction=negative_instruction,
        secret_path=secret_path,
        secret_content=secret_content,
        malformed=malformed,
        exclusion_reasons=reasons,
    )


def _blockquote_intervals(
    tokens: Sequence[Token], line_count: int
) -> tuple[_Interval, ...]:
    result: list[_Interval] = []
    for token in tokens:
        if token.type != "blockquote_open" or token.map is None:
            continue
        start, end = int(token.map[0]), int(token.map[1])
        result.append(
            _Interval(start, min(max(end, start + 1), line_count))
        )
    return tuple(result)


def _fence_intervals(
    text: str, tokens: Sequence[Token], line_count: int
) -> tuple[tuple[_Interval, ...], list[str]]:
    lines = text.splitlines()
    result: list[_Interval] = []
    warnings: list[str] = []
    for token in tokens:
        if token.type != "fence" or token.map is None:
            continue
        start, end = int(token.map[0]), int(token.map[1])
        closed = _fence_closed(lines, start, end, token.markup)
        if not closed:
            warnings.append(f"unclosed fenced block starting at line {start + 1}")
        result.append(_Interval(start, min(max(end, start + 1), line_count), not closed))
    return tuple(result), warnings


def _fence_closed(
    lines: Sequence[str], start: int, end: int, markup: str
) -> bool:
    if not markup:
        return False
    character, minimum = markup[0], len(markup)
    for line in lines[start + 1 : min(end, len(lines))]:
        if re.match(
            rf"^ {{0,3}}{re.escape(character)}{{{minimum},}}[ \t]*$", line
        ):
            return True
    return False


def _html_intervals(
    text: str, line_count: int
) -> tuple[tuple[_Interval, ...], list[str]]:
    stack: list[tuple[str, int]] = []
    result: list[_Interval] = []
    warnings: list[str] = []
    for line0, line in enumerate(text.splitlines()):
        for match in _HTML_CONTAINER_RE.finditer(line):
            closing, tag = match.group(1), match.group(2).casefold()
            if closing:
                owner = next(
                    (
                        index
                        for index in range(len(stack) - 1, -1, -1)
                        if stack[index][0] == tag
                    ),
                    None,
                )
                if owner is None:
                    warnings.append(
                        f"unmatched closing HTML <{tag}> at line {line0 + 1}"
                    )
                    continue
                _, start = stack.pop(owner)
                result.append(_Interval(start, line0 + 1))
            elif not match.group(0).rstrip().endswith("/>"):
                stack.append((tag, line0))
    for tag, start in stack:
        warnings.append(f"unclosed HTML <{tag}> starting at line {start + 1}")
        result.append(_Interval(start, line_count, True))
    return tuple(result), warnings


__all__ = [
    "DEFAULT_MARKDOWN_STRUCTURE_SERVICE",
    "HeadingAncestor",
    "MarkdownBlock",
    "MarkdownSection",
    "MarkdownStructureError",
    "MarkdownStructureService",
    "SourceDocument",
    "SourceLocation",
    "StructuralFlags",
    "parse_markdown",
    "parse_markdown_bytes",
]
