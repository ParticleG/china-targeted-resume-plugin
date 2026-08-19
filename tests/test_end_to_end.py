from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

import pymupdf
import pytest

from china_targeted_resume.adapters.markdown_career_v1 import (
    MarkdownCareerV1Adapter,
)
from china_targeted_resume.cli import main
from china_targeted_resume.dossier import DOSSIER_FILES
from china_targeted_resume.models import CompanyRef, RoleRef, RunRequest
from china_targeted_resume.pipeline import Pipeline, _tier_b_requirements


BASE_OUTPUT_FILES = {
    "run.json",
    "source-manifest.json",
    "target-context.json",
    "jd-snapshot.md",
    "requirements.json",
    "competencies.json",
    "application-constraints.json",
    "evidence-map.json",
    "gaps.json",
    "application-recommendation.json",
    "provenance.json",
    "confirmation-questions.md",
    "audit-report.md",
    "resume-document.json",
    "resume-targeted.md",
    "resume-ats.txt",
    "resume.html",
    "resume.pdf",
    "resume-preview.png",
    "interview-questions.md",
}
FORBIDDEN_SECRET = "TOKEN-FICTIONAL-DO-NOT-USE-7QX"
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _remove_intentional_traversal_probe(root: Path) -> None:
    path = root / "personal-data/meta/public-links.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if "outside-secret.md" not in line) + "\n", encoding="utf-8")


def _source_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_body_keys(value: object) -> None:
    if isinstance(value, dict):
        assert not ({"body", "snippet", "raw_body", "source_body"} & set(value))
        for item in value.values():
            _assert_no_body_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_body_keys(item)


def _assert_full_contract(run_dir: Path, *, handoff: bool) -> None:
    assert run_dir.is_dir()
    assert BASE_OUTPUT_FILES <= {path.name for path in run_dir.iterdir()}
    assert set(DOSSIER_FILES) == {path.name for path in (run_dir / "role-dossier").iterdir()}
    assert (run_dir / "roadmap-handoff.json").exists() is handoff

    for path in run_dir.rglob("*"):
        if path.is_dir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o700, path
        elif path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
            assert not path.name.startswith("."), path
            assert path.stat().st_size > 0 or path.name == "jd-snapshot.md"
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700

    for filename in (
        "run.json",
        "source-manifest.json",
        "target-context.json",
        "requirements.json",
        "competencies.json",
        "application-constraints.json",
        "evidence-map.json",
        "gaps.json",
        "application-recommendation.json",
        "provenance.json",
        "resume-document.json",
        "role-dossier-ir.json",
    ):
        _json(run_dir / filename)
    _assert_no_body_keys(_json(run_dir / "source-manifest.json"))
    persisted_dossier = _json(run_dir / "role-dossier-ir.json")
    _assert_no_body_keys(persisted_dossier)
    assert persisted_dossier["evidence_candidates"] == []
    assert persisted_dossier["evidence_records"] == []

    forbidden_storage_names = {"index", "indexes", "cache", "caches", "temp", "tmp", "logs", "trace", "traces"}
    assert not {
        path.name.casefold()
        for path in run_dir.rglob("*")
        if path.name.casefold() in forbidden_storage_names
        or path.suffix.casefold() in {".cache", ".log", ".trace", ".tmp", ".temp"}
    }
    persisted = b"\n".join(path.read_bytes() for path in run_dir.rglob("*") if path.is_file())
    assert FORBIDDEN_SECRET.encode() not in persisted
    assert b"-----BEGIN PRIVATE KEY-----" not in persisted
    assert b"password=" not in persisted.lower()
    text_artifacts = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".json", ".md", ".txt", ".html"}
    )
    assert not re.search(r"(?<![A-Za-z0-9])(?:F6|P3)(?![A-Za-z0-9])", text_artifacts)
    assert "Operated a 10,000-node fleet" not in text_artifacts
    assert "Reduced all incidents by 90%" not in text_artifacts


def _expected_pdf_sequence(document: dict[str, object]) -> list[str]:
    labels = {
        "summary": "Summary",
        "skills": "Skills",
        "experience": "Experience",
        "projects": "Projects",
        "education": "Education",
        "honors": "Honors",
    }
    return [label for section, label in labels.items() if document.get(section)] + (["Links"] if document["contact"].get("links") else [])


def _assert_real_pdf(run_dir: Path, *, max_pages: int) -> None:
    pdf_path = run_dir / "resume.pdf"
    preview_path = run_dir / "resume-preview.png"
    resume = _json(run_dir / "resume-document.json")
    visible = (run_dir / "resume-ats.txt").read_text(encoding="utf-8")

    with pymupdf.open(pdf_path) as pdf:
        assert pdf.is_pdf and not pdf.is_encrypted
        assert 1 <= pdf.page_count <= max_pages
        extracted = "\n".join(page.get_text("text", sort=True) for page in pdf)
        assert extracted.strip()
        assert "�" not in extracted
        assert set(CJK.findall(visible)) <= set(CJK.findall(extracted))
        if resume["contact"]["name"]:
            assert resume["contact"]["name"] in extracted
        headings = _expected_pdf_sequence(resume)
        positions = [extracted.index(heading) for heading in headings]
        assert positions == sorted(positions)

        expected_links = {str(item["url"]) for item in resume["contact"].get("links", [])}
        if resume["contact"].get("email"):
            expected_links.add("mailto:" + resume["contact"]["email"])
        actual_links: set[str] = set()
        safe_font_programs = 0
        sizes: list[float] = []
        for page in pdf:
            assert page.rect.width == pytest.approx(595.28, abs=2.0)
            assert page.rect.height == pytest.approx(841.89, abs=2.0)
            blocks = page.get_text("blocks", sort=True)
            assert blocks
            assert all(
                -0.5 <= block[0] <= block[2] <= page.rect.width + 0.5
                and -0.5 <= block[1] <= block[3] <= page.rect.height + 0.5
                for block in blocks
            )
            actual_links.update(link["uri"] for link in page.get_links() if link.get("uri"))
            for font in page.get_fonts(full=True):
                if str(font[2]).casefold() == "type3":
                    safe_font_programs += 1
                elif font[0] > 0 and pdf.extract_font(font[0])[3]:
                    safe_font_programs += 1
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    sizes.extend(float(span["size"]) for span in line.get("spans", []) if span.get("text", "").strip())
        assert expected_links <= actual_links
        assert safe_font_programs > 0
        assert sizes and min(sizes) + 0.15 >= 10.0

    pixmap = pymupdf.Pixmap(str(preview_path))
    assert 1200 <= pixmap.width <= 1300
    assert 1700 <= pixmap.height <= 1800
    assert pixmap.n in (3, 4)


def _run_cli(argv: list[str], capsys) -> tuple[Path, dict[str, object]]:
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    run_dir = Path(payload["run_dir"])
    assert run_dir == run_dir.resolve()
    assert payload["operation"] == "generate"
    assert set(map(Path, payload["artifacts"])) <= set(run_dir.rglob("*"))
    return run_dir, payload


def test_tier_a_complete_jd_full_run_direct_mapping_pdf_and_source_isolation(synthetic_db_copy, tmp_path, capsys) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    source_before = _source_snapshot(synthetic_db_copy)
    output_root = tmp_path / "tier-a-output"
    jd = """# Current complete job description / 当前完整职位描述
## Source metadata
- Published: 2026-07-10
- Accessed: 2026-07-12
- URL: https://jobs.example.invalid/platform

## Requirements
- Must operate Linux services and lead incident response.
- Required Python automation and API integration.
- Required container delivery with Docker.
"""
    run_dir, payload = _run_cli(
        [
            "generate", "--source", str(synthetic_db_copy),
            "--company", "acme-cloudworks",
            "--role", "acme-cloudworks-platform-engineer",
            "--jd-text", jd, "--pages", "2", "--template", "ats-simple",
            "--output", str(output_root),
        ],
        capsys,
    )

    _assert_full_contract(run_dir, handoff=False)
    target = _json(run_dir / "target-context.json")
    mappings = _json(run_dir / "evidence-map.json")
    assert target["target_basis"] == "exact-current-jd"
    assert target["jd_completeness"] == "complete"
    assert target["jd_source_date"] == "2026-07-10"
    assert target["jd_checked_at"] == "2026-07-12T00:00:00Z"
    assert target["source_refs"] == ["https://jobs.example.invalid/platform"]
    assert run_dir.name.startswith("acme-cloudworks--")
    assert target["explicit_requirement_coverage"] is not None
    assert target["coverage_calculation"]["total_explicit_requirements"] == 3
    assert mappings and all(mapping["match_state"] == "已有直接证据" for mapping in mappings)
    assert all(mapping["evidence_ids"] for mapping in mappings)
    assert [mapping["resume_priority"] for mapping in mappings] == sorted(
        (mapping["resume_priority"] for mapping in mappings), reverse=True
    )
    assert payload["summary"]["target_basis"] == "exact-current-jd"
    _assert_real_pdf(run_dir, max_pages=2)
    assert _source_snapshot(synthetic_db_copy) == source_before
    assert not run_dir.is_relative_to(synthetic_db_copy)


def test_tier_b_partial_role_full_run_null_coverage_limitations_and_explicit_handoff(synthetic_db_copy, tmp_path) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    source_before = _source_snapshot(synthetic_db_copy)
    output_root = tmp_path / "tier-b-output"
    company = CompanyRef(
        company_id="clockwork-capybara-robotics",
        display_name="Clockwork Capybara Robotics",
        source_refs=["company-research/clockwork-capybara-robotics/README.md"],
    )
    role = RoleRef(
        role_id="clockwork-capybara-robotics-platform-engineer",
        title="Robotics Platform Engineer",
        company_id=company.company_id,
        source_refs=["company-research/clockwork-capybara-robotics/roles-and-hiring.md"],
    )
    result = Pipeline().generate(
        RunRequest(
            source_root=synthetic_db_copy,
            company_ref=company,
            role_ref=role,
            target_pages=2,
            template="human-readable",
            export_roadmap_handoff=True,
            output_root=output_root,
        )
    )
    assert result.run_dir is not None
    run_dir = result.run_dir
    payload = result.model_dump(mode="json")

    _assert_full_contract(run_dir, handoff=True)
    target = _json(run_dir / "target-context.json")
    assert target["target_basis"] == "exact-role-partial-evidence"
    assert target["jd_completeness"] in {"partial", "stale"}
    assert target["explicit_requirement_coverage"] is None
    assert target["coverage_calculation"] is None
    assert target["limitations"]
    assert target["staleness_risk"] in {"high", "unknown"}
    assert payload["summary"]["limitations"] == target["limitations"]
    audit_text = (run_dir / "audit-report.md").read_text(encoding="utf-8")
    assert "Target basis: `exact-role-partial-evidence`" in audit_text
    assert all(f"Limitation: {limitation}" in audit_text for limitation in target["limitations"])
    requirements = _json(run_dir / "requirements.json")
    assert all(not item["hard_gate"] for item in requirements if item["origin"] == "inferred")
    assert (run_dir / "roadmap-handoff.json").is_file()
    _assert_real_pdf(run_dir, max_pages=2)
    assert _source_snapshot(synthetic_db_copy) == source_before
    assert not run_dir.is_relative_to(synthetic_db_copy)


def test_tier_b_inference_uses_only_the_exact_role_signal(
    synthetic_db_copy,
) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    hiring = (
        synthetic_db_copy
        / "company-research/clockwork-capybara-robotics/roles-and-hiring.md"
    )
    hiring.write_text(
        """# Roles and Hiring

## Current openings

Salary ranges are page snapshots and are not final offers.

## Role families and evidence

- AI: Required distributed training and model serving.
- C++: Linux, C/C++, Python, Shell, gRPC, operating systems, networking, and ROS 2; video delivery, Docker, and API design preferred.
- Sales: Customer acquisition and frequent travel are preferred.
""",
        encoding="utf-8",
    )
    adapter = MarkdownCareerV1Adapter(synthetic_db_copy)
    company = CompanyRef(
        company_id="clockwork-capybara-robotics",
        display_name="Clockwork Capybara Robotics",
    )
    role = RoleRef(
        role_id="clockwork-capybara-robotics-cpp-engineer",
        title="C++ 开发工程师（J10034）",
        company_id=company.company_id,
        source_refs=[
            "company-research/clockwork-capybara-robotics/roles-and-hiring.md:L1-L13"
        ],
    )

    requirements = _tier_b_requirements(adapter, company, role)

    texts = {item.text for item in requirements}
    assert texts == {
        "Linux",
        "C/C++",
        "Python",
        "Shell",
        "gRPC",
        "operating systems",
        "networking",
        "ROS 2",
        "video delivery preferred",
        "Docker preferred",
        "API design preferred",
    }
    assert all("distributed training" not in text for text in texts)
    assert all("Customer acquisition" not in text for text in texts)
    assert all(item.origin == "inferred" for item in requirements)
    assert all(item.necessity == "context" for item in requirements)
    assert all(not item.hard_gate for item in requirements)


def test_installable_package_tree_contains_no_fixture_or_real_career_data() -> None:
    project_root = Path(__file__).resolve().parents[1]
    package_root = project_root / "src/china_targeted_resume"
    packaged_paths = {path.relative_to(package_root).as_posix() for path in package_root.rglob("*")}
    packaged_bytes = b"\n".join(path.read_bytes() for path in package_root.rglob("*") if path.is_file())

    assert not any("personal-data/" in path or "company-research/" in path for path in packaged_paths)
    assert FORBIDDEN_SECRET.encode() not in packaged_bytes
    assert b"outside-secret.md" not in packaged_bytes


def test_curated_skill_archive_includes_readme_and_excludes_workspaces(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    archive_path = tmp_path / "china-targeted-resume.skill"
    subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/package_skill.py"),
            str(project_root),
            str(archive_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    prefix = f"{project_root.name}/"
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        readme = archive.read(prefix + "README.md").decode("utf-8")

    assert prefix + "SKILL.md" in names
    assert prefix + "README.md" in names
    assert "## Tutorial: generate from a complete current JD" in readme
    assert "uv run china-targeted-resume generate" in readme
    assert not any(
        blocked in name
        for name in names
        for blocked in ("/tests/", "/evals/", "-workspace/")
    )
