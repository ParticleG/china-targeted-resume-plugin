from __future__ import annotations

import hashlib
from pathlib import Path

from china_targeted_resume.markdown_structure import parse_markdown
from china_targeted_resume.models import DisclosureLevel, FactState


FIXTURE_ROOT = Path(__file__).parent / "fixtures_nonstandard" / "nonstandard-repository"


def _value(value: object) -> object:
    return getattr(value, "value", value)


def _reasons(block: object) -> tuple[str, ...]:
    flags = getattr(block, "flags")
    for name in ("exclusion_reasons", "reasons", "excluded_reasons"):
        value = getattr(flags, name, None)
        if value:
            if isinstance(value, str):
                return (value,)
            return tuple(str(item) for item in value)
    return ()


def _blocks_containing(document: object, needle: str) -> list[object]:
    return [
        block
        for block in document.blocks
        if needle in document.exact_text(block.location)
    ]


def test_inherited_f6_p3_policy_excludes_descendant_with_exact_provenance() -> None:
    path = FIXTURE_ROOT / "projects" / "harbor-ledger.md"
    document = parse_markdown(path, source_root=FIXTURE_ROOT)

    descendants = _blocks_containing(document, "I documented the handoff checklist")
    assert descendants, "the narrower personal block must still be discoverable"
    descendant = descendants[0]
    assert descendant.heading_ancestry[:2] == (
        "Harbor Ledger",
        "F6/P3 Confidential Team Context",
    )
    assert _value(descendant.effective_fact_state) == FactState.F6
    assert _value(descendant.effective_disclosure) == DisclosureLevel.P3
    assert descendant.flags.excluded_from_evidence is True
    reasons = " ".join(_reasons(descendant)).casefold()
    assert "policy" in reasons or "f6" in reasons or "p3" in reasons

    quote = document.exact_text(descendant.location)
    assert "I documented the handoff checklist for one review queue." in quote
    source_bytes = path.read_bytes()
    assert document.source_hash == "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    byte_slice = source_bytes[descendant.location.start_byte : descendant.location.end_byte]
    assert byte_slice.decode("utf-8") == quote
    assert descendant.location.start_line <= descendant.location.end_line
    assert descendant.location.start_byte < descendant.location.end_byte


def test_fenced_headings_tables_bullets_and_blockquotes_never_enter_recall() -> None:
    path = FIXTURE_ROOT / "projects" / "harbor-ledger.md"
    document = parse_markdown(path, source_root=FIXTURE_ROOT)

    fake = _blocks_containing(document, "This fenced bullet looks like a claim")
    assert fake
    assert all(block.flags.inside_fence for block in fake)
    assert all(block.flags.excluded_from_evidence for block in fake)
    assert any("fence" in " ".join(_reasons(block)).casefold() for block in fake)

    fake_heading = _blocks_containing(document, "Fake project heading")
    assert fake_heading and all(block.flags.inside_fence for block in fake_heading)
    fake_table = _blocks_containing(document, "Fake signal")
    assert fake_table and all(block.flags.inside_fence for block in fake_table)

    quoted = _blocks_containing(document, "Quoted claim: the coordinator personally")
    assert quoted
    assert all(block.flags.inside_blockquote for block in quoted)
    assert all(block.flags.excluded_from_evidence for block in quoted)
    assert any("quot" in " ".join(_reasons(block)).casefold() for block in quoted)

    supported = _blocks_containing(document, "The coordinator documented a repeatable")
    assert supported
    assert any(not block.flags.inside_fence for block in supported)
    eligible_ids = {block.identity for block in document.eligible_blocks()}
    assert any(block.identity in eligible_ids for block in supported)


def test_profile_perturbations_preserve_heading_identity_and_exclusion_context() -> None:
    path = FIXTURE_ROOT / "profile-notes.md"
    document = parse_markdown(path, source_root=FIXTURE_ROOT)

    setext = [section for section in document.sections if section.heading == "Profile Notes"]
    assert setext and setext[0].level == 1

    duplicates = [section for section in document.sections if section.heading == "Duplicate heading"]
    assert len(duplicates) == 2
    assert duplicates[0].identity != duplicates[1].identity

    bilingual = [section for section in document.sections if "个人概览" in section.heading]
    assert bilingual

    html = _blocks_containing(document, "Example-only appendix")
    assert html
    assert all(block.flags.inside_html for block in html)
    assert all(block.flags.excluded_from_evidence for block in html)

    example = _blocks_containing(document, "the operator cut every delay")
    assert example
    assert all(block.flags.example for block in example)
    assert all(block.flags.excluded_from_evidence for block in example)

    instruction = _blocks_containing(document, "Do not claim that the operator")
    assert instruction
    assert all(block.flags.example or block.flags.template for block in instruction)
    assert all(block.flags.excluded_from_evidence for block in instruction)

    # Label bullets, definition-list-like fields, and prose fields are all retained
    # as source blocks without assuming a fixed profile vocabulary.
    assert _blocks_containing(document, "Display label: Example Operator")
    assert _blocks_containing(document, "workflow reliability and service coordination")
    assert _blocks_containing(document, "A paragraph profile field says")


def test_tables_prose_metrics_and_nonengineering_roles_are_recalled_without_column_assumptions() -> None:
    role_path = FIXTURE_ROOT / "role-brief.md"
    role_document = parse_markdown(role_path, source_root=FIXTURE_ROOT)
    role_headings = {section.heading.casefold() for section in role_document.sections}
    assert not any(
        heading.split() and any(term in heading.split() for term in ("required", "preferred"))
        for heading in role_headings
    )
    assert _blocks_containing(role_document, "facilitation")
    assert _blocks_containing(role_document, "concise handoff note")
    assert len([block for block in role_document.blocks if block.kind == "table"]) >= 2

    project_path = FIXTURE_ROOT / "projects" / "harbor-ledger.md"
    project_document = parse_markdown(project_path, source_root=FIXTURE_ROOT)
    team = _blocks_containing(project_document, "The team processed 180 synthetic requests")
    personal = _blocks_containing(project_document, "My checklist covered the intake")
    prose_metric = _blocks_containing(project_document, "review completion improved from roughly")
    role = _blocks_containing(project_document, "non-engineering operations role")
    assert team and personal and prose_metric and role
    assert team[0].location.end_line < personal[0].location.start_line
    assert project_document.exact_text(prose_metric[0].location).startswith("Outcome notes are prose-only")
    assert project_document.exact_text(role[0].location).startswith("In a non-engineering operations role")


def test_prose_only_project_is_recalled_as_paragraphs() -> None:
    path = FIXTURE_ROOT / "projects" / "prose-only.md"
    document = parse_markdown(path, source_root=FIXTURE_ROOT)
    summary = _blocks_containing(document, "This prose-only project used")
    outcome = _blocks_containing(document, "closed 8 of 10 requests")
    assert summary and outcome
    assert all(block.kind == "paragraph" for block in summary + outcome)
    assert not any(block.kind == "table" for block in document.blocks)
    assert not any(block.kind == "list_item" for block in document.blocks)
