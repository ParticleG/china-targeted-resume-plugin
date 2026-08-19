from __future__ import annotations

import os
from datetime import date

from china_targeted_resume.dossier import DOSSIER_FILES, render_dossier_files, write_dossier
from china_targeted_resume.models import Competency, SourceRef
from china_targeted_resume.role_analysis import detect_anomalies, order_sources


def test_role_dossier_has_exactly_seven_owning_files(dossier_factory, requirement_factory) -> None:
    requirement = requirement_factory()
    competency = Competency(
        competency_id="COMP-1",
        requirement_ids=[requirement.requirement_id],
        dimension="Distributed service operations",
        expected_depth="independent delivery",
        source_refs=["jd/current.md"],
    )
    dossier = dossier_factory(
        requirements=[requirement],
        competencies=[competency],
        anomalies=["SYNTHETIC_CONFLICT source-a versus source-b"],
        interview_questions=["Which synthetic incident best demonstrates the requirement?"],
        sources=[SourceRef(path="jd/current.md", source_hash="hash-jd", source_type="current-official")],
    )

    files = render_dossier_files(dossier, job_description="Synthetic complete JD source body.")

    assert tuple(files) == DOSSIER_FILES
    assert set(files) == {
        "job-description.md",
        "requirement-analysis.md",
        "competency-model.md",
        "evidence-mapping.md",
        "gap-analysis.md",
        "interview-preparation.md",
        "sources.md",
    }
    assert "Synthetic complete JD source body." in files["job-description.md"]
    assert all(
        "Synthetic complete JD source body." not in body
        for name, body in files.items()
        if name != "job-description.md"
    )
    assert requirement.requirement_id in files["requirement-analysis.md"]
    assert requirement.requirement_id not in files["competency-model.md"].split("Requirement IDs")[0]
    assert competency.competency_id in files["competency-model.md"]
    assert "SYNTHETIC_CONFLICT" in files["requirement-analysis.md"]


def test_dossier_write_uses_private_permissions(tmp_path, dossier_factory) -> None:
    output = tmp_path / "synthetic-output" / "role-dossier"

    written = write_dossier(
        dossier_factory(), output, job_description="Synthetic JD with no personal data."
    )

    assert tuple(path.name for path in written) == DOSSIER_FILES
    assert os.stat(output).st_mode & 0o777 == 0o700
    assert all(os.stat(path).st_mode & 0o777 == 0o600 for path in written)


def test_source_priority_retains_lower_priority_conflicts() -> None:
    sources = [
        {"id": "third", "source_type": "third-party", "published_at": "2026-08-01"},
        {"id": "snapshot", "source_type": "snapshot", "published_at": "2026-07-01"},
        {"id": "official", "source_type": "current-official", "published_at": "2026-08-02"},
    ]

    ordered = order_sources(sources)

    assert [source["id"] for source in ordered] == ["official", "snapshot", "third"]
    assert len(ordered) == len(sources)


def test_conflicts_and_staleness_are_reported_without_overwriting_claims() -> None:
    requirements = [
        {
            "requirement_id": "REQ-OFFICIAL",
            "text": "Kubernetes",
            "necessity": "required",
            "hard_gate": True,
            "origin": "explicit",
            "verbatim_quote": "Kubernetes",
            "source_ref": "official",
        },
        {
            "requirement_id": "REQ-SNAPSHOT",
            "text": "Kubernetes",
            "necessity": "preferred",
            "hard_gate": False,
            "origin": "explicit",
            "verbatim_quote": "Kubernetes",
            "source_ref": "snapshot",
        },
    ]
    sources = [
        {"id": "official", "source_type": "current-official", "published_at": "2026-08-01"},
        {"id": "snapshot", "source_type": "snapshot", "published_at": "2025-01-01"},
    ]

    anomalies = detect_anomalies(requirements, sources, as_of=date(2026, 8, 14))

    assert any(item.startswith("SOURCE_CONFLICT") for item in anomalies)
    assert any(item.startswith("STALE_SOURCE source=snapshot") for item in anomalies)
    conflict = next(item for item in anomalies if item.startswith("SOURCE_CONFLICT"))
    assert "REQ-OFFICIAL@official" in conflict
    assert "REQ-SNAPSHOT@snapshot" in conflict
