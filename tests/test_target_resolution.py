from __future__ import annotations

from datetime import date

import pytest

from china_targeted_resume.models import JdCompleteness, TargetBasis
from china_targeted_resume.target_resolution import resolve_target


def test_tier_a_requires_complete_current_jd_and_preserves_exact_identity() -> None:
    context = resolve_target(
        {"company": "Acme Cloudworks", "role": "Platform Engineer"},
        jd_text="Must operate distributed systems.",
        jd_complete=True,
        source_date=date(2026, 8, 1),
    )

    assert context.target_basis is TargetBasis.EXACT_CURRENT_JD
    assert context.jd_completeness is JdCompleteness.COMPLETE
    assert context.company == "Acme Cloudworks"
    assert context.role == "Platform Engineer"
    assert context.staleness_risk == "none"
    assert context.source_refs[0].startswith("inline-current-jd:sha256:")


@pytest.mark.parametrize("partial", [{"requirements": ["synthetic"]}, "historical dossier"])
def test_tier_b_continues_analysis_but_never_claims_coverage(partial: object) -> None:
    context = resolve_target(
        {"company": "Acme Cloudworks", "role": "Platform Engineer"},
        partial_dossier=partial,
    )

    assert context.target_basis is TargetBasis.EXACT_ROLE_PARTIAL_EVIDENCE
    assert context.jd_completeness is JdCompleteness.STALE
    assert context.explicit_requirement_coverage is None
    assert context.staleness_risk == "high"
    assert context.evidence_coverage_summary is not None
    assert any("current" in limitation.casefold() for limitation in context.limitations)


def test_incomplete_current_text_is_tier_b_not_tier_a() -> None:
    context = resolve_target(
        {"company": "Acme Cloudworks", "role": "Platform Engineer"},
        jd_text="Responsibilities excerpt only",
        jd_complete=False,
    )

    assert context.target_basis is TargetBasis.EXACT_ROLE_PARTIAL_EVIDENCE
    assert context.jd_completeness is JdCompleteness.PARTIAL
    assert context.explicit_requirement_coverage is None
    assert any("incomplete" in limitation.casefold() for limitation in context.limitations)


def test_tier_c_is_company_role_family_without_exact_role() -> None:
    context = resolve_target({"company": "Nebula Robotics", "role_family": "Platform Engineering"})

    assert context.target_basis is TargetBasis.COMPANY_ROLE_FAMILY
    assert context.company == "Nebula Robotics"
    assert context.role is None
    assert context.jd_completeness is JdCompleteness.UNAVAILABLE
    assert context.explicit_requirement_coverage is None


def test_tier_d_does_not_invent_missing_target_identity() -> None:
    context = resolve_target({"company": "Acme Cloudworks"})

    assert context.target_basis is TargetBasis.INSUFFICIENT_TARGET
    assert context.company == "Acme Cloudworks"
    assert context.role is None
    assert context.explicit_requirement_coverage is None
    assert context.limitations


def test_multiple_current_jd_sources_are_rejected(synthetic_career_db) -> None:
    jd_file = synthetic_career_db / "role-research" / "acme-cloudworks-platform-engineer" / "job-description.md"
    with pytest.raises(ValueError, match="only one"):
        resolve_target({}, jd_text="synthetic", jd_file=jd_file, allowed_source_roots=[synthetic_career_db])


def test_jd_file_must_remain_inside_allowed_synthetic_root(synthetic_career_db, tmp_path) -> None:
    outside = tmp_path / "synthetic-outside-jd.md"
    outside.write_text("Synthetic outside JD", encoding="utf-8")

    with pytest.raises(ValueError, match="outside allowed source roots"):
        resolve_target({}, jd_file=outside, allowed_source_roots=[synthetic_career_db])
