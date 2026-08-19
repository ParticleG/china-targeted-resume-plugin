from __future__ import annotations

import pytest
from pydantic import ValidationError

from china_targeted_resume.competencies import build_competencies, merge_role_family_competencies
from china_targeted_resume.models import Competency


def test_competencies_describe_job_expectations_not_candidate_match(requirement_factory) -> None:
    raw = requirement_factory().model_dump(mode="json")
    raw.update(
        {
            "candidate_match": "strong",
            "evidence_ids": ["ev-personal"],
            "gap_severity": "Critical",
            "score": 0.99,
        }
    )

    [competency] = build_competencies([raw])
    serialized = competency.model_dump(mode="json")

    assert competency.requirement_ids == [raw["requirement_id"]]
    assert competency.dimension == raw["text"]
    assert competency.expected_depth == "independent delivery"
    assert not ({"candidate_match", "evidence_ids", "gap_severity", "score"} & serialized.keys())
    assert "strong" not in str(serialized)
    assert "ev-personal" not in str(serialized)


@pytest.mark.parametrize("candidate_field", ["candidate_match", "evidence_ids", "match_state", "coverage"])
def test_competency_schema_rejects_candidate_dimensions(candidate_field: str) -> None:
    payload = {
        "competency_id": "COMP-1",
        "requirement_ids": ["REQ-1"],
        "dimension": "Distributed systems",
        "expected_depth": "independent delivery",
        "source_refs": ["fixture-jd"],
        candidate_field: "candidate-specific",
    }
    with pytest.raises(ValidationError):
        Competency.model_validate(payload)


def test_distinct_source_expectations_remain_traceable(requirement_factory) -> None:
    first = requirement_factory(requirement_id="REQ-A", text="Operate queues", verbatim_quote="Operate queues")
    second = requirement_factory(requirement_id="REQ-B", text="Operate queues", verbatim_quote="Operate queues")

    competencies = build_competencies([first, second])

    assert len(competencies) == 2
    assert [item.requirement_ids for item in competencies] == [["REQ-A"], ["REQ-B"]]


def test_role_family_merge_combines_traceability_without_candidate_fields() -> None:
    baseline = {
        "competency_id": "family",
        "requirement_ids": ["REQ-FAMILY"],
        "dimension": "Incident response",
        "expected_depth": "working familiarity",
        "source_refs": ["role-family/platform.md"],
        "candidate_match": "none",
    }
    delta = {
        "competency_id": "company",
        "requirement_ids": ["REQ-COMPANY"],
        "dimension": "Incident response",
        "expected_depth": "independent delivery",
        "source_refs": ["company/acme-jd.md"],
        "evidence_ids": ["ev-should-not-leak"],
    }

    [merged] = merge_role_family_competencies(
        [baseline], [delta], company_explicit_source_ids=["company/acme-jd.md"]
    )

    assert merged.requirement_ids == ["REQ-FAMILY", "REQ-COMPANY"]
    assert merged.source_refs == ["role-family/platform.md", "company/acme-jd.md"]
    assert merged.expected_depth == "independent delivery"
    assert "ev-should-not-leak" not in str(merged.model_dump(mode="json"))
