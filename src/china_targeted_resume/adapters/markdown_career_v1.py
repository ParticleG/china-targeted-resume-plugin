"""Adapter for the supported Markdown career-knowledge-base layout."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import ipaddress
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from china_targeted_resume.markdown_structure import (
    MarkdownBlock,
    MarkdownSection,
    SourceDocument,
    parse_markdown,
)

from china_targeted_resume.models import (
    CompanyRef,
    DisclosureLevel,
    EvidenceCandidate,
    EvidenceRecord,
    FactState,
    Freshness,
    Requirement,
    RoleMatchState,
    RoleRef,
    RoleRequest,
    SourceManifest,
    SourceRef,
    SourceSection,
    SourceSpan,
    TargetContext,
)

_ADAPTER_NAME = "markdown-career-v1"
_REQUIRED_PATHS = (
    "personal-data/README.md",
    "personal-data/meta/fact-boundaries.md",
    "company-research/README.md",
    "role-research/README.md",
    "role-research/skill-assisted-job-match-workflow.md",
    "growth-roadmap/README.md",
)
_ROLE_DOSSIER_FILES = (
    "job-description.md",
    "requirement-analysis.md",
    "competency-model.md",
    "evidence-mapping.md",
    "gap-analysis.md",
    "interview-preparation.md",
    "sources.md",
)
_IGNORED_NAMES = {".git", ".hg", ".svn", "__pycache__", "node_modules", "output", "outputs", "dist", "build"}
_SENSITIVE_PATH_RE = re.compile(r"(?:^|[-_.])(secret|credential|password|private[-_]?key|token|\.env)(?:$|[-_.])", re.I)
_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+[\"'][^\n]*[\"'])?\)|<((?:https?://|mailto:)[^>]+)>", re.I)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_SECRET_RE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\b\s*[:=]|\b(?:sk|ghp|xox[baprs])_[A-Za-z0-9_-]{12,})",
    re.I,
)
_INTERNAL_ADDRESS_RE = re.compile(r"\b(?:localhost|127\.0\.0\.1|10\.\d{1,3}(?:\.\d{1,3}){2}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?::\d+)?\b", re.I)
_BLOCK_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])(?:F6|P3)(?![A-Za-z0-9])", re.I)
_FACT_RE = re.compile(r"(?<![A-Za-z0-9])(F[1-6])(?![A-Za-z0-9])", re.I)
_DISCLOSURE_RE = re.compile(r"(?<![A-Za-z0-9])(P[0-3])(?![A-Za-z0-9])", re.I)
_WORD_RE = re.compile(r"[\w.+#-]+", re.UNICODE)
_CJK_SEQUENCE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


class SourceBoundaryError(ValueError):
    """Raised when a source path would leave the configured source root."""


class SourceLayoutError(ValueError):
    """Raised when authority or navigation files are missing."""




class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _public_http_host(parsed: Any) -> bool:
    host = parsed.hostname
    if host is None or parsed.username is not None or parsed.password is not None:
        return False
    normalized = host.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith((".localhost", ".local", ".internal", ".lan")):
        return False
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        if "." not in normalized:
            return False
        addresses = {
            ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
            for _, _, _, _, sockaddr in socket.getaddrinfo(
                normalized,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
        return bool(addresses) and all(address.is_global for address in addresses)
    return literal.is_global


def _display_heading(raw: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`~]", "", raw)).strip()


def _anchor_base(heading: str) -> str:
    text = _display_heading(heading).casefold().strip()
    text = re.sub(r"[^\w\- \u0080-\U0010ffff]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text)


def _domain(path: PurePosixPath) -> str:
    top = path.parts[0] if path.parts else "root"
    return {
        "personal-data": "personal-data",
        "company-research": "company-research",
        "role-research": "role-research",
        "growth-roadmap": "growth-roadmap",
    }.get(top, "repository-navigation")


def _redact(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _SECRET_RE.sub("[REDACTED_SECRET]", text)
    return _INTERNAL_ADDRESS_RE.sub("[REDACTED_INTERNAL_ADDRESS]", text)


def _blocked(text: str) -> bool:
    return bool(_BLOCK_MARKER_RE.search(text) or _SECRET_RE.search(text))


def _terms(value: str) -> set[str]:
    return {term.casefold() for term in _WORD_RE.findall(value) if len(term) > 1}


class MarkdownCareerV1Adapter:
    """Read Markdown source data while retaining only navigation metadata."""

    def __init__(self, root: Path | None = None) -> None:
        self._root: Path | None = None
        self._manifest: SourceManifest | None = None
        self._sections: dict[tuple[str, str, int, int], SourceSection] = {}
        self._source_documents: dict[str, SourceDocument] = {}
        self._structural_sections: dict[
            tuple[str, str, int, int], MarkdownSection
        ] = {}
        if root is not None:
            self.discover(root)

    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("discover() must be called before reading source data")
        return self._root

    @property
    def manifest(self) -> SourceManifest:
        if self._manifest is None:
            raise RuntimeError("discover() must be called before reading source data")
        return self._manifest

    def _resolve_local(self, value: str | Path, *, owner: Path | None = None, must_exist: bool = True) -> Path:
        raw = os.fspath(value)
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc:
            raise SourceBoundaryError(f"external references are not local paths: {raw!r}")
        decoded = unquote(parsed.path)
        candidate_path = Path(decoded)
        if candidate_path.is_absolute():
            raise SourceBoundaryError(f"absolute source path rejected: {raw!r}")
        base = owner.parent if owner is not None else self.root
        candidate = base.joinpath(candidate_path)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise SourceBoundaryError(f"path traversal escapes configured root: {raw!r}")
        if must_exist:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise SourceBoundaryError(f"source path is not readable: {raw!r}") from exc
            if not resolved.is_relative_to(self.root):
                raise SourceBoundaryError(f"path traversal escapes configured root: {raw!r}")
        return resolved

    def _validate_layout(self) -> None:
        readmes = (self.root / "README.md", self.root / "README.zh-CN.md")
        if not any(path.is_file() for path in readmes):
            raise SourceLayoutError("source root requires README.md or README.zh-CN.md")
        missing = [relative for relative in _REQUIRED_PATHS if not self._resolve_local(relative, must_exist=False).is_file()]
        if missing:
            raise SourceLayoutError(f"missing required authority/navigation files: {', '.join(missing)}")

    def _markdown_files(self) -> list[Path]:
        result: list[Path] = []
        pending = [self.root]
        while pending:
            directory = pending.pop()
            for entry in sorted(os.scandir(directory), key=lambda item: item.name.casefold(), reverse=True):
                if entry.name.startswith(".") or entry.name in _IGNORED_NAMES or _SENSITIVE_PATH_RE.search(entry.name):
                    continue
                path = Path(entry.path)
                if entry.is_symlink():
                    try:
                        target = path.resolve(strict=True)
                    except OSError as exc:
                        raise SourceBoundaryError(f"broken source symlink rejected: {path.relative_to(self.root)}") from exc
                    if not target.is_relative_to(self.root):
                        raise SourceBoundaryError(f"source symlink escapes configured root: {path.relative_to(self.root)}")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix.casefold() in {".md", ".markdown"}:
                    result.append(path)
        return sorted(result, key=lambda path: path.relative_to(self.root).as_posix())

    def _headings(
        self, document: SourceDocument
    ) -> list[tuple[int, int, str, str]]:
        """Return the legacy tuple view over the canonical structural tree."""

        return [
            (
                section.location.start_line,
                section.level,
                section.heading,
                section.anchor,
            )
            for section in document.sections
        ]

    def _internal_links(self, text: str, owner: Path) -> list[str]:
        links: set[str] = set()
        for match in _LINK_RE.finditer(text):
            target = match.group(1) or match.group(2) or ""
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            if not parsed.path:
                if parsed.fragment:
                    links.add(f"{owner.relative_to(self.root).as_posix()}#{parsed.fragment}")
                continue
            resolved = self._resolve_local(target, owner=owner, must_exist=False)
            if not resolved.exists():
                continue
            relative = resolved.relative_to(self.root).as_posix()
            if any(_SENSITIVE_PATH_RE.search(part) for part in PurePosixPath(relative).parts):
                continue
            links.add(f"{relative}#{parsed.fragment}" if parsed.fragment else relative)
        return sorted(links)

    def source_document(self, path: str | Path) -> SourceDocument:
        """Return the one-read in-memory document for a discovered source path."""

        source = self._resolve_local(path)
        relative = source.relative_to(self.root).as_posix()
        try:
            return self._source_documents[relative]
        except KeyError as exc:
            raise KeyError(f"source was not part of discovery: {relative}") from exc
    @staticmethod
    def structural_block_is_safe(block: MarkdownBlock) -> bool:
        """Ignore only generic fallback policy while preserving hard context."""

        reasons = set(block.flags.exclusion_reasons)
        if not block.has_explicit_disclosure_policy:
            reasons.discard("disclosure_policy_P3")
        if not block.has_explicit_fact_policy:
            reasons.discard("fact_policy_F6")
        return not reasons


    def parse_pipe_tables(self, path: str | Path) -> list[dict[str, Any]]:
        """Return the legacy table view backed by markdown-it token maps."""

        document = self.source_document(path)
        grouped: dict[str, dict[str, Any]] = {}
        for block in document.blocks:
            if (
                block.kind != "table"
                or block.table_identity is None
                or block.table_location is None
                or not self.structural_block_is_safe(block)
            ):
                continue
            table = grouped.setdefault(
                block.table_identity,
                {
                    "start_line": block.table_location.start_line,
                    "end_line": block.table_location.end_line,
                    "rows": [],
                },
            )
            table["rows"].append(list(block.cells))
        return sorted(grouped.values(), key=lambda item: item["start_line"])

    @staticmethod
    def _split_table_row(line: str) -> list[str]:
        value = line.strip().strip("|")
        return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", value)]

    def discover(self, root: Path) -> SourceManifest:
        candidate = Path(root).expanduser()
        if not candidate.exists() or not candidate.is_dir():
            raise SourceLayoutError(f"source root is not a directory: {candidate}")
        self._root = candidate.resolve(strict=True)
        self._validate_layout()
        sections: list[SourceSection] = []
        documents: list[str] = []
        section_lookup: dict[tuple[str, str, int, int], SourceSection] = {}
        structural_lookup: dict[
            tuple[str, str, int, int], MarkdownSection
        ] = {}
        parsed_documents: dict[str, SourceDocument] = {}
        for path in self._markdown_files():
            relative = path.relative_to(self.root).as_posix()
            document = parse_markdown(path, source_root=self.root)
            parsed_documents[relative] = document
            if not document.sections:
                continue
            title = next(
                (
                    section.heading
                    for section in document.sections
                    if section.level == 1
                ),
                path.stem,
            )
            if _blocked(title) or _EMAIL_RE.search(title) or _PHONE_RE.search(title):
                continue
            safe_sections: list[SourceSection] = []
            for structural in document.sections:
                if (
                    structural.flags.secret_path
                    or structural.flags.secret_content
                    or structural.effective_fact_state is FactState.F6
                    or structural.effective_disclosure is DisclosureLevel.P3
                    or _blocked(structural.heading)
                    or _EMAIL_RE.search(structural.heading)
                    or _PHONE_RE.search(structural.heading)
                ):
                    continue
                safe_text = "\n".join(
                    block.text
                    for block in structural.blocks
                    if self.structural_block_is_safe(block)
                )
                start = structural.content_location.start_line
                end = structural.content_location.end_line
                item = SourceSection(
                    document_id=relative,
                    source_path=relative,
                    source_hash=document.source_hash,
                    title=title,
                    section=structural.heading,
                    section_anchor=structural.anchor,
                    domain=_domain(PurePosixPath(relative)),
                    outgoing_internal_links=self._internal_links(safe_text, path),
                    start_line=start,
                    end_line=end,
                )
                key = (relative, structural.anchor, start, end)
                safe_sections.append(item)
                section_lookup[key] = item
                structural_lookup[key] = structural
            if safe_sections:
                documents.append(relative)
                sections.extend(safe_sections)
        manifest = SourceManifest(
            adapter=_ADAPTER_NAME,
            root=self.root,
            generated_at=datetime.now(UTC),
            documents=documents,
            sections=sections,
        )
        self._manifest = manifest
        self._sections = section_lookup
        self._source_documents = parsed_documents
        self._structural_sections = structural_lookup
        return manifest

    def _company_id(self, ref: str | CompanyRef) -> str:
        return ref.company_id if isinstance(ref, CompanyRef) else ref

    def list_companies(self) -> list[CompanyRef]:
        company_root = self._resolve_local("company-research")
        navigation = self._resolve_local("company-research/README.md")
        nav_text = self.source_document(
            navigation.relative_to(self.root).as_posix()
        ).text
        slugs: set[str] = set()
        for match in _LINK_RE.finditer(nav_text):
            target = match.group(1) or ""
            if urlsplit(target).scheme:
                continue
            try:
                resolved = self._resolve_local(target, owner=navigation)
            except SourceBoundaryError:
                raise
            directory = resolved if resolved.is_dir() else resolved.parent
            if directory.parent == company_root and directory != company_root:
                slugs.add(directory.name)
        for entry in os.scandir(company_root):
            if entry.is_dir(follow_symlinks=False) and not entry.is_symlink() and (Path(entry.path) / "README.md").is_file():
                slugs.add(entry.name)
        companies: list[CompanyRef] = []
        for slug in sorted(slugs):
            readme = self._resolve_local(f"company-research/{slug}/README.md")
            document = self.source_document(
                readme.relative_to(self.root).as_posix()
            )
            heading = next(
                (
                    item.heading
                    for item in document.sections
                    if item.level == 1
                ),
                slug.replace("-", " ").title(),
            )
            companies.append(CompanyRef(company_id=slug, display_name=heading, source_refs=[readme.relative_to(self.root).as_posix()]))
        return companies

    def load_company(self, company_ref: str | CompanyRef) -> dict[str, str]:
        slug = self._company_id(company_ref)
        known = {company.company_id for company in self.list_companies()}
        if slug not in known:
            raise KeyError(f"unknown company reference: {slug}")
        directory = self._resolve_local(f"company-research/{slug}")
        result: dict[str, str] = {}
        for path in sorted(directory.glob("*.md")):
            relative = path.relative_to(self.root).as_posix()
            result[relative] = self.source_document(relative).text
        return result

    def list_roles(self, company_ref: str | CompanyRef) -> list[RoleRef]:
        company_id = self._company_id(company_ref)
        if company_id not in {company.company_id for company in self.list_companies()}:
            raise KeyError(f"unknown company reference: {company_id}")
        roles: dict[str, RoleRef] = {}
        role_root = self._resolve_local("role-research")
        for entry in sorted(os.scandir(role_root), key=lambda item: item.name):
            if not entry.is_dir(follow_symlinks=False) or entry.is_symlink() or not entry.name.startswith(f"{company_id}-"):
                continue
            directory = Path(entry.path)
            if not all((directory / filename).is_file() for filename in _ROLE_DOSSIER_FILES):
                continue
            source = self._resolve_local((directory / "job-description.md").relative_to(self.root).as_posix())
            headings = self._headings(
                self.source_document(source.relative_to(self.root).as_posix())
            )
            title = next(
                (heading for _, level, heading, _ in headings if level == 1),
                entry.name.removeprefix(f"{company_id}-").replace("-", " ").title(),
            )
            source_refs = [
                self._resolve_local((directory / filename).relative_to(self.root).as_posix()).relative_to(self.root).as_posix()
                for filename in _ROLE_DOSSIER_FILES
            ]
            roles[entry.name] = RoleRef(
                role_id=entry.name,
                title=title,
                company_id=company_id,
                source_refs=source_refs,
            )
        hiring = self._resolve_local(f"company-research/{company_id}/roles-and-hiring.md", must_exist=False)
        if hiring.is_file():
            relative = hiring.relative_to(self.root).as_posix()
            for table in self.parse_pipe_tables(relative):
                rows = table["rows"]
                if len(rows) < 2:
                    continue
                role_column = next(
                    (
                        index
                        for index, header in enumerate(rows[0])
                        if re.fullmatch(r"(?:岗位|职位|job|position|role)(?:名称|标题)?", _display_heading(header), re.I)
                    ),
                    None,
                )
                if role_column is None:
                    continue
                for row in rows[1:]:
                    if role_column >= len(row) or not row[role_column].strip() or _blocked(" ".join(row)):
                        continue
                    raw_title = row[role_column]
                    link_title = re.fullmatch(r"\[([^\]]+)\]\([^)]+\)", raw_title)
                    title = _display_heading(link_title.group(1) if link_title else raw_title)
                    role_id = f"{company_id}-{_anchor_base(title)}"
                    roles.setdefault(
                        role_id,
                        RoleRef(
                            role_id=role_id,
                            title=title,
                            company_id=company_id,
                            source_refs=[f"{relative}:L{table['start_line']}-L{table['end_line']}"],
                        ),
                    )
        return sorted(roles.values(), key=lambda role: (role.title.casefold(), role.role_id))

    def resolve_role(self, request: RoleRequest) -> TargetContext:
        from china_targeted_resume import target_resolution

        resolver = getattr(target_resolution, "resolve_role", None) or getattr(target_resolution, "resolve_target_context", None)
        if resolver is None:
            raise AttributeError("target_resolution must export resolve_role or resolve_target_context")
        return resolver(request=request, adapter=self)

    def load_policy(self) -> dict[str, Any]:
        relative = "personal-data/meta/fact-boundaries.md"
        document = self.source_document(relative)
        return {
            "source_path": relative,
            "source_hash": document.source_hash,
            "text": document.text,
        }

    def _structural_section(self, section: SourceSection) -> MarkdownSection:
        if section.start_line is None or section.end_line is None:
            raise RuntimeError("section ownership range is unavailable")
        key = (
            section.source_path,
            section.section_anchor,
            section.start_line,
            section.end_line,
        )
        try:
            return self._structural_sections[key]
        except KeyError as exc:
            raise RuntimeError("section is not owned by the structural document") from exc

    def _section_text(self, section: SourceSection) -> str:
        document = self.source_document(section.source_path)
        if document.source_hash != section.source_hash:
            raise RuntimeError(f"source changed after discovery: {section.source_path}")
        if section.start_line is None or section.end_line is None:
            raise RuntimeError("section ownership range is unavailable")
        return document.text_for_lines(section.start_line, section.end_line).rstrip(
            "\r\n"
        )
    @staticmethod
    def _clean_claim(raw: str) -> str:
        claim = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", raw)
        claim = re.sub(r"<(?:https?://|mailto:)[^>]+>", "", claim, flags=re.I)
        claim = re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s+", "", claim)
        claim = re.sub(r"[*_`~]", "", claim)
        claim = re.sub(r"(?<![A-Za-z0-9])(?:F[1-6]|P[0-3])(?![A-Za-z0-9])", "", claim, flags=re.I)
        claim = re.sub(r"\s*[,;，；]\s*(?=[,;，；.]|$)", "", claim)
        claim = _redact(claim)
        return re.sub(r"\s+", " ", claim).strip(" \t,;，；")

    def _claim_units(
        self, section: SourceSection, body: str | None = None
    ) -> list[tuple[int, int, str, str]]:
        """Extract claim units only from eligible markdown-it leaf blocks."""

        del body
        units: list[tuple[int, int, str, str]] = []
        structural = self._structural_section(section)
        for block in structural.blocks:
            if not self.structural_block_is_safe(block):
                continue
            if block.kind == "table":
                if block.row_index == 0:
                    continue
                value = "; ".join(block.cells)
            elif block.kind in {"list_item", "paragraph"}:
                value = block.plain_text
            else:
                continue
            raw_units = (
                re.split(r"(?<=[.!?。！？])\s+", value)
                if block.kind == "paragraph"
                else [value]
            )
            for raw_unit in raw_units:
                claim = self._clean_claim(raw_unit)
                if claim:
                    units.append(
                        (
                            block.location.start_line,
                            block.location.end_line,
                            claim,
                            block.text,
                        )
                    )
        return units
    def _structural_block_for_unit(
        self, section: SourceSection, start_line: int, end_line: int
    ) -> MarkdownBlock | None:
        block = self.source_document(section.source_path).block_for_span(
            start_line, end_line
        )
        if block is None or block.section_identity != self._structural_section(
            section
        ).identity:
            return None
        return block


    def _document_gates(
        self, sections: list[SourceSection]
    ) -> dict[str, tuple[FactState, DisclosureLevel]]:
        gates: dict[str, tuple[FactState, DisclosureLevel]] = {}
        for section in sections:
            document = self.source_document(section.source_path)
            if (
                document.document_fact_state is not None
                and document.document_disclosure is not None
            ):
                gates[section.source_path] = (
                    document.document_fact_state,
                    document.document_disclosure,
                )
        return gates

    def _heading_contexts(
        self, sections: list[SourceSection]
    ) -> dict[tuple[str, int], str]:
        contexts: dict[tuple[str, int], str] = {}
        for section in sections:
            structural = self._structural_section(section)
            contexts[(section.source_path, section.start_line or 0)] = " / ".join(
                structural.heading_ancestry
            )
        return contexts

    @staticmethod
    def _semantic_gate(
        section: SourceSection,
        heading_context: str,
    ) -> tuple[FactState, DisclosureLevel] | None:
        path = PurePosixPath(section.source_path)
        parts = path.parts
        if len(parts) < 3 or parts[0] != "personal-data":
            return None
        headings = [
            heading.strip().casefold()
            for heading in heading_context.split(" / ")
            if heading.strip()
        ]
        leaf = headings[-1] if headings else section.section.casefold()
        category_headings = set(headings[1:])
        if any(
            re.search(
                r"(?:pending|unverified|conflict|confidential|secret|"
                r"待确认|待补|未确认|冲突|机密)",
                heading,
                re.I,
            )
            for heading in headings
        ) or leaf in {
            "分类原则",
            "记录原则",
            "使用说明",
            "量化信息使用规则",
            "隐私与公开边界",
            "公开边界",
            "核验边界",
            "协作及上游边界",
            "公开链接",
        }:
            return None
        category = parts[1]
        filename = parts[-1]
        if category == "meta" or filename == "basic-information.md":
            return None
        if category in {"work", "company-projects"}:
            return FactState.F2, DisclosureLevel.P1
        if category == "projects":
            return FactState.F3, DisclosureLevel.P0
        if category in {"personal-projects", "community-projects"}:
            return FactState.F2, DisclosureLevel.P0
        if filename == "career-timeline.md":
            return FactState.F2, DisclosureLevel.P1
        if filename == "capabilities.md":
            if category_headings & {
                "工程使用或了解",
                "knowledge",
                "study",
                "learning",
            }:
                return FactState.F3, DisclosureLevel.P1
            if category_headings & {"公开项目经验", "public project experience"}:
                return FactState.F2, DisclosureLevel.P0
            if category_headings & {
                "公司生产经验",
                "工程方法",
                "测试、构建与可观测性",
                "production experience",
                "engineering methods",
                "testing, build, and observability",
            }:
                return FactState.F2, DisclosureLevel.P1
        if filename == "verifiable-achievements.md":
            if category_headings & {
                "公开项目量化记录",
                "教育阶段荣誉与证书",
                "public project metrics",
                "education honors and certificates",
            }:
                return FactState.F2, DisclosureLevel.P0
            if category_headings & {
                "公司项目量化成果",
                "公司荣誉",
                "company project metrics",
                "company honors",
            }:
                return FactState.F2, DisclosureLevel.P1
        if filename == "education-and-honors.md":
            if category_headings & {"教育经历", "education"}:
                return FactState.F2, DisclosureLevel.P0
            if category_headings & {
                "荣誉",
                "honors",
                "证书与能力证明",
                "certificates",
            }:
                return FactState.F2, DisclosureLevel.P1
        return FactState.F5, DisclosureLevel.P3

    @staticmethod
    def _meaningful_terms(text: str) -> set[str]:
        stopwords = {
            "a", "ai", "an", "and", "are", "be", "for", "from", "have", "in",
            "integration", "lead", "more", "must", "of", "or", "professional",
            "required", "the", "to", "with", "years", "experience", "work",
            "ability", "knowledge",
            "以及", "具有", "具备", "相关", "工作", "经验", "能力", "要求", "必须",
            "工程", "开发", "系统", "平台", "负责", "参与", "建设", "实现", "支持",
            "技术", "应用", "岗位", "职位", "使用", "服务", "模型", "数据", "任务",
            "过程", "进行", "管理", "资源", "结构", "方案", "优化", "原理", "问题",
            "工具", "流程", "熟悉", "掌握", "维护", "构建", "设计", "团队", "场景",
            "解决方案", "密切合作", "针对性优化",
        }
        terms: set[str] = set()
        for raw_term in re.findall(r"[A-Za-z][A-Za-z0-9.+#/-]*", text):
            if len(raw_term) <= 1:
                continue
            term = raw_term.casefold().strip("./-")
            if not term:
                continue
            terms.add(term)
            terms.update(
                component
                for component in term.split("/")
                if len(component) > 1
            )
        for sequence in _CJK_SEQUENCE_RE.findall(text):
            if 2 <= len(sequence) <= 8:
                terms.add(sequence)
            for width in (2, 3, 4):
                terms.update(
                    sequence[index : index + width]
                    for index in range(len(sequence) - width + 1)
                )
        return {term for term in terms if term not in stopwords}

    @staticmethod
    def _strong_terms(terms: set[str]) -> set[str]:
        technical_anchors = {
            "训练",
            "推理",
            "通信",
            "吞吐",
            "内存",
            "量化",
            "蒸馏",
            "算力",
            "集群",
            "并行",
            "性能",
            "延迟",
            "调度",
            "容器",
            "缓存",
            "检索",
            "架构",
            "接口",
            "协议",
            "数据库",
            "网络",
            "编译",
            "部署",
            "监控",
            "日志",
            "并发",
            "异步",
            "自动化",
            "算法",
            "测试",
            "交付",
            "运维",
            "大模型",
            "多模态",
            "强化",
            "控制",
            "加载",
            "工作区",
            "研发云",
            "前端",
            "后端",
        }
        boundary_characters = set("并与的和及或为在将从对等了")
        candidates: set[str] = set()
        for term in terms:
            if _CJK_SEQUENCE_RE.fullmatch(term) is None:
                candidates.add(term)
                continue
            if term[0] in boundary_characters or term[-1] in boundary_characters:
                continue
            if term in technical_anchors or (
                len(term) >= 3
                and any(anchor in term for anchor in technical_anchors)
            ):
                candidates.add(term)
        return {
            term
            for term in candidates
            if not any(
                term != other and term in other
                for other in candidates
            )
        }

    def search_evidence(self, requirements: list[Requirement]) -> list[EvidenceCandidate]:
        personal_sections = [section for section in self.manifest.sections if section.domain == "personal-data"]
        document_gates = self._document_gates(personal_sections)
        heading_contexts = self._heading_contexts(personal_sections)
        direct_source_kinds = {
            "work",
            "projects",
            "company-projects",
            "personal-projects",
            "community-projects",
        }
        relevant_heading = re.compile(
            r"(?:capabilit|achievement|personal work|engineering|verification|architecture|technology|"
            r"incident|delivery|result|metric|responsibilit|experience|stack|能力|成就|个人工作|工程|"
            r"验证|架构|技术|事故|交付|结果|指标|职责|经历)",
            re.I,
        )
        context_heading = re.compile(
            r"(?:overview|background(?:\s+and\s+goal)?|project context|"
            r"project positioning|概览|背景与目标|项目背景|项目定位)",
            re.I,
        )
        aggregated: dict[tuple[str, int, int, str, RoleMatchState, FactState, DisclosureLevel], dict[str, Any]] = {}
        for requirement in requirements:
            resume_discovery = requirement.category == "resume-discovery"
            query_terms = self._meaningful_terms(" ".join([requirement.text, *requirement.keywords, requirement.category]))
            if not query_terms:
                continue
            primary_anchor_groups: list[tuple[str, ...]] = []
            if re.search(r"(?:训练|\btrain(?:ing)?\b)", requirement.text, re.I):
                primary_anchor_groups.append((r"训练", r"\btrain(?:ing)?\b"))
            if re.search(r"(?:推理|\binference\b)", requirement.text, re.I):
                primary_anchor_groups.append((r"推理", r"\binference\b"))
            cluster_requirement = bool(re.search(
                r"(?:算力|千卡|集群|\bGPU\s*cluster|\bclusters?\b|"
                r"compute\s+cluster)",
                requirement.text,
                re.I,
            ))
            if cluster_requirement:
                query_terms.update({
                    "cluster",
                    "docker",
                    "kubernetes",
                    "swarm",
                    "容器",
                    "调度",
                })
                primary_anchor_groups.append(
                    (r"算力", r"千卡", r"\bgpu\b", r"compute\s+cluster")
                )
            if re.search(r"(?:多模态|\bmultimodal\b)", requirement.text, re.I):
                primary_anchor_groups.append((r"多模态", r"\bmultimodal\b"))
            if re.search(
                r"(?:强化学习|\breinforcement\s+learning\b)",
                requirement.text,
                re.I,
            ):
                primary_anchor_groups.append(
                    (r"强化学习", r"\breinforcement\s+learning\b")
                )
            if re.search(
                r"(?:实时控制|real[- ]time\s+control)",
                requirement.text,
                re.I,
            ):
                primary_anchor_groups.append(
                    (r"实时控制", r"real[- ]time\s+control")
                )
            if re.search(r"(?:低延迟|low[- ]latency)", requirement.text, re.I):
                primary_anchor_groups.append((r"低延迟", r"low[- ]latency"))
            if re.search(r"(?:量化|\bquantization\b)", requirement.text, re.I):
                primary_anchor_groups.append((r"量化", r"\bquantization\b"))
            if re.search(r"(?:蒸馏|\bdistillation\b)", requirement.text, re.I):
                primary_anchor_groups.append((r"蒸馏", r"\bdistillation\b"))
            if re.search(
                r"(?:模型编译|model\s+compil)",
                requirement.text,
                re.I,
            ):
                primary_anchor_groups.append((r"模型编译", r"model\s+compil"))
            matches: list[tuple[float, SourceSection, tuple[int, int, str, str], RoleMatchState, FactState, DisclosureLevel]] = []
            for section in personal_sections:
                heading_context = heading_contexts.get(
                    (section.source_path, section.start_line or 0),
                    section.section,
                )
                semantic_gate = self._semantic_gate(section, heading_context)
                if semantic_gate is None:
                    continue
                metadata = " ".join(
                    (
                        section.source_path,
                        section.title,
                        heading_context,
                        *section.outgoing_internal_links,
                    )
                )
                metadata_overlap = self._strong_terms(
                    query_terms & self._meaningful_terms(metadata)
                )
                if (
                    not metadata_overlap
                    and not relevant_heading.search(heading_context)
                    and not (
                        resume_discovery
                        and context_heading.search(heading_context)
                    )
                ):
                    continue
                inherited_fact, inherited_disclosure = document_gates.get(
                    section.source_path,
                    semantic_gate or (FactState.F5, DisclosureLevel.P3),
                )
                structural_section = self._structural_section(section)
                for unit in self._claim_units(section):
                    start_line, end_line, claim, raw = unit
                    block = self._structural_block_for_unit(
                        section, start_line, end_line
                    )
                    if block is None or not self.structural_block_is_safe(block):
                        continue
                    if _blocked(raw):
                        continue
                    facts = {
                        FactState(value.upper()) for value in _FACT_RE.findall(raw)
                    }
                    disclosures = {
                        DisclosureLevel(value.upper())
                        for value in _DISCLOSURE_RE.findall(raw)
                    }
                    explicit_facts = {
                        value
                        for value in (
                            structural_section.effective_fact_state,
                            block.fact_state,
                            *facts,
                        )
                        if value is not None
                    }
                    explicit_disclosures = {
                        value
                        for value in (
                            structural_section.effective_disclosure,
                            block.disclosure,
                            *disclosures,
                        )
                        if value is not None
                    }
                    fact = (
                        max(
                            explicit_facts,
                            key=lambda value: int(value.value[1]),
                        )
                        if explicit_facts
                        else inherited_fact
                    )
                    disclosure = (
                        max(
                            explicit_disclosures,
                            key=lambda value: int(value.value[1]),
                        )
                        if explicit_disclosures
                        else inherited_disclosure
                    )
                    if (
                        fact in {FactState.F4, FactState.F5, FactState.F6}
                        or disclosure is DisclosureLevel.P3
                    ):
                        continue
                    overlap = self._strong_terms(
                        query_terms
                        & self._meaningful_terms(f"{section.section} {claim}")
                    )
                    if not overlap:
                        continue
                    lower = claim.casefold()
                    negated = bool(re.search(
                        r"\b(?:no|not|never|without|lacks?|unverified|conflicting|must not|do not infer|"
                        r"knowledge only|study only)\b|(?:没有|未曾|不具备|不得|仅学习|无实践)",
                        lower,
                    ))
                    domain_boundary = bool(re.search(
                        r"\b(?:transferable|structurally similar|not .{0,40} experience|cannot replace|"
                        r"different (?:domain|context)|domain boundary)\b|(?:可迁移|领域不同|不能替代)",
                        lower,
                    ))
                    knowledge_only = bool(re.search(
                        r"\b(?:knowledge|concepts?|familiarity|study|studied|learning)\b.*"
                        r"\b(?:only|without|no production|no practice)\b|(?:有知识无实践|仅学习|概念学习)",
                        lower,
                    )) or bool(re.search(
                        r"(?:工程使用或了解|knowledge|study|learning)",
                        heading_context,
                        re.I,
                    ))
                    parts = PurePosixPath(section.source_path).parts
                    source_kind = parts[1] if len(parts) > 1 else ""
                    direct_exact_terms = {
                        "c++",
                        "cuda",
                        "ddp",
                        "deepspeed",
                        "docker",
                        "fsdp",
                        "grpc",
                        "jax",
                        "kubernetes",
                        "linux",
                        "megatron-lm",
                        "postgresql",
                        "prometheus",
                        "python",
                        "pytorch",
                        "redis",
                        "rust",
                        "tensorflow",
                        "terraform",
                    }
                    direct_signal = len(overlap) >= 2 or any(
                        term in direct_exact_terms
                        or (
                            _CJK_SEQUENCE_RE.fullmatch(term) is not None
                            and len(term) >= 4
                        )
                        for term in overlap
                    )
                    direct_text = f"{section.section} {claim}"
                    primary_anchors_covered = all(
                        any(
                            re.search(pattern, direct_text, re.I)
                            for pattern in group
                        )
                        for group in primary_anchor_groups
                    )
                    requires_production_scope = bool(re.search(
                        r"(?:production|large[- ]scale|real[- ]time|"
                        r"生产|大规模|千卡|实时控制|主导|集群)",
                        requirement.text,
                        re.I,
                    ))
                    nonprofessional_source = source_kind in {
                        "projects",
                        "personal-projects",
                        "community-projects",
                    }
                    if knowledge_only or (source_kind == "profile" and fact == FactState.F3):
                        match_state = RoleMatchState.KNOWLEDGE_WITHOUT_PRACTICE
                    elif (
                        not negated
                        and source_kind in direct_source_kinds
                        and fact in {FactState.F1, FactState.F2}
                        and direct_signal
                        and primary_anchors_covered
                        and not (requires_production_scope and nonprofessional_source)
                    ):
                        match_state = RoleMatchState.DIRECT_EVIDENCE
                    elif not negated or domain_boundary:
                        match_state = RoleMatchState.TRANSFERABLE_EXPERIENCE
                    else:
                        continue
                    source_quality_bonus = {
                        "work": 5,
                        "company-projects": 4,
                        "projects": 3,
                        "community-projects": 2,
                        "personal-projects": 1,
                    }.get(source_kind, 0)
                    score = (
                        len(overlap) * 10
                        + len(metadata_overlap) * 2
                        + source_quality_bonus
                    )
                    matches.append((score, section, unit, match_state, fact, disclosure))
            per_section: defaultdict[tuple[str, str], int] = defaultdict(int)
            selected = 0
            for score, section, unit, match_state, fact, disclosure in sorted(
                matches,
                key=lambda item: (-item[0], item[1].source_path, item[2][0], item[2][2]),
            ):
                section_key = (section.source_path, section.section_anchor)
                if per_section[section_key] >= 2 or selected >= 16:
                    continue
                per_section[section_key] += 1
                selected += 1
                start_line, end_line, claim, _raw = unit
                key = (section.source_path, start_line, end_line, claim, match_state, fact, disclosure)
                record = aggregated.setdefault(key, {"requirement_ids": set(), "confidence": 0.0, "section": section})
                record["requirement_ids"].add(requirement.requirement_id)
                record["confidence"] = max(record["confidence"], min(1.0, 0.45 + 0.1 * (score // 10)))

        candidates: list[EvidenceCandidate] = []
        for key, record in sorted(aggregated.items(), key=lambda item: (item[0][0], item[0][1], item[0][3], item[0][4].value)):
            source_path, start_line, end_line, claim, match_state, fact, disclosure = key
            section: SourceSection = record["section"]
            requirement_ids = sorted(record["requirement_ids"])
            identity = "\0".join((source_path, str(start_line), str(end_line), claim, match_state.value))
            candidates.append(EvidenceCandidate(
                candidate_id="candidate." + hashlib.sha256(identity.encode()).hexdigest()[:20],
                requirement_ids=requirement_ids,
                source=SourceRef(
                    path=source_path,
                    title=section.title,
                    section=section.section,
                    source_hash=section.source_hash,
                    source_type="career-source",
                ),
                source_span=SourceSpan(start_line=start_line, end_line=end_line),
                body=claim,
                snippet=claim,
                proposed_claim=claim,
                fact_state=fact,
                disclosure=disclosure,
                match_state=match_state,
                confidence=record["confidence"],
                rejection_reasons=[],
            ))
        return candidates

    def load_evidence(self, ref: EvidenceCandidate) -> EvidenceRecord:
        if ref.source.path is None or ref.source_span is None:
            raise ValueError("evidence candidate requires an owning local source span")
        section = next(
            (
                item for item in self.manifest.sections
                if item.source_path == ref.source.path
                and item.start_line is not None and item.end_line is not None
                and item.start_line <= ref.source_span.start_line
                and item.end_line >= ref.source_span.end_line
            ),
            None,
        )
        if section is None:
            raise KeyError("evidence candidate does not reference a discovered owning section")
        matching = [
            (claim, raw)
            for start_line, end_line, claim, raw in self._claim_units(section, self._section_text(section))
            if start_line == ref.source_span.start_line
            and end_line == ref.source_span.end_line
            and claim == ref.proposed_claim
        ]
        if not matching:
            raise RuntimeError("selected source claim changed after candidate retrieval")
        safe_claim, raw = matching[0]
        facts = {FactState(value.upper()) for value in _FACT_RE.findall(raw)}
        disclosures = {DisclosureLevel(value.upper()) for value in _DISCLOSURE_RE.findall(raw)}
        if facts & {FactState.F4, FactState.F5, FactState.F6} or DisclosureLevel.P3 in disclosures or _blocked(raw):
            raise ValueError("selected claim is blocked by fact, disclosure, or secret-content policy")
        return EvidenceRecord(
            evidence_id=ref.candidate_id.replace("candidate.", "evidence.", 1),
            requirement_ids=ref.requirement_ids,
            source=ref.source,
            source_span=ref.source_span,
            fact_state=ref.fact_state,
            disclosure=ref.disclosure,
            match_state=ref.match_state,
            contribution_scope="source-faithful claim; contribution boundaries preserved",
            safe_claim=safe_claim,
            forbidden_expansions=["unsupported ownership", "unsupported production scope", "unqualified metric precision"],
            freshness=Freshness(dynamic=False),
        )

    @staticmethod
    def _link_value(ref: Any) -> str:
        if isinstance(ref, str):
            return ref
        if isinstance(ref, dict):
            return str(ref.get("url") or ref.get("href") or "")
        return str(getattr(ref, "url", None) or getattr(ref, "href", None) or ref)

    def verify_links(self, refs: list[Any], *, timeout: float = 3.0) -> list[dict[str, Any]]:
        bounded_timeout = min(max(float(timeout), 0.1), 10.0)
        results: list[dict[str, Any]] = []
        opener = build_opener(_NoRedirect())
        for ref in refs:
            url = self._link_value(ref)
            parsed = urlsplit(url)
            if parsed.scheme == "mailto":
                address = unquote(parsed.path)
                valid = bool(_EMAIL_RE.fullmatch(address))
                results.append({"url": url, "status": "valid" if valid else "invalid", "status_code": None, "error": None if valid else "invalid-mailto"})
                continue
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                results.append({"url": url, "status": "unsupported", "status_code": None, "error": "public http, https, or mailto URL required"})
                continue
            try:
                if not _public_http_host(parsed):
                    results.append({"url": url, "status": "unsupported", "status_code": None, "error": "non-public-host"})
                    continue
                request = Request(url, method="HEAD", headers={"User-Agent": "china-targeted-resume/1"})
                with opener.open(request, timeout=bounded_timeout) as response:
                    code = response.status
                results.append({"url": url, "status": "reachable" if code < 400 else "unreachable", "status_code": code, "error": None})
            except HTTPError as exc:
                results.append({"url": url, "status": "unreachable", "status_code": exc.code, "error": f"http-{exc.code}"})
            except (socket.gaierror, URLError, TimeoutError, OSError) as exc:
                results.append({"url": url, "status": "unreachable", "status_code": None, "error": type(exc).__name__})
        return results
