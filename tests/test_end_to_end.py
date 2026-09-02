from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
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


DEFAULT_VARIANT_BASES = {
    "resume-recruiter-1p",
    "resume-technical-2p",
}
EXTENDED_VARIANT_BASE = "technical-profile-3p"
VARIANT_SUFFIXES = {
    ".document.json",
    ".provenance.json",
    ".validation.json",
    ".audit.md",
    ".md",
    ".txt",
    ".html",
    ".pdf",
    ".preview.png",
}
BASE_OUTPUT_FILES = {
    "run.json",
    "source-manifest.json",
    "target-context.json",
    "jd-snapshot.md",
    "requirements.json",
    "competencies.json",
    "application-constraints.json",
    "evidence-map.json",
    "experience-duration-facts.json",
    "gaps.json",
    "application-recommendation.json",
    "confirmation-questions.md",
    "interview-questions.md",
    "role-dossier-ir.json",
    "resume-variants.json",
}


def _variant_files(base_name: str) -> set[str]:
    return {base_name + suffix for suffix in VARIANT_SUFFIXES}
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


def _assert_full_contract(
    run_dir: Path,
    *,
    handoff: bool,
    extended: bool = False,
) -> None:
    assert run_dir.is_dir()
    variant_bases = set(DEFAULT_VARIANT_BASES)
    if extended:
        variant_bases.add(EXTENDED_VARIANT_BASE)
    expected = BASE_OUTPUT_FILES | {
        filename
        for base_name in variant_bases
        for filename in _variant_files(base_name)
    }
    names = {path.name for path in run_dir.iterdir()}
    assert expected <= names
    assert (
        EXTENDED_VARIANT_BASE + ".document.json" in names
    ) is extended
    assert set(DOSSIER_FILES) == {
        path.name for path in (run_dir / "role-dossier").iterdir()
    }
    assert (run_dir / "roadmap-handoff.json").exists() is handoff

    for path in run_dir.rglob("*"):
        if path.is_dir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o700, path
        elif path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
            assert not path.name.startswith("."), path
            assert path.stat().st_size > 0 or path.name == "jd-snapshot.md"
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700

    json_files = [
        "run.json",
        "source-manifest.json",
        "target-context.json",
        "requirements.json",
        "competencies.json",
        "application-constraints.json",
        "evidence-map.json",
        "experience-duration-facts.json",
        "gaps.json",
        "application-recommendation.json",
        "role-dossier-ir.json",
        "resume-variants.json",
        *(
            base_name + suffix
            for base_name in variant_bases
            for suffix in (
                ".document.json",
                ".provenance.json",
                ".validation.json",
            )
        ),
    ]
    for filename in json_files:
        _json(run_dir / filename)
    manifest = _json(run_dir / "resume-variants.json")
    assert all(
        item["template"] in {"ats-simple", "human-readable"}
        for item in manifest["variants"]
    )
    gap_analysis = (
        run_dir / "role-dossier" / "gap-analysis.md"
    ).read_text(encoding="utf-8")
    assert "## Application recommendation" in gap_analysis
    assert "- Hard-constraint readiness:" in gap_analysis
    requirements = _json(run_dir / "requirements.json")
    mappings = _json(run_dir / "evidence-map.json")
    assert all(
        not item["requirement_id"].startswith("resume-discovery-")
        and item.get("category") != "resume-discovery"
        for item in requirements
    )
    assert all(
        not mapping["requirement_id"].startswith("resume-discovery-")
        for mapping in mappings
    )
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


def _assert_real_pdf(
    run_dir: Path,
    base_name: str,
    *,
    max_pages: int,
    min_pages: int = 1,
) -> None:
    pdf_path = run_dir / f"{base_name}.pdf"
    preview_path = run_dir / f"{base_name}.preview.png"
    resume = _json(run_dir / f"{base_name}.document.json")
    visible = (run_dir / f"{base_name}.txt").read_text(encoding="utf-8")

    with pymupdf.open(pdf_path) as pdf:
        assert pdf.is_pdf and not pdf.is_encrypted
        assert min_pages <= pdf.page_count <= max_pages
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
    constraints_path = tmp_path / "tier-a-constraints.json"
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
            "--jd-text", jd, "--template", "ats-simple",
            "--application-constraints-file", str(constraints_path),
            "--language", "en-US",
            "--output", str(output_root),
        ],
        capsys,
    )

    _assert_full_contract(run_dir, handoff=False)
    target = _json(run_dir / "target-context.json")
    mappings = _json(run_dir / "evidence-map.json")
    constraints = _json(run_dir / "application-constraints.json")
    recommendation = _json(run_dir / "application-recommendation.json")
    assert target["target_basis"] == "exact-current-jd"
    assert target["jd_completeness"] == "complete"
    assert target["jd_source_date"] == "2026-07-10"
    assert target["jd_checked_at"] == "2026-07-12T00:00:00Z"
    assert target["source_refs"] == ["https://jobs.example.invalid/platform"]
    assert run_dir.name.startswith("acme-cloudworks--")
    assert target["explicit_requirement_coverage"] is not None
    assert target["coverage_calculation"]["total_explicit_requirements"] == 3
    assert mappings and all(mapping["match_state"] == "已有直接证据" for mapping in mappings)
    assert constraints[0]["status"] == "unsatisfied"
    assert recommendation["decision"] == "deprioritize"
    assert all(mapping["evidence_ids"] for mapping in mappings)
    assert [mapping["resume_priority"] for mapping in mappings] == sorted(
        (mapping["resume_priority"] for mapping in mappings), reverse=True
    )
    assert payload["summary"]["target_basis"] == "exact-current-jd"
    assert set(payload["summary"]["variants"]) == {
        "recruiter-one-page",
        "technical-two-page",
    }
    _assert_real_pdf(
        run_dir,
        "resume-recruiter-1p",
        max_pages=1,
    )
    _assert_real_pdf(
        run_dir,
        "resume-technical-2p",
        max_pages=2,
    )
    assert _source_snapshot(synthetic_db_copy) == source_before
    assert not run_dir.is_relative_to(synthetic_db_copy)



def test_incomplete_jd_cli_keeps_tier_b_and_parses_explicit_requirements(
    synthetic_db_copy,
    tmp_path,
    capsys,
) -> None:
    _remove_intentional_traversal_probe(synthetic_db_copy)
    jd = """# Partial job description excerpt
## Requirements
- Must operate Kubernetes services.
- Required Python automation and API integration.
- Prometheus experience is preferred.
"""
    run_dir, _ = _run_cli(
        [
            "generate",
            "--source",
            str(synthetic_db_copy),
            "--company",
            "acme-cloudworks",
            "--role",
            "acme-cloudworks-platform-engineer",
            "--jd-text",
            jd,
            "--jd-incomplete",
            "--language",
            "en-US",
            "--output",
            str(tmp_path / "tier-b-incomplete-jd-output"),
        ],
        capsys,
    )

    target = _json(run_dir / "target-context.json")
    requirements = _json(run_dir / "requirements.json")

    assert target["target_basis"] == "exact-role-partial-evidence"
    assert target["jd_completeness"] == "partial"
    assert target["explicit_requirement_coverage"] is None
    assert target["coverage_calculation"] is None
    assert len(requirements) == 3
    assert all(item["origin"] == "explicit" for item in requirements)
    assert any("Kubernetes" in item["text"] for item in requirements)

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
            language="en-US",
            template="human-readable",
            export_roadmap_handoff=True,
            include_extended_profile=True,
            output_root=output_root,
        )
    )
    assert result.run_dir is not None
    run_dir = result.run_dir
    payload = result.model_dump(mode="json")

    _assert_full_contract(run_dir, handoff=True, extended=True)
    target = _json(run_dir / "target-context.json")
    assert target["target_basis"] == "exact-role-partial-evidence"
    assert target["jd_completeness"] in {"partial", "stale"}
    assert target["explicit_requirement_coverage"] is None
    assert target["coverage_calculation"] is None
    assert target["limitations"]
    assert target["staleness_risk"] in {"high", "unknown"}
    assert payload["summary"]["limitations"] == target["limitations"]
    audit_text = (
        run_dir / "resume-technical-2p.audit.md"
    ).read_text(encoding="utf-8")
    assert "Target basis: `exact-role-partial-evidence`" in audit_text
    assert all(f"Limitation: {limitation}" in audit_text for limitation in target["limitations"])
    requirements = _json(run_dir / "requirements.json")
    assert all(not item["hard_gate"] for item in requirements if item["origin"] == "inferred")
    assert (run_dir / "roadmap-handoff.json").is_file()
    _assert_real_pdf(
        run_dir,
        "resume-recruiter-1p",
        max_pages=1,
    )
    _assert_real_pdf(
        run_dir,
        "resume-technical-2p",
        max_pages=2,
    )
    _assert_real_pdf(
        run_dir,
        "technical-profile-3p",
        max_pages=3,
    )
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


def test_curated_skill_archive_uses_canonical_plugin_layout_without_links(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    canonical_root = project_root / "skills/china-targeted-resume"
    canonical_skill = canonical_root / "SKILL.md"
    archive_path = tmp_path / "china-targeted-resume.skill"

    assert canonical_skill.is_file()
    assert (canonical_root / "references/source-adapter.md").is_file()
    assert not (project_root / "SKILL.md").exists()
    assert not (project_root / "references").exists()
    assert not any(path.is_symlink() for path in canonical_root.rglob("*"))

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
        infos = archive.infolist()
        names = {item.filename for item in infos}
        readme = archive.read(prefix + "README.md").decode("utf-8")
        archived_skill = archive.read(prefix + "SKILL.md")

    assert archived_skill == canonical_skill.read_bytes()
    assert sum(name.endswith("/SKILL.md") for name in names) == 1
    assert prefix + "README.md" in names
    assert prefix + "references/source-adapter.md" in names
    assert prefix + "schemas/source-map.schema.json" in names
    assert prefix + "schemas/approved-claims.schema.json" in names
    assert "## Tutorial: generate from a complete current JD" in readme
    assert "uv run china-targeted-resume generate" in readme
    assert all(not stat.S_ISLNK(item.external_attr >> 16) for item in infos)
    assert not any(
        blocked in name
        for name in names
        for blocked in (
            "/tests/",
            "/evals/",
            "-workspace/",
            "/.agents/",
            "/.claude/",
            "/skills/",
        )
    )


def test_clean_wheel_install_and_sdist_run_ir_commands_with_packaged_schemas(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    distribution_directory = tmp_path / "distributions"
    distribution_directory.mkdir()
    subprocess.run(
        ["uv", "build", "--out-dir", str(distribution_directory)],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(distribution_directory.glob("*.whl"))
    sdists = list(distribution_directory.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    schema_members = (
        "approved-claims.schema.json",
        "normalized-evidence-input.schema.json",
        "normalized-role-input.schema.json",
        "review-decision.schema.json",
        "source-map.schema.json",
    )
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_names = set(wheel.namelist())
    assert all(
        f"china_targeted_resume/schemas/{name}" in wheel_names
        for name in schema_members
    )
    assert not any(name.endswith("/SKILL.md") for name in wheel_names)

    with tarfile.open(sdists[0], "r:gz") as sdist:
        sdist_names = set(sdist.getnames())
    canonical_skill_suffix = "/skills/china-targeted-resume/SKILL.md"
    assert sum(name.endswith(canonical_skill_suffix) for name in sdist_names) == 1
    assert any(
        name.endswith(
            "/skills/china-targeted-resume/references/source-adapter.md"
        )
        for name in sdist_names
    )
    assert not any(
        name.endswith("/SKILL.md")
        and not name.endswith(canonical_skill_suffix)
        for name in sdist_names
    )

    site_packages = tmp_path / "site-packages"
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(site_packages),
            "--no-deps",
            str(wheels[0]),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(site_packages)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, china_targeted_resume; "
                "from china_targeted_resume.validation import SCHEMA_NAMES, load_schema; "
                "print(json.dumps({'package_file': china_targeted_resume.__file__, "
                "'schema_names': [name for name in SCHEMA_NAMES if load_schema(name)]}))"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    probe_result = json.loads(probe.stdout)
    assert Path(probe_result["package_file"]).resolve().is_relative_to(
        site_packages.resolve()
    )
    assert probe_result["schema_names"] == [
        "source-map",
        "normalized-role-input",
        "normalized-evidence-input",
        "review-decision",
        "approved-claims",
    ]

    source_root = tmp_path / "source"
    source_root.mkdir(mode=0o700)
    (source_root / "profile.md").write_text(
        "# Synthetic Profile\n\n- Built a synthetic service.\n",
        encoding="utf-8",
    )
    source_map_path = tmp_path / "source-map.json"
    discovered = subprocess.run(
        [
            sys.executable,
            "-m",
            "china_targeted_resume",
            "discover-source-structure",
            "--source",
            str(source_root),
            "--output",
            str(source_map_path),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    discovered_payload = json.loads(discovered.stdout)
    assert discovered_payload["operation"] == "discover-source-structure"

    validated = subprocess.run(
        [
            sys.executable,
            "-m",
            "china_targeted_resume",
            "validate-source-map",
            "--source",
            str(source_root),
            "--input",
            str(source_map_path),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(validated.stdout)["operation"] == "validate-source-map"
