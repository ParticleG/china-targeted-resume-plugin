from __future__ import annotations

from datetime import UTC, datetime

import pytest

from china_targeted_resume.models import DisclosureLevel, FactState, OutputMode
from china_targeted_resume.policy import apply_evidence_policy, parse_policy_markers


@pytest.mark.parametrize(
    ("fact", "candidate", "output", "confirmation"),
    [
        ("F1", True, True, False),
        ("F2", True, True, False),
        ("F4", True, False, True),
        ("F5", True, False, False),
        ("F6", False, False, False),
    ],
)
def test_fact_state_gates_are_fail_closed(fact, candidate, output, confirmation) -> None:
    decision = apply_evidence_policy(
        {"fact_state": fact, "disclosure": "P1", "safe_claim": "Synthetic verified claim"},
        OutputMode.TARGETED_APPLICATION,
    )
    assert decision.allowed_as_candidate is candidate
    assert decision.allowed_in_output is output
    assert decision.confirmation_required is confirmation
    if not candidate:
        assert decision.record is None


def test_f3_requires_current_nonstale_verification() -> None:
    current = apply_evidence_policy(
        {
            "fact_state": "F3",
            "disclosure": "P1",
            "safe_claim": "Synthetic current claim",
            "freshness": {
                "checked_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-09-01T00:00:00Z",
                "stale": False,
            },
        },
        "targeted_application",
        now=datetime(2026, 8, 14, tzinfo=UTC),
    )
    stale = apply_evidence_policy(
        {
            "fact_state": "F3",
            "disclosure": "P1",
            "safe_claim": "Synthetic stale claim",
            "freshness": {"checked_at": None, "stale": True},
        },
        "targeted_application",
        now=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert current.allowed_in_output is True
    assert current.current_verification_required is True
    assert stale.allowed_as_candidate is True
    assert stale.allowed_in_output is False
    assert stale.confirmation_required is True
    assert "current_verification_required" in stale.reason_codes


@pytest.mark.parametrize(
    ("disclosure", "mode", "allowed"),
    [
        ("P0", "public_portfolio", True),
        ("P1", "master_resume", True),
        ("P2", "targeted_application", True),
        ("P2", "public_portfolio", False),
        ("P3", "targeted_application", False),
    ],
)
def test_disclosure_gate_depends_on_output_mode(disclosure, mode, allowed) -> None:
    decision = apply_evidence_policy(
        {"fact_state": "F1", "disclosure": disclosure, "safe_claim": "Synthetic claim"}, mode
    )
    assert decision.allowed_in_output is allowed


def test_sensitive_content_blocks_candidate_and_does_not_echo_record() -> None:
    decision = apply_evidence_policy(
        {"fact_state": "F1", "disclosure": "P0", "safe_claim": "password=FIXTURE_SECRET"},
        "targeted_application",
    )

    assert decision.allowed_as_candidate is False
    assert decision.allowed_in_output is False
    assert decision.record is None
    assert "sensitive_content_detected" in decision.reason_codes


def test_marker_parser_uses_most_restrictive_explicit_markers() -> None:
    fact, disclosure = parse_policy_markers("F1 reviewed, but section boundary is F6; P0 then P3")
    assert fact is FactState.F6
    assert disclosure is DisclosureLevel.P3


def test_marker_parser_defaults_fail_closed_when_absent() -> None:
    fact, disclosure = parse_policy_markers("No classification markers in this synthetic line")
    assert fact is FactState.F5
    assert disclosure is DisclosureLevel.P3
