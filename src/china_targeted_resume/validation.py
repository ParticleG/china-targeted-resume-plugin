"""Deterministic validation and approval for proof-carrying IR.

This module never attempts general semantic equivalence.  It checks source identity,
structural policy, and explicitly supported mechanical transformations, while
requiring independent review for semantic claims.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from importlib.resources.abc import Traversable
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .ir import (
    ApprovalBasis,
    ApprovedClaimIR,
    ApprovedClaimsIR,
    ClaimMode,
    ContributionQualifier,
    DisclosureAudience,
    DisclosureDecision,
    DisclosurePolicy,
    EvidenceCandidateIR,
    FactPolicy,
    NormalizedEvidenceInput,
    NormalizedRoleInput,
    ProposalDomain,
    ProposalOwner,
    ReviewDecision,
    ReviewDecisionIR,
    ReviewKind,
    ReviewOutcome,
    SourceDocumentIR,
    SourceMapIR,
    SourceReference,
    SourceSpan,
    StructuralFlags,
)
from .markdown_structure import parse_markdown_bytes, source_map_block_is_safe


SCHEMA_NAMES = (
    "source-map",
    "normalized-role-input",
    "normalized-evidence-input",
    "review-decision",
    "approved-claims",
)

_MODEL_BY_SCHEMA: dict[str, type[BaseModel]] = {
    "source-map": SourceMapIR,
    "normalized-role-input": NormalizedRoleInput,
    "normalized-evidence-input": NormalizedEvidenceInput,
    "review-decision": ReviewDecisionIR,
    "approved-claims": ApprovedClaimsIR,
}
_BODY_KEYS = {
    "body",
    "content",
    "document_body",
    "raw_source",
    "source_body",
    "source_content",
    "source_text",
    "whole_source",
}
_LIST_MARKER = re.compile(r"^(?:[-+*]|\d+[.)])(?:[ \t]+|$)")


class IRValidationError(ValueError):
    """Actionable domain validation failure."""

    def __init__(self, message: str, *, issues: Sequence[str] = ()) -> None:
        self.issues = tuple(issues) or (message,)
        super().__init__(message if len(self.issues) == 1 else "; ".join(self.issues))


TModel = TypeVar("TModel", bound=BaseModel)


def _schema_key(name: str | Path) -> str:
    if isinstance(name, Path):
        path = name
        if path.suffix != ".json":
            raise IRValidationError(f"schema path must name a .json schema: {path}")
        key = path.stem
    else:
        key = name.removesuffix(".schema.json").removesuffix(".json")
    if key not in SCHEMA_NAMES:
        raise IRValidationError(f"unknown IR schema {key!r}; expected one of {SCHEMA_NAMES}")
    return key


def _schema_resource(name: str | Path) -> Traversable:
    key = _schema_key(name)
    filename = f"{key}.schema.json"
    packaged = files("china_targeted_resume").joinpath("schemas", filename)
    if packaged.is_file():
        return packaged

    # Editable/source-tree execution keeps the schema authority at repository
    # root; wheels force-include the same files below the installed package.
    source_tree = Path(__file__).resolve().parents[2] / "schemas" / filename
    if source_tree.is_file():
        return source_tree
    raise IRValidationError(
        "bundled IR schema is missing from both installed package resources "
        f"and the source tree: {filename}"
    )


def load_schema(name: str | Path) -> dict[str, Any]:
    """Load one of the five bundled Draft 2020-12 schemas."""

    resource = _schema_resource(name)
    try:
        with resource.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise IRValidationError(f"bundled IR schema is missing: {resource}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IRValidationError(f"could not read IR schema {resource}: {exc}") from exc
    if not isinstance(value, dict):
        raise IRValidationError(f"IR schema {resource} must be a JSON object")
    return value


def _reject_source_bodies(value: Any, *, path: str = "$root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in _BODY_KEYS:
                raise IRValidationError(
                    f"{path}.{key}: source-body-shaped fields are forbidden; retain only metadata and exact per-proposal quotes"
                )
            _reject_source_bodies(nested, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_source_bodies(nested, path=f"{path}[{index}]")


def _format_pydantic_error(exc: ValidationError) -> list[str]:
    issues: list[str] = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ())) or "$root"
        message = str(item.get("msg", "invalid value"))
        issues.append(f"{location}: {message}")
    return issues or [str(exc)]


def validate_schema_document(value: Any, schema: str | Path) -> BaseModel:
    """Validate a JSON-compatible value against both its schema and canonical model."""

    key = _schema_key(schema)
    _reject_source_bodies(value)
    document = load_schema(key)
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(document)
        errors = sorted(Draft202012Validator(document).iter_errors(value), key=lambda item: list(item.path))
        if errors:
            issues = []
            for error in errors:
                location = ".".join(str(part) for part in error.absolute_path) or "$root"
                issues.append(f"{location}: {error.message}")
            raise IRValidationError(f"{key} schema validation failed", issues=issues)
    except ImportError:
        # Runtime installations intentionally do not need the dev-only jsonschema
        # package; Pydantic still enforces the same closed model contract.
        pass
    except IRValidationError:
        raise
    except Exception as exc:
        raise IRValidationError(f"{key} schema validation failed: {exc}") from exc
    model_type = _MODEL_BY_SCHEMA[key]
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise IRValidationError(f"{key} canonical model validation failed", issues=_format_pydantic_error(exc)) from exc


def validate_ir(value: Any, model_or_schema: str | type[TModel]) -> TModel | BaseModel:
    """Validate one IR value by schema name or canonical model type."""

    if isinstance(model_or_schema, str):
        return validate_schema_document(value, model_or_schema)
    try:
        return model_or_schema.model_validate(value)
    except ValidationError as exc:
        raise IRValidationError("canonical IR model validation failed", issues=_format_pydantic_error(exc)) from exc


def _read_regular_source(root: Path, relative: str) -> tuple[Path, bytes]:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise IRValidationError(f"source path {relative!r} does not exist below source root") from exc
    if not resolved.is_relative_to(root) or candidate.is_symlink() or not resolved.is_file():
        raise IRValidationError(f"source path {relative!r} escapes source root or is not a regular file")
    # O_NOFOLLOW protects the final component; containment protects symlinked
    # parent directories.  The source remains read-only throughout validation.
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(fd)
    except OSError as exc:
        raise IRValidationError(f"could not securely read source path {relative!r}: {exc}") from exc
    return resolved, data


def _line_for_byte(data: bytes, offset: int) -> int:
    return data[:offset].count(b"\n") + 1


def _verify_span(data: bytes, span: SourceSpan, quote: str | None, *, label: str) -> None:
    if span.start_byte > len(data) or span.end_byte > len(data):
        raise IRValidationError(
            f"{label}: UTF-8 byte span {span.start_byte}:{span.end_byte} exceeds source length {len(data)}"
        )
    expected_start = _line_for_byte(data, span.start_byte)
    # A half-open span ending at a newline belongs to the line containing that
    # newline, not the following line.
    expected_end = _line_for_byte(data, max(span.start_byte, span.end_byte - 1))
    if span.start_line != expected_start or span.end_line != expected_end:
        raise IRValidationError(
            f"{label}: line span {span.start_line}:{span.end_line} disagrees with UTF-8 byte span; expected {expected_start}:{expected_end}"
        )
    if quote is not None:
        try:
            actual = data[span.start_byte : span.end_byte].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IRValidationError(f"{label}: byte span does not contain valid UTF-8") from exc
        if actual != quote:
            raise IRValidationError(f"{label}: exact_quote does not match source bytes at the declared span")


def _lookup_structural(
    lookup: Callable[..., Any] | Mapping[Any, Any] | None,
    *,
    path: str,
    span: SourceSpan,
    item: Any,
) -> Any:
    if lookup is None:
        return None
    if callable(lookup):
        for args in ((path, span), (path, span.start_byte, span.end_byte), (item,)):
            try:
                result = lookup(*args)
            except TypeError:
                continue
            if result is not None:
                return result
        return None
    keys = (
        (path, span.start_byte, span.end_byte),
        (path, span.start_byte, span.end_byte, span.start_line, span.end_line),
        path,
    )
    for key in keys:
        if key in lookup:
            return lookup[key]
    return None


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)




def _parsed_flag_value(parsed: Any, name: str, default: Any = None) -> Any:
    value = _value(parsed, name, default)
    if hasattr(value, "value"):
        return value.value
    return value


def _parsed_effective_fact(parsed: Any) -> FactPolicy:
    value = _parsed_flag_value(parsed, "effective_fact_policy", None)
    if value is None:
        value = _parsed_flag_value(parsed, "effective_fact_state", None)
    if value is None:
        value = _parsed_flag_value(parsed, "document_fact_policy", None)
    if value is None:
        value = _parsed_flag_value(parsed, "document_fact_state", None)
    return FactPolicy(str(value or FactPolicy.F5.value))


def _parsed_effective_disclosure(parsed: Any) -> DisclosurePolicy:
    value = _parsed_flag_value(parsed, "effective_disclosure_policy", None)
    if value is None:
        value = _parsed_flag_value(parsed, "effective_disclosure", None)
    if value is None:
        value = _parsed_flag_value(parsed, "document_disclosure_policy", None)
    if value is None:
        value = _parsed_flag_value(parsed, "document_disclosure", None)
    return DisclosurePolicy(str(value or DisclosurePolicy.P3.value))


def _parsed_structural_flags(parsed: Any, *, block_kind: str) -> StructuralFlags:
    raw = _value(parsed, "flags", parsed)
    return StructuralFlags(
        block_kind=block_kind,
        inside_fence=bool(_parsed_flag_value(raw, "inside_fence", False)),
        inside_blockquote=bool(_parsed_flag_value(raw, "inside_blockquote", False)),
        inside_html=bool(_parsed_flag_value(raw, "inside_html", False)),
        is_example=bool(_parsed_flag_value(raw, "inside_example", _parsed_flag_value(raw, "is_example", False))),
        is_template=bool(_parsed_flag_value(raw, "inside_template", False)),
        is_quoted=bool(_parsed_flag_value(raw, "inside_quoted", _parsed_flag_value(raw, "is_quoted", False))),
        negative_instruction=bool(_parsed_flag_value(raw, "negative_instruction", False)),
        secret_path=bool(_parsed_flag_value(raw, "secret_path", False)),
        secret_content=bool(_parsed_flag_value(raw, "secret_content", False)),
        malformed=bool(_parsed_flag_value(raw, "malformed", False)),
        effective_fact_policy=_parsed_effective_fact(parsed),
        effective_disclosure_policy=_parsed_effective_disclosure(parsed),
    )


def _location_span(location: Any) -> SourceSpan:
    return SourceSpan(
        start_line=int(_value(location, "start_line")),
        end_line=int(_value(location, "end_line")),
        start_byte=int(_value(location, "start_byte")),
        end_byte=int(_value(location, "end_byte")),
    )


def _same_span(left: SourceSpan, right: Any) -> bool:
    return (
        left.start_line == int(_value(right, "start_line"))
        and left.end_line == int(_value(right, "end_line"))
        and left.start_byte == int(_value(right, "start_byte"))
        and left.end_byte == int(_value(right, "end_byte"))
    )


def _check_structural_flags(
    expected: StructuralFlags,
    actual: Any,
    *,
    label: str,
    reject_blocked: bool = True,
) -> None:
    if actual is not None:
        for name in (
            "block_kind",
            "inside_fence",
            "inside_blockquote",
            "inside_html",
            "is_example",
            "is_template",
            "is_quoted",
            "negative_instruction",
            "secret_path",
            "secret_content",
            "malformed",
            "effective_fact_policy",
            "effective_disclosure_policy",
        ):
            actual_value = _value(actual, name, None)
            if actual_value is None:
                continue
            if hasattr(actual_value, "value"):
                actual_value = actual_value.value
            expected_value = getattr(expected, name)
            if hasattr(expected_value, "value"):
                expected_value = expected_value.value
            if actual_value != expected_value:
                raise IRValidationError(f"{label}: structural flag {name}={actual_value!r} disagrees with IR {expected_value!r}")
    if reject_blocked and expected.blocked:
        raise IRValidationError(f"{label}: blocked fence/quote/example/HTML/F6/P3 content cannot become an evidence proposal")

@dataclass(slots=True)
class _ParsedSourceContext:
    value: SourceMapIR
    root: Path
    docs_by_id: dict[str, SourceDocumentIR]
    parsed_by_path: dict[str, Any]
    data_by_path: dict[str, bytes]
    parsed_sections: dict[str, tuple[str, Any]]
    parsed_blocks: dict[str, tuple[str, Any]]
    structural_lookup: Callable[..., Any] | Mapping[Any, Any] | None


def _coerce_source_map(value: SourceMapIR | Mapping[str, Any]) -> SourceMapIR:
    try:
        return value if isinstance(value, SourceMapIR) else SourceMapIR.model_validate(value)
    except ValidationError as exc:
        raise IRValidationError("source map canonical model validation failed", issues=_format_pydantic_error(exc)) from exc


def _build_source_context(
    source_map: SourceMapIR,
    source_root: str | os.PathLike[str],
    structural_lookup: Callable[..., Any] | Mapping[Any, Any] | None,
) -> _ParsedSourceContext:
    root = Path(source_root).expanduser()
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise IRValidationError(f"source root does not exist: {source_root}") from exc
    if not root.is_dir():
        raise IRValidationError(f"source root must be a real directory: {source_root}")

    docs_by_id: dict[str, SourceDocumentIR] = {}
    parsed_by_path: dict[str, Any] = {}
    data_by_path: dict[str, bytes] = {}
    for document in source_map.documents:
        if document.document_id in docs_by_id:
            raise IRValidationError(f"source map contains duplicate document ID {document.document_id!r}")
        if document.path in data_by_path:
            raise IRValidationError(f"source map contains duplicate document path {document.path!r}")
        _, data = _read_regular_source(root, document.path)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if digest != document.source_hash:
            raise IRValidationError(f"document {document.document_id!r}: source_hash does not match {document.path!r}")
        try:
            parsed = parse_markdown_bytes(data, path=document.path)
        except Exception as exc:
            raise IRValidationError(f"document {document.document_id!r}: structural Markdown parse failed: {exc}") from exc
        if parsed.path != document.path or parsed.source_hash != document.source_hash:
            raise IRValidationError(f"document {document.document_id!r}: parsed source identity differs from submitted metadata")
        parsed_fact = _parsed_effective_fact(parsed)
        parsed_disclosure = _parsed_effective_disclosure(parsed)
        if parsed_fact != document.document_fact_policy:
            raise IRValidationError(
                f"document {document.document_id!r}: document fact policy {document.document_fact_policy.value} disagrees with parsed {parsed_fact.value}"
            )
        if parsed_disclosure != document.document_disclosure_policy:
            raise IRValidationError(
                f"document {document.document_id!r}: document disclosure policy {document.document_disclosure_policy.value} disagrees with parsed {parsed_disclosure.value}"
            )
        if tuple(document.validation_warnings) != tuple(parsed.validation_warnings):
            raise IRValidationError(f"document {document.document_id!r}: validation_warnings do not match parser warnings")
        if document.span is not None:
            _verify_span(data, document.span, None, label=f"document {document.document_id}")
        docs_by_id[document.document_id] = document
        parsed_by_path[document.path] = parsed
        data_by_path[document.path] = data

    parsed_sections: dict[str, tuple[str, Any]] = {}
    parsed_blocks: dict[str, tuple[str, Any]] = {}
    for document in source_map.documents:
        parsed = parsed_by_path[document.path]
        for section in parsed.sections:
            if section.identity in parsed_sections:
                raise IRValidationError(f"parsed source documents contain duplicate section identity {section.identity!r}")
            parsed_sections[section.identity] = (document.path, section)
        for block in parsed.blocks:
            if block.identity in parsed_blocks:
                raise IRValidationError(f"parsed source documents contain duplicate block identity {block.identity!r}")
            parsed_blocks[block.identity] = (document.path, block)
    return _ParsedSourceContext(
        value=source_map,
        root=root,
        docs_by_id=docs_by_id,
        parsed_by_path=parsed_by_path,
        data_by_path=data_by_path,
        parsed_sections=parsed_sections,
        parsed_blocks=parsed_blocks,
        structural_lookup=structural_lookup,
    )


def _compare_context_flags(
    context: _ParsedSourceContext,
    submitted: StructuralFlags,
    parsed_item: Any,
    *,
    path: str,
    label: str,
    block_kind: str,
    reject_blocked: bool,
) -> None:
    expected = _parsed_structural_flags(parsed_item, block_kind=block_kind)
    _check_structural_flags(expected, submitted, label=label, reject_blocked=reject_blocked)
    hook = _lookup_structural(
        context.structural_lookup,
        path=path,
        span=_location_span(_value(parsed_item, "location")),
        item=parsed_item,
    )
    if hook is not None:
        _check_structural_flags(expected, hook, label=f"{label} structural lookup", reject_blocked=False)


def _validate_source_structure(context: _ParsedSourceContext) -> None:
    for section in context.value.sections:
        document = context.docs_by_id.get(section.document_id)
        if document is None:
            raise IRValidationError(f"section {section.section_id!r}: unknown document {section.document_id!r}")
        parsed_pair = context.parsed_sections.get(section.section_id)
        if parsed_pair is None or parsed_pair[0] != document.path:
            raise IRValidationError(f"section {section.section_id!r}: no exact parsed section identity")
        parsed_section = parsed_pair[1]
        if not _same_span(section.span, parsed_section.location):
            raise IRValidationError(f"section {section.section_id!r}: submitted span differs from parsed section span")
        if section.heading != parsed_section.heading:
            raise IRValidationError(f"section {section.section_id!r}: heading differs from parsed source")
        if tuple(section.heading_ancestry) != tuple(parsed_section.heading_ancestry):
            raise IRValidationError(f"section {section.section_id!r}: heading ancestry differs from parsed source")
        if section.duplicate_index != int(parsed_section.occurrence):
            raise IRValidationError(f"section {section.section_id!r}: duplicate heading occurrence differs from parsed source")
        expected_block_ids = tuple(
            item.identity for item in parsed_section.blocks if source_map_block_is_safe(item)
        )
        if tuple(section.block_ids) != expected_block_ids:
            raise IRValidationError(f"section {section.section_id!r}: block identity list differs from parsed source")
        _compare_context_flags(
            context,
            section.structural_flags,
            parsed_section,
            path=document.path,
            label=f"section {section.section_id}",
            block_kind=section.structural_flags.block_kind,
            reject_blocked=False,
        )
    for block in context.value.blocks:
        document = context.docs_by_id.get(block.document_id)
        if document is None:
            raise IRValidationError(f"block {block.block_id!r}: unknown document {block.document_id!r}")
        parsed_pair = context.parsed_blocks.get(block.block_id)
        if parsed_pair is None or parsed_pair[0] != document.path:
            raise IRValidationError(f"block {block.block_id!r}: no exact parsed block identity")
        parsed_block = parsed_pair[1]
        if not _same_span(block.span, parsed_block.location):
            raise IRValidationError(f"block {block.block_id!r}: submitted span differs from parsed block span")
        if block.section_id != parsed_block.section_identity:
            raise IRValidationError(f"block {block.block_id!r}: owning section identity differs from parsed source")
        if tuple(block.heading_ancestry) != tuple(parsed_block.heading_ancestry):
            raise IRValidationError(f"block {block.block_id!r}: heading ancestry differs from parsed source")
        _compare_context_flags(
            context,
            block.structural_flags,
            parsed_block,
            path=document.path,
            label=f"block {block.block_id}",
            block_kind=parsed_block.kind,
            reject_blocked=False,
        )


def _verify_source_reference(context: _ParsedSourceContext, ref: SourceReference, *, label: str) -> None:
    document = next((item for item in context.value.documents if item.path == ref.path), None)
    if document is None:
        raise IRValidationError(f"{label}: source path {ref.path!r} is not in the source map documents")
    parsed = context.parsed_by_path[ref.path]
    data = context.data_by_path[ref.path]
    if ref.source_hash != document.source_hash:
        raise IRValidationError(f"{label}: source hash differs from document hash")
    _verify_span(data, ref.span, ref.exact_quote, label=label)
    containing = [
        block
        for block in parsed.blocks
        if block.location.start_byte <= ref.span.start_byte
        and ref.span.end_byte <= block.location.end_byte
    ]
    if ref.block_id is not None:
        owner = next((item for item in containing if item.identity == ref.block_id), None)
        if owner is None:
            raise IRValidationError(f"{label}: block_id is not an exact or containing parsed block")
    else:
        if not containing:
            raise IRValidationError(f"{label}: source span has no owning parsed block")
        owner = min(containing, key=lambda item: item.location.end_byte - item.location.start_byte)
    if ref.section_id is not None and ref.section_id != owner.section_identity:
        raise IRValidationError(f"{label}: section_id does not own the parsed block")
    if ref.section_id is not None:
        section = next((item for item in parsed.sections if item.identity == ref.section_id), None)
        if section is None or not (
            section.location.start_byte <= ref.span.start_byte
            and ref.span.end_byte <= section.location.end_byte
        ):
            raise IRValidationError(f"{label}: section_id does not contain the submitted span")
    if tuple(ref.heading_ancestry) != tuple(owner.heading_ancestry):
        raise IRValidationError(f"{label}: heading ancestry does not match the owning parsed block")
    _compare_context_flags(
        context,
        ref.structural_flags,
        owner,
        path=ref.path,
        label=label,
        block_kind=owner.kind,
        reject_blocked=True,
    )


def revalidate_source_map(
    source_map: SourceMapIR | Mapping[str, Any],
    source_root: str | os.PathLike[str],
    structural_lookup: Callable[..., Any] | Mapping[Any, Any] | None = None,
) -> SourceMapIR:
    """Re-open, parse, and prove every structural and semantic source identity."""

    value = _coerce_source_map(source_map)
    context = _build_source_context(value, source_root, structural_lookup)
    _validate_source_structure(context)
    for proposal in value.proposals:
        _verify_source_reference(context, proposal.source, label=f"proposal {proposal.proposal_id}")
    return value


def _coerce_evidence_input(value: NormalizedEvidenceInput | Mapping[str, Any]) -> NormalizedEvidenceInput:
    try:
        return value if isinstance(value, NormalizedEvidenceInput) else NormalizedEvidenceInput.model_validate(value)
    except ValidationError as exc:
        raise IRValidationError("normalized evidence input is invalid", issues=_format_pydantic_error(exc)) from exc


def _coerce_role_input(value: NormalizedRoleInput | Mapping[str, Any]) -> NormalizedRoleInput:
    try:
        return value if isinstance(value, NormalizedRoleInput) else NormalizedRoleInput.model_validate(value)
    except ValidationError as exc:
        raise IRValidationError("normalized role input is invalid", issues=_format_pydantic_error(exc)) from exc


def _match_origin_proposal(
    source_map: SourceMapIR,
    proposal_id: str | None,
    ref: SourceReference,
    *,
    label: str,
    allowed_domains: set[Any] | None = None,
) -> Any:
    if proposal_id is None:
        return None
    proposal = next((item for item in source_map.proposals if item.proposal_id == proposal_id), None)
    if proposal is None:
        raise IRValidationError(f"{label}: origin proposal {proposal_id!r} is missing from source map")
    if allowed_domains is not None and proposal.domain not in allowed_domains:
        raise IRValidationError(f"{label}: origin proposal domain {proposal.domain.value!r} is not valid for this input")
    if proposal.source.model_dump(mode="json") != ref.model_dump(mode="json"):
        raise IRValidationError(f"{label}: source reference differs from its origin proposal {proposal_id!r}")
    return proposal


def revalidate_evidence_input(
    evidence_input: NormalizedEvidenceInput | Mapping[str, Any],
    source_map: SourceMapIR | Mapping[str, Any],
    source_root: str | os.PathLike[str],
    structural_lookup: Callable[..., Any] | Mapping[Any, Any] | None = None,
) -> NormalizedEvidenceInput:
    """Revalidate every evidence candidate against parser-authoritative source metadata."""

    evidence = _coerce_evidence_input(evidence_input)
    source = _coerce_source_map(source_map)
    context = _build_source_context(source, source_root, structural_lookup)
    _validate_source_structure(context)
    for candidate in evidence.candidates:
        label = f"evidence {candidate.evidence_id}"
        if candidate.proposal_id is None:
            raise IRValidationError(f"{label}: evidence candidates require an origin proposal ID")
        _verify_source_reference(context, candidate.source, label=label)
        _match_origin_proposal(
            source,
            candidate.proposal_id,
            candidate.source,
            label=label,
            allowed_domains={ProposalDomain.PERSONAL, ProposalDomain.EVIDENCE},
        )
    return evidence


def revalidate_role_input(
    role_input: NormalizedRoleInput | Mapping[str, Any],
    source_map: SourceMapIR | Mapping[str, Any],
    source_root: str | os.PathLike[str],
    structural_lookup: Callable[..., Any] | Mapping[Any, Any] | None = None,
) -> NormalizedRoleInput:
    """Revalidate role proposals and explicit requirement sources."""

    role = _coerce_role_input(role_input)
    source = _coerce_source_map(source_map)
    context = _build_source_context(source, source_root, structural_lookup)
    _validate_source_structure(context)
    for proposal in role.proposals:
        label = f"role proposal {proposal.proposal_id}"
        _verify_source_reference(context, proposal.source, label=label)
        _match_origin_proposal(
            source,
            proposal.proposal_id,
            proposal.source,
            label=label,
            allowed_domains={ProposalDomain.ROLE, ProposalDomain.JOB_DESCRIPTION},
        )
    for requirement in role.requirements:
        if requirement.source is None:
            if requirement.origin != "inferred":
                raise IRValidationError(
                    f"requirement {requirement.requirement_id!r}: explicit requirements require an exact source reference"
                )
            continue
        _verify_source_reference(context, requirement.source, label=f"requirement {requirement.requirement_id}")
    return role


def _collapse_mechanical_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _remove_list_markers(value: str) -> str:
    lines = value.splitlines()
    normalized: list[str] = []
    for line in lines:
        stripped = line.strip()
        marker = _LIST_MARKER.match(stripped)
        normalized.append(stripped[marker.end() :] if marker else stripped)
    return " ".join(normalized)


def normalize_extractive_claim(exact_quote: str, proposed_claim: str) -> str:
    """Apply only whitespace and list-marker normalization; reject paraphrase."""

    if not isinstance(exact_quote, str) or not isinstance(proposed_claim, str):
        raise IRValidationError("extractive normalization requires string exact_quote and proposed_claim")
    if not exact_quote.strip() or not proposed_claim.strip():
        raise IRValidationError("extractive normalization requires non-empty text")
    if exact_quote == proposed_claim:
        return proposed_claim
    if _collapse_mechanical_whitespace(exact_quote) == _collapse_mechanical_whitespace(proposed_claim):
        return proposed_claim.strip()
    if _collapse_mechanical_whitespace(_remove_list_markers(exact_quote)) == _collapse_mechanical_whitespace(
        _remove_list_markers(proposed_claim)
    ):
        return proposed_claim.strip()
    raise IRValidationError(
        "extractive claim is not an exact quote or a supported mechanical whitespace/list-marker normalization"
    )


def _decisions(value: ReviewDecisionIR | Mapping[str, Any] | Sequence[ReviewDecision] | Sequence[Mapping[str, Any]]) -> list[ReviewDecision]:
    if isinstance(value, ReviewDecisionIR):
        return list(value.decisions)
    if isinstance(value, Mapping):
        try:
            return list(ReviewDecisionIR.model_validate(value).decisions)
        except ValidationError as exc:
            raise IRValidationError("review decision IR is invalid", issues=_format_pydantic_error(exc)) from exc
    result: list[ReviewDecision] = []
    for item in value:
        if isinstance(item, ReviewDecision):
            result.append(item)
        else:
            try:
                result.append(ReviewDecision.model_validate(item))
            except ValidationError as exc:
                raise IRValidationError("review decision is invalid", issues=_format_pydantic_error(exc)) from exc
    return result


def _qualifier_texts(values: Sequence[str]) -> list[ContributionQualifier]:
    return [ContributionQualifier(text=item) for item in values]


def _metric_texts(values: Sequence[str]) -> list[MetricQualifier]:
    return [MetricQualifier(text=item) for item in values]


def approve_claims(
    evidence_input: NormalizedEvidenceInput | Mapping[str, Any],
    reviews: ReviewDecisionIR | Mapping[str, Any] | Sequence[ReviewDecision] | Sequence[Mapping[str, Any]],
    *,
    approved_safe_claims: Mapping[str, str] | None = None,
    user_confirmations: Mapping[str, bool] | None = None,
) -> ApprovedClaimsIR:
    """Aggregate reviewer decisions and produce exact-text approved claims."""

    try:
        evidence = evidence_input if isinstance(evidence_input, NormalizedEvidenceInput) else NormalizedEvidenceInput.model_validate(evidence_input)
    except ValidationError as exc:
        raise IRValidationError("normalized evidence input is invalid", issues=_format_pydantic_error(exc)) from exc
    decisions = _decisions(reviews)
    by_evidence: dict[str, list[ReviewDecision]] = {}
    for decision in decisions:
        by_evidence.setdefault(decision.evidence_id, []).append(decision)
    known_ids = {candidate.evidence_id for candidate in evidence.candidates}
    unknown = sorted(set(by_evidence).difference(known_ids))
    if unknown:
        raise IRValidationError(f"review decisions reference unknown evidence IDs: {unknown}")
    confirmations = user_confirmations or {}
    proposed_safe = approved_safe_claims or {}
    if evidence.unresolved_questions:
        raise IRValidationError(
            f"normalized evidence input {evidence.input_id!r} has unresolved questions; approval fails closed until revalidated"
        )
    claims: list[ApprovedClaimIR] = []
    for candidate in evidence.candidates:
        candidate_reviews = by_evidence.get(candidate.evidence_id, [])
        if candidate.owner != ProposalOwner.CANDIDATE:
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: owner {candidate.owner.value} is not candidate; ownership must be resolved in reviewed candidate IR"
            )
        if any(item.review_kind == ReviewKind.REQUIREMENT for item in candidate_reviews):
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: requirement review is not valid for claim approval"
            )
        unsupported = [
            item
            for item in candidate_reviews
            if item.outcome
            in {
                ReviewOutcome.REJECT,
                ReviewOutcome.DISAGREE,
                ReviewOutcome.NEEDS_CONFIRMATION,
            }
        ]
        if unsupported:
            kinds = sorted({item.review_kind.value for item in unsupported})
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: unsupported reviewer disagreement/rejection in {kinds}; approval fails closed"
            )
        if candidate.source.structural_flags.blocked:
            raise IRValidationError(f"evidence {candidate.evidence_id!r}: blocked structural policy cannot be approved")
        fact_policy = candidate.source.structural_flags.effective_fact_policy
        if fact_policy == FactPolicy.F3:
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: fact policy F3 requires parser-revalidated current freshness proof before approval"
            )
        if fact_policy in {FactPolicy.F4, FactPolicy.F5}:
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: fact policy {fact_policy.value} is unapprovable without a confirmed fact state"
            )
        if candidate.claim_mode == ClaimMode.EXTRACTIVE and candidate.unresolved_questions:
            raise IRValidationError(
                f"evidence {candidate.evidence_id!r}: extractive approval cannot proceed with unresolved questions"
            )
        if candidate.claim_mode == ClaimMode.EXTRACTIVE:
            claim_text = normalize_extractive_claim(
                candidate.source.exact_quote,
                proposed_safe.get(candidate.evidence_id, candidate.proposed_claim),
            )
            basis = ApprovalBasis.MECHANICAL
            reviewer_ids: list[str] = []
            disclosure = DisclosureDecision.ALLOWED
            audience: DisclosureAudience | None = DisclosureAudience.RECRUITER
            purpose = "resume evidence"
            contribution_qualifiers = _qualifier_texts(candidate.contribution_qualifiers)
            metric_qualifiers = _metric_texts(candidate.metric_qualifiers)
            privacy = [item for item in candidate_reviews if item.review_kind == ReviewKind.PRIVACY]
            if candidate.source.structural_flags.effective_disclosure_policy == DisclosurePolicy.P2:
                if len(privacy) != 1 or privacy[0].outcome != ReviewOutcome.APPROVE:
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: P2 extractive disclosure requires one approving privacy review"
                    )
                if privacy[0].disclosure_decision != DisclosureDecision.ALLOWED:
                    raise IRValidationError(f"evidence {candidate.evidence_id!r}: privacy review did not allow disclosure")
                if (
                    privacy[0].disclosure_audience
                    not in {DisclosureAudience.RECRUITER, DisclosureAudience.HIRING_TEAM}
                    or privacy[0].disclosure_purpose != "targeted_application"
                ):
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: confirmation privacy scope must be recruiter or hiring_team with targeted_application purpose"
                    )
                if privacy[0].approved_safe_claim != claim_text:
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: approved_safe_claim does not exactly match all approving reviews"
                    )
                if confirmations.get(candidate.evidence_id) is not True:
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: P2 extractive approval requires explicit user confirmation"
                    )
                basis = ApprovalBasis.USER_CONFIRMED
                reviewer_ids = [privacy[0].review_id]
                disclosure = privacy[0].disclosure_decision
                audience = privacy[0].disclosure_audience
                purpose = privacy[0].disclosure_purpose
        else:
            required = {
                ReviewKind.EVIDENCE,
                ReviewKind.CONTRIBUTION_METRIC,
                ReviewKind.PRIVACY,
            }
            selected: dict[ReviewKind, ReviewDecision] = {}
            for kind in required:
                matches = [item for item in candidate_reviews if item.review_kind == kind]
                if len(matches) != 1:
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: reviewed-semantic approval requires exactly one {kind.value} review"
                    )
                review = matches[0]
                if review.outcome != ReviewOutcome.APPROVE:
                    raise IRValidationError(
                        f"evidence {candidate.evidence_id!r}: {kind.value} review did not approve; disagreement fails closed"
                    )
                selected[kind] = review
            reviewer_ids_set = {item.reviewer_id for item in selected.values()}
            if len(reviewer_ids_set) != len(required):
                raise IRValidationError(
                    f"evidence {candidate.evidence_id!r}: evidence, contribution/metric, and privacy reviewers must be independent"
                )
            privacy = selected[ReviewKind.PRIVACY]
            if privacy.disclosure_decision != DisclosureDecision.ALLOWED:
                raise IRValidationError(f"evidence {candidate.evidence_id!r}: privacy reviewer did not allow disclosure")
            claim_text = proposed_safe.get(candidate.evidence_id, "")
            if not claim_text:
                raise IRValidationError(
                    f"evidence {candidate.evidence_id!r}: reviewed-semantic approval requires exact approved_safe_claim"
                )
            if (
                candidate.source.structural_flags.effective_disclosure_policy == DisclosurePolicy.P2
                and (
                    privacy.disclosure_audience
                    not in {DisclosureAudience.RECRUITER, DisclosureAudience.HIRING_TEAM}
                    or privacy.disclosure_purpose != "targeted_application"
                )
            ):
                raise IRValidationError(
                    f"evidence {candidate.evidence_id!r}: confirmation privacy scope must be recruiter or hiring_team with targeted_application purpose"
                )
            if any(item.approved_safe_claim != claim_text for item in selected.values()):
                raise IRValidationError(
                    f"evidence {candidate.evidence_id!r}: approved_safe_claim does not exactly match all approving reviews"
                )
            qualifier_review = selected[ReviewKind.CONTRIBUTION_METRIC]
            contribution_qualifiers = list(qualifier_review.contribution_qualifiers)
            metric_qualifiers = list(qualifier_review.metric_qualifiers)
            confirmation_reviews = [
                item
                for item in selected.values()
                if item.user_confirmation_required or item.questions
            ]
            needs_confirmation = bool(candidate.unresolved_questions) or (
                candidate.source.structural_flags.effective_disclosure_policy == DisclosurePolicy.P2
            ) or bool(confirmation_reviews)
            confirmed = confirmations.get(candidate.evidence_id) is True
            if needs_confirmation and not confirmed:
                raise IRValidationError(f"evidence {candidate.evidence_id!r}: required user confirmation is missing")
            basis = ApprovalBasis.USER_CONFIRMED if confirmed else ApprovalBasis.INDEPENDENT_REVIEW
            reviewer_ids = [
                selected[kind].review_id
                for kind in (ReviewKind.EVIDENCE, ReviewKind.CONTRIBUTION_METRIC, ReviewKind.PRIVACY)
            ]
            disclosure = privacy.disclosure_decision or DisclosureDecision.NEEDS_CONFIRMATION
            audience = privacy.disclosure_audience
            purpose = privacy.disclosure_purpose
        claims.append(
            ApprovedClaimIR(
                claim_id=f"claim.{candidate.evidence_id}",
                origin_evidence_ids=[candidate.evidence_id],
                approved_safe_claim=claim_text,
                approval_basis=basis,
                reviewer_decision_ids=reviewer_ids,
                claim_mode=candidate.claim_mode,
                contribution_qualifiers=contribution_qualifiers,
                metric_qualifiers=metric_qualifiers,
                disclosure_decision=disclosure,
                disclosure_audience=audience,
                disclosure_purpose=purpose,
            )
        )
    return ApprovedClaimsIR(claims=claims)


def check_provenance_closure(
    approved_claims: ApprovedClaimsIR | Mapping[str, Any],
    evidence_input: NormalizedEvidenceInput | Mapping[str, Any],
    review_decisions: ReviewDecisionIR
    | Mapping[str, Any]
    | Sequence[ReviewDecision]
    | Sequence[Mapping[str, Any]] = (),
    visible_claim_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Check that visible claims close over approved evidence, reviews, and sources."""

    try:
        approved = (
            approved_claims
            if isinstance(approved_claims, ApprovedClaimsIR)
            else ApprovedClaimsIR.model_validate(approved_claims)
        )
        evidence = (
            evidence_input
            if isinstance(evidence_input, NormalizedEvidenceInput)
            else NormalizedEvidenceInput.model_validate(evidence_input)
        )
    except ValidationError as exc:
        raise IRValidationError(
            "provenance closure input is invalid",
            issues=_format_pydantic_error(exc),
        ) from exc
    decisions = _decisions(review_decisions)
    evidence_by_id = {
        candidate.evidence_id: candidate for candidate in evidence.candidates
    }
    review_ids = {decision.review_id for decision in decisions}
    approved_ids = {claim.claim_id for claim in approved.claims}
    missing_origin: set[str] = set()
    missing_reviews: set[str] = set()
    missing_sources: set[str] = set()
    for claim in approved.claims:
        for evidence_id in claim.origin_evidence_ids:
            origin = evidence_by_id.get(evidence_id)
            if origin is None:
                missing_origin.add(evidence_id)
                continue
            source = origin.source
            if (
                not source.path
                or not source.source_hash
                or not source.exact_quote
                or (source.section_id is None and source.block_id is None)
            ):
                missing_sources.add(evidence_id)
        missing_reviews.update(
            review_id
            for review_id in claim.reviewer_decision_ids
            if review_id not in review_ids
        )
    visible = (
        list(visible_claim_ids)
        if visible_claim_ids is not None
        else [claim.claim_id for claim in approved.claims]
    )
    uncovered = {claim_id for claim_id in visible if claim_id not in approved_ids}
    missing_origin_ids = sorted(missing_origin)
    missing_review_ids = sorted(missing_reviews)
    missing_source_ids = sorted(missing_sources)
    uncovered_ids = sorted(uncovered)
    missing = sorted(
        set(
            missing_origin_ids
            + missing_review_ids
            + missing_source_ids
            + uncovered_ids
        )
    )
    return {
        "closed": not missing,
        "missing": missing,
        "missing_origin_evidence_ids": missing_origin_ids,
        "missing_review_decision_ids": missing_review_ids,
        "missing_source_evidence_ids": missing_source_ids,
        "uncovered_claim_ids": uncovered_ids,
    }


def lock_approved_claims(
    approved_claims: ApprovedClaimsIR | Mapping[str, Any],
    final_claims: Mapping[str, str] | None = None,
) -> ApprovedClaimsIR:
    """Return validated claims and reject any final text that is not exact."""

    try:
        value = approved_claims if isinstance(approved_claims, ApprovedClaimsIR) else ApprovedClaimsIR.model_validate(approved_claims)
    except ValidationError as exc:
        raise IRValidationError("approved claims IR is invalid", issues=_format_pydantic_error(exc)) from exc
    if final_claims is not None:
        expected = {item.claim_id: item.approved_safe_claim for item in value.claims}
        unknown = sorted(set(final_claims).difference(expected))
        missing = sorted(set(expected).difference(final_claims))
        if unknown or missing:
            details = []
            if unknown:
                details.append(f"unknown final claim IDs: {unknown}")
            if missing:
                details.append(f"missing final claim IDs: {missing}")
            raise IRValidationError("final claim set is not closed over approved claims", issues=details)
        mismatches = [claim_id for claim_id, text in expected.items() if final_claims[claim_id] != text]
        if mismatches:
            raise IRValidationError(f"final claim text must exactly equal approved_safe_claim for IDs: {mismatches}")
    # Revalidation from a JSON round-trip prevents callers from retaining a
    # mutable subclass or an unvalidated mapping at the locking boundary.
    return ApprovedClaimsIR.model_validate(value.model_dump(mode="json"))

__all__ = [
    "IRValidationError",
    "SCHEMA_NAMES",
    "approve_claims",
    "check_provenance_closure",
    "load_schema",
    "lock_approved_claims",
    "normalize_extractive_claim",
    "revalidate_evidence_input",
    "revalidate_role_input",
    "revalidate_source_map",
    "validate_ir",
    "validate_schema_document",
]
