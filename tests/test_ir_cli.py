from __future__ import annotations

import pytest

from china_targeted_resume.cli import _parser
from china_targeted_resume.pipeline import Pipeline, PipelineError


def test_generate_from_ir_rejects_missing_verified_evidence_bundle(tmp_path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    with pytest.raises(PipelineError, match="source_map and normalized evidence"):
        Pipeline().generate_from_ir(
            {"approved_claims": {"schema_version": 1, "claims": []}},
            source=source,
            output_root=output,
        )
    assert not output.exists()


def test_generate_from_ir_requires_deterministic_approval_inputs(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = {
        "source_map": {"schema_version": 1, "documents": [], "sections": [], "blocks": [], "proposals": []},
        "evidence_input": {"schema_version": 1, "input_id": "e", "domain": "evidence", "candidates": []},
        "approved_claims": {"schema_version": 1, "claims": []},
    }
    with pytest.raises(PipelineError, match="approval inputs"):
        Pipeline().generate_from_ir(payload, source=source, output_root=source.parent / "output")


def test_role_and_evidence_ir_commands_require_source_flag() -> None:
    for command in ("validate-role-input", "validate-evidence-input", "approve-claims"):
        with pytest.raises(SystemExit):
            _parser().parse_args([command, "--input", "private.json"])


def test_inspect_pdf_accepts_authoritative_document_path() -> None:
    args = _parser().parse_args(["inspect-pdf", "--pdf", "resume.pdf", "--document", "resume-document.json"])
    assert str(args.document).endswith("resume-document.json")
