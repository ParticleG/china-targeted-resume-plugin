from __future__ import annotations

from contextlib import contextmanager
import json
from io import StringIO

import pytest

from china_targeted_resume.cli import (
    _dispatch,
    _parser,
    _request_from_generate,
    _request_from_guided,
    main,
)
from china_targeted_resume.models import (
    CompanyRef,
    Contact,
    RenderPolicy,
    ResumeDocument,
    ResumeTarget,
    ResumeVariant,
    RoleRef,
    RunRequest,
    TargetBasis,
)

def _remove_intentional_traversal_probe(root) -> None:
    path = root / "personal-data/meta/public-links.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if "outside-secret.md" not in line) + "\n", encoding="utf-8")


EXPECTED_COMMANDS = {
    "list-companies",
    "list-roles",
    "generate",
    "guided-generate",
    "analyze-role",
    "refresh-role",
    "refresh-match",
    "export-roadmap-handoff",
    "write-growth-roadmap",
    "build-evidence-map",
    "validate-content",
    "render",
    "inspect-pdf",
}


def test_help_exposes_complete_command_contract(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert EXPECTED_COMMANDS <= set(help_text.replace("{", "").replace("}", "").replace(",", " ").split())


def test_list_companies_and_roles_emit_machine_readable_json(synthetic_db_copy, capsys) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    assert main(["list-companies", "--source", str(synthetic_db_copy)]) == 0
    companies = json.loads(capsys.readouterr().out)
    assert companies["operation"] == "list-companies"
    assert companies["count"] == len(companies["companies"]) >= 2
    assert {item["company_id"] for item in companies["companies"]} >= {"acme-cloudworks", "clockwork-capybara-robotics"}

    assert main(
        [
            "list-roles",
            "--source",
            str(synthetic_db_copy),
            "--company",
            "acme-cloudworks",
        ]
    ) == 0
    roles = json.loads(capsys.readouterr().out)
    assert roles["operation"] == "list-roles"
    assert roles["count"] == len(roles["roles"]) >= 1
    assert "acme-cloudworks-platform-engineer" in {item["role_id"] for item in roles["roles"]}

def test_conventional_company_research_path_resolves_to_source_root(
    synthetic_db_copy,
    capsys,
) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)

    assert main(
        [
            "list-companies",
            "--source",
            str(synthetic_db_copy / "company-research"),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] >= 2


def test_cli_rejects_traversal_fixture_without_reading_outside(synthetic_career_db, capsys) -> None:
    status = main(["list-companies", "--source", str(synthetic_career_db)])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert "traversal" in json.loads(captured.err)["error"].casefold()


def test_cli_rejects_output_inside_read_only_source_before_creating_a_run(synthetic_db_copy, capsys) -> None:
    nested_output = synthetic_db_copy / "outputs"
    status = main(
        [
            "generate",
            "--source",
            str(synthetic_db_copy),
            "--company",
            "acme-cloudworks",
            "--role",
            "acme-cloudworks-platform-engineer",
            "--jd-text",
            "Current complete role requires Python automation.",
            "--output",
            str(nested_output),
        ]
    )

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert status == 2
    assert captured.out == ""
    assert "outside the source root" in error["error"]
    assert not nested_output.exists()



def test_generate_cli_constructs_extended_profile_request(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "generate",
            "--source",
            str(tmp_path / "source"),
            "--output",
            str(tmp_path / "output"),
            "--include-extended-profile",
        ]
    )

    request = _request_from_generate(args)

    assert request.include_extended_profile is True
    assert request.template == "adaptive"
    assert "target_pages" not in RunRequest.model_fields


def test_generate_cli_loads_application_constraints_file(tmp_path) -> None:
    constraints_path = tmp_path / "constraints.json"
    constraints_path.write_text(
        json.dumps(
            [
                {
                    "constraint_id": "CON-LOCATION",
                    "kind": "location",
                    "hard_gate": True,
                    "status": "unsatisfied",
                    "candidate_value": "Remote only",
                    "required_value": "Three office days",
                }
            ]
        ),
        encoding="utf-8",
    )
    args = _parser().parse_args(
        [
            "generate",
            "--source",
            str(tmp_path / "source"),
            "--jd-text",
            "Current role text.",
            "--application-constraints-file",
            str(constraints_path),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    request = _request_from_generate(args)

    [constraint] = request.application_constraints
    assert constraint["constraint_id"] == "CON-LOCATION"
    assert constraint["status"] == "unsatisfied"

def test_generate_cli_loads_experience_duration_diagnostics_file(
    tmp_path,
) -> None:
    diagnostics_path = tmp_path / "duration-diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            [
                {
                    "requirement_id": "REQ-PYTHON-YEARS",
                    "diagnostic": {
                        "candidate_scope": "professional Python development",
                        "required_scope": "professional Python development",
                        "unit": "years",
                        "candidate_years": 4,
                        "required_min_years": 5,
                        "evidence_refs": ["ev-python-duration"],
                        "checked_at": "2026-08-30T00:00:00Z",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    args = _parser().parse_args(
        [
            "generate",
            "--source",
            str(tmp_path / "source"),
            "--experience-duration-diagnostics-file",
            str(diagnostics_path),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    request = _request_from_generate(args)

    [binding] = request.experience_duration_diagnostics
    assert binding.requirement_id == "REQ-PYTHON-YEARS"
    assert binding.diagnostic.evidence_refs == ["ev-python-duration"]

def test_guided_generate_selects_company_and_role_on_private_console(
    tmp_path,
) -> None:
    class DiscoveryPipeline:
        def list_companies(self, source):
            return [
                CompanyRef(company_id="company-a", display_name="Company A"),
                CompanyRef(company_id="company-b", display_name="Company B"),
            ]

        def list_roles(self, source, company):
            assert company == "company-b"
            return [
                RoleRef(
                    role_id="role-b1",
                    title="Platform Engineer",
                    company_id="company-b",
                ),
                RoleRef(
                    role_id="role-b2",
                    title="Infrastructure Engineer",
                    company_id="company-b",
                ),
            ]

    args = _parser().parse_args(
        [
            "guided-generate",
            "--source",
            str(tmp_path / "source" / "company-research"),
            "--output",
            str(tmp_path / "output"),
        ]
    )
    prompts = StringIO()

    request = _request_from_guided(
        args,
        DiscoveryPipeline(),
        input_stream=StringIO("2\n1\n"),
        prompt_stream=prompts,
    )

    assert request.company_ref == "company-b"
    assert request.role_ref == "role-b1"
    assert request.template == "adaptive"
    assert "Available company choices" in prompts.getvalue()
    assert "Available role choices" in prompts.getvalue()


@pytest.mark.parametrize(
    ("selection", "expected_error"),
    [
        ("", "company selection is required"),
        ("not-a-company\n", "invalid company selection"),
    ],
)
def test_guided_generate_selection_errors_keep_stderr_single_json(
    synthetic_db_copy,
    tmp_path,
    monkeypatch,
    capsys,
    selection,
    expected_error,
) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    prompts = StringIO()

    @contextmanager
    def fake_console():
        yield StringIO(selection), prompts

    monkeypatch.setattr(
        "china_targeted_resume.cli._guided_console",
        fake_console,
    )

    status = main(
        [
            "guided-generate",
            "--source",
            str(synthetic_db_copy / "company-research"),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    error = json.loads(captured.err)
    assert expected_error in error["error"]
    assert "Available company choices" in prompts.getvalue()


def test_generate_help_has_no_legacy_pages_option(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _parser().parse_args(["generate", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--include-extended-profile" in help_text
    assert "--pages" not in help_text


def test_inspect_pdf_dispatches_max_pages(tmp_path) -> None:
    class RecordingPipeline:
        def __init__(self) -> None:
            self.call = None

        def inspect_pdf(self, pdf, **kwargs):
            self.call = (pdf, kwargs)
            return {"ok": True}

    args = _parser().parse_args(
        [
            "inspect-pdf",
            "--pdf",
            str(tmp_path / "resume.pdf"),
            "--max-pages",
            "3",
            "--expected-name",
            "Candidate",
        ]
    )
    pipeline = RecordingPipeline()

    assert _dispatch(args, pipeline) == {"ok": True}
    assert pipeline.call == (
        tmp_path / "resume.pdf",
        {"max_pages": 3, "expected_name": "Candidate"},
    )


def test_resume_variant_and_page_range_model_contract() -> None:
    assert {variant.value for variant in ResumeVariant} == {
        "recruiter-one-page",
        "technical-two-page",
        "extended-three-page",
    }
    document = ResumeDocument(
        target=ResumeTarget(target_basis=TargetBasis.INSUFFICIENT_TARGET),
        contact=Contact(name="Candidate"),
        headline="Engineer",
    )
    assert document.variant == ResumeVariant.TECHNICAL_TWO_PAGE
    assert RenderPolicy().minimum_pages == 1

    with pytest.raises(ValueError, match="minimum_pages must not exceed target_pages"):
        RenderPolicy(minimum_pages=3, target_pages=2)