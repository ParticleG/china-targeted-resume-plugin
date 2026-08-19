from __future__ import annotations

import json

import pytest

from china_targeted_resume.cli import main

def _remove_intentional_traversal_probe(root) -> None:
    path = root / "personal-data/meta/public-links.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if "outside-secret.md" not in line) + "\n", encoding="utf-8")


EXPECTED_COMMANDS = {
    "list-companies",
    "list-roles",
    "generate",
    "analyze-role",
    "refresh-role",
    "refresh-match",
    "export-roadmap-handoff",
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
