from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import shutil
from typing import Any

import pytest

from china_targeted_resume.models import (
    DisclosureLevel,
    EvidenceCandidate,
    EvidenceMapping,
    FactState,
    Requirement,
    RequirementNecessity,
    RequirementOrigin,
    RoleDossierIR,
    RoleMatchState,
    SourceRef,
    SourceSpan,
    TargetBasis,
    TargetContext,
    JdCompleteness,
)


@pytest.fixture(scope="session")
def synthetic_career_db() -> Path:
    root = Path(__file__).parent / "fixtures" / "synthetic-career-db"
    assert root.is_dir()
    return root


@pytest.fixture
def synthetic_db_copy(synthetic_career_db: Path, tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-career-db"
    shutil.copytree(synthetic_career_db, root)
    return root


@pytest.fixture
def requirement_factory() -> Callable[..., Requirement]:
    def make(**overrides: Any) -> Requirement:
        data: dict[str, Any] = {
            "requirement_id": "req-platform",
            "text": "Must operate distributed services in production",
            "verbatim_quote": "Must operate distributed services in production",
            "category": "technical",
            "necessity": RequirementNecessity.REQUIRED,
            "priority": "high",
            "origin": RequirementOrigin.EXPLICIT,
            "source_ref": "jd/current.md",
            "source_span": SourceSpan(start_line=3, end_line=3),
            "confidence": 1.0,
            "hard_gate": False,
            "keywords": ["distributed", "production"],
        }
        data.update(overrides)
        return Requirement.model_validate(data)

    return make


@pytest.fixture
def candidate_factory() -> Callable[..., EvidenceCandidate]:
    def make(**overrides: Any) -> EvidenceCandidate:
        data: dict[str, Any] = {
            "candidate_id": "candidate-platform",
            "requirement_ids": ["req-platform"],
            "source": SourceRef(
                path="personal-data/work/orbit-orchard-experience.md",
                title="Orbit Orchard",
                section="Reliability contribution",
                source_hash="fixture-hash-a",
                source_type="career-source",
                accessed_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            "source_span": SourceSpan(start_line=8, end_line=9),
            "proposed_claim": "Contributed to a team pilot that reduced latency by about 20% in 2025.",
            "fact_state": FactState.F2,
            "disclosure": DisclosureLevel.P1,
            "match_state": RoleMatchState.DIRECT_EVIDENCE,
            "confidence": 0.9,
        }
        data.update(overrides)
        return EvidenceCandidate.model_validate(data)

    return make


@pytest.fixture
def mapping_factory() -> Callable[..., EvidenceMapping]:
    def make(**overrides: Any) -> EvidenceMapping:
        data: dict[str, Any] = {
            "requirement_id": "req-platform",
            "match_state": RoleMatchState.CLEAR_GAP,
            "evidence_ids": [],
            "selection_reason": "No eligible direct evidence.",
            "resume_priority": 0.8,
            "missing_evidence": ["A verified production example is required."],
        }
        data.update(overrides)
        return EvidenceMapping.model_validate(data)

    return make


@pytest.fixture
def dossier_factory() -> Callable[..., RoleDossierIR]:
    def make(**overrides: Any) -> RoleDossierIR:
        data: dict[str, Any] = {
            "target_context": TargetContext(
                target_basis=TargetBasis.EXACT_CURRENT_JD,
                company="Acme Cloudworks",
                role="Platform Engineer",
                jd_completeness=JdCompleteness.COMPLETE,
                staleness_risk="none",
                source_refs=["jd/current.md"],
            ),
            "requirements": [],
            "competencies": [],
            "application_constraints": [],
            "evidence_candidates": [],
            "evidence_records": [],
            "evidence_mappings": [],
            "gaps": [],
            "roadmap_handoff": [],
            "provenance": [],
            "anomalies": [],
            "interview_questions": [],
            "sources": [],
            "limitations": [],
        }
        data.update(overrides)
        return RoleDossierIR.model_validate(data)

    return make
