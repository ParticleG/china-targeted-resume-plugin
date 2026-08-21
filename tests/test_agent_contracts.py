from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agents"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "agent_contracts" / "disagreement-cases.json"
AGENT_NAMES = {
    "source-mapper",
    "role-analyst",
    "requirement-reviewer",
    "evidence-reviewer",
    "contribution-reviewer",
    "privacy-reviewer",
    "resume-advisor",
}
REVIEWER_NAMES = {
    "requirement-reviewer",
    "evidence-reviewer",
    "contribution-reviewer",
    "privacy-reviewer",
}
KERNEL_REVIEWER_NAMES = {
    "requirement-reviewer",
    "evidence-reviewer",
    "contribution-reviewer",
    "privacy-reviewer",
}
KERNEL_DECISION_FIELDS = {
    "review_id",
    "evidence_id",
    "reviewer_id",
    "review_kind",
    "outcome",
    "reasoning",
    "approved_safe_claim",
    "contribution_qualifiers",
    "metric_qualifiers",
    "disclosure_decision",
    "disclosure_audience",
    "disclosure_purpose",
    "user_confirmation_required",
    "user_confirmed",
    "questions",
}
REVIEW_KINDS = {
    "requirement-reviewer": "requirement",
    "evidence-reviewer": "evidence",
    "contribution-reviewer": "contribution_metric",
    "privacy-reviewer": "privacy",
}
ROLE_FIELDS = {
    "source-mapper": {"mapping_id", "mapper_id", "proposals", "slice_requests"},
    "role-analyst": {"analysis_id", "analyst_id", "requirements", "constraints", "conflicts"},
    "requirement-reviewer": {"decision", "requirement_id", "proposal_id", "support", "classification", "freshness"},
    "evidence-reviewer": {"decision", "claim_id", "support_finding", "unsupported_elements"},
    "contribution-reviewer": {"decision", "contribution_finding", "metric_finding", "mismatches", "required_resolution"},
    "privacy-reviewer": {"decision", "effective_disclosure_policy", "permission_status", "redactions"},
    "resume-advisor": {"advisory_id", "warnings", "missing_steps", "approval_granted"},
}
EXPECTED_CASES = {
    "unsupported-evidence",
    "p3-rejection",
    "unknown-p2-permission",
    "contribution-metric-conflict",
    "majority-cannot-override-policy",
    "advisor-attempted-approval",
}


def _agent_contract(name: str) -> tuple[dict[str, str], dict[str, Any], str]:
    text = (AGENT_DIR / f"{name}.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw_frontmatter, body = text.split("---", 2)
    lines = raw_frontmatter.strip("\n").splitlines()
    output_index = lines.index("output: |-")
    scalar_lines = lines[:output_index]
    fields = {
        key.strip(): value.strip().strip('"')
        for key, value in (line.split(":", 1) for line in scalar_lines if ":" in line)
    }
    output_text = "\n".join(line[2:] for line in lines[output_index + 1 :])
    return fields, json.loads(output_text), body.strip()


def _contracts() -> dict[str, tuple[dict[str, str], dict[str, Any], str]]:
    return {name: _agent_contract(name) for name in AGENT_NAMES}


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

def _decision_schema(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    if name in KERNEL_REVIEWER_NAMES:
        return schema["properties"]["decision"]
    return schema


def _decision(output: dict[str, Any]) -> dict[str, Any]:
    decision = output.get("decision")
    return decision if isinstance(decision, dict) else output


def _resolve_hard_gate(outputs: list[dict[str, Any]]) -> tuple[str, str, bool]:
    for output in outputs:
        if output["agent_role"] == "privacy-reviewer":
            if output["effective_disclosure_policy"] == "P3":
                return "reject", "p3_forbidden", False
            if output["effective_fact_policy"] == "F6":
                return "reject", "f6_forbidden", False

    for output in outputs:
        if output["agent_role"] == "evidence-reviewer" and output["support_finding"] == "unsupported":
            return "reject", "unsupported_evidence", False

    for output in outputs:
        if (
            output["agent_role"] == "privacy-reviewer"
            and output["effective_disclosure_policy"] == "P2"
            and output["permission_status"] == "unknown"
        ):
            return "needs_confirmation", "p2_permission_unknown", True

    for output in outputs:
        if output["agent_role"] == "contribution-reviewer" and (
            output["contribution_finding"] in {"expanded", "ambiguous"}
            or output["metric_finding"] in {"expanded", "ambiguous"}
            or output["actor_scope_finding"] in {"expanded", "ambiguous"}
        ):
            requires_user = output["required_resolution"] == "user_confirmation"
            return "disagree", "contribution_metric_conflict", requires_user

    if any(_decision(output)["outcome"] == "reject" for output in outputs):
        return "reject", "review_rejected", False
    if any(_decision(output)["outcome"] == "needs_confirmation" for output in outputs):
        return "needs_confirmation", "review_confirmation_required", True
    if any(_decision(output)["outcome"] == "disagree" for output in outputs):
        return "disagree", "review_disagreement", True
    return "approve", "none", False


def test_all_seven_agent_definitions_are_strict_and_non_mutating() -> None:
    assert {path.stem for path in AGENT_DIR.glob("*.md")} == AGENT_NAMES

    contracts = _contracts()
    for name, (frontmatter, schema, body) in contracts.items():
        assert frontmatter["name"] == name
        assert frontmatter["description"]
        assert frontmatter["tools"] == "yield"
        assert frontmatter["spawns"] == "[]"
        assert schema["additionalProperties"] is False
        assert schema["properties"]["agent_role"]["const"] == name
        assert {"outcome", "reasoning"} <= set(_decision_schema(name, schema)["required"])
        assert ROLE_FIELDS[name] <= set(schema["required"])
        Draft202012Validator.check_schema(schema)

        normalized_body = body.casefold()
        assert "metadata-only mode" in normalized_body
        assert "authorized minimum-slice mode" in normalized_body
        assert "always forbidden" in normalized_body
        assert "non-goals and mutation boundary" in normalized_body
        assert "must not" in normalized_body and "mutat" in normalized_body
        assert "contact" in normalized_body
        assert "credential" in normalized_body
        assert "f6" in normalized_body and "p3" in normalized_body


def test_slice_capable_agents_require_exact_runtime_receipt_identity() -> None:
    contracts = _contracts()
    for name in AGENT_NAMES - {"resume-advisor"}:
        body = contracts[name][2]
        assert "resume_read_source_slice" in body
        assert "`ok: true`" in body
        assert "`authorizationId`" in body
        assert "exact model" in body
        assert "`local`/`remote` locality" in body
        assert f"consumer `{name}`" in body
        assert "purpose" in body
        assert "exact `path`" in body
        assert "exact `startLine`/`endLine`" in body
        assert "byte" in body
        assert "`requestId` when" in body
        assert "Copy `authorizationId` byte-for-byte" in body
        assert "never invent" in body.casefold()


def test_reviewer_contracts_require_independent_identity_and_distinct_findings() -> None:
    contracts = _contracts()
    schema_fingerprints = {json.dumps(contract[1], sort_keys=True) for contract in contracts.values()}
    body_fingerprints = {contract[2] for contract in contracts.values()}
    assert len(schema_fingerprints) == len(AGENT_NAMES)
    assert len(body_fingerprints) == len(AGENT_NAMES)

    role_specific_shapes: set[frozenset[str]] = set()
    for name in REVIEWER_NAMES:
        _, schema, body = contracts[name]
        decision_schema = _decision_schema(name, schema)
        required = set(decision_schema["required"])
        assert {"review_id", "reviewer_id", "review_kind", "outcome", "reasoning"} <= required
        assert decision_schema["properties"]["review_kind"]["const"] == REVIEW_KINDS[name]
        if name in KERNEL_REVIEWER_NAMES:
            assert required == KERNEL_DECISION_FIELDS
            assert set(decision_schema["properties"]) == KERNEL_DECISION_FIELDS
            assert decision_schema["properties"]["user_confirmed"] == {"const": False}
        assert "hidden reasoning" in body.casefold()
        role_specific_shapes.add(frozenset(ROLE_FIELDS[name]))
    assert len(role_specific_shapes) == len(REVIEWER_NAMES)


def test_complete_reviewer_wrappers_are_routed_without_prelock_flattening() -> None:
    wrappers = [
        output
        for case in _fixture()["cases"]
        for output in case.get("agent_outputs", [])
        if output["agent_role"] in KERNEL_REVIEWER_NAMES
    ]
    assert wrappers
    for wrapper in wrappers:
        assert {"agent_role", "mode", "authorization_id", "decision"} <= set(wrapper)
        decision = wrapper["decision"]
        assert set(decision) == KERNEL_DECISION_FIELDS
        if decision["review_kind"] in {"evidence", "contribution_metric", "privacy"} and decision["outcome"] == "approve":
            assert isinstance(decision["approved_safe_claim"], str)
            assert decision["approved_safe_claim"]
        else:
            assert decision["approved_safe_claim"] is None

    role_validation_wrappers = [
        wrapper for wrapper in wrappers if wrapper["agent_role"] == "requirement-reviewer"
    ]
    claim_lock_wrappers = [
        wrapper
        for wrapper in wrappers
        if wrapper["agent_role"] in {"evidence-reviewer", "contribution-reviewer", "privacy-reviewer"}
    ]
    approving_claim_decisions = [
        wrapper["decision"]
        for wrapper in claim_lock_wrappers
        if wrapper["decision"]["outcome"] == "approve"
    ]
    assert len(approving_claim_decisions) >= 2
    assert len({decision["approved_safe_claim"] for decision in approving_claim_decisions}) == 1
    assert len({decision["reviewer_id"] for decision in approving_claim_decisions}) == len(
        approving_claim_decisions
    )
    assert role_validation_wrappers
    assert claim_lock_wrappers
    assert {wrapper["decision"]["review_id"] for wrapper in role_validation_wrappers}.isdisjoint(
        wrapper["decision"]["review_id"] for wrapper in claim_lock_wrappers
    )


def test_decision_schema_locks_claim_text_and_rejects_agent_confirmation() -> None:
    fixture = _fixture()
    contracts = _contracts()

    unsupported = next(
        case for case in fixture["cases"] if case["case_id"] == "unsupported-evidence"
    )["agent_outputs"][0]
    rejected_with_text = json.loads(json.dumps(unsupported))
    rejected_with_text["decision"]["approved_safe_claim"] = "must not survive rejection"
    assert list(
        Draft202012Validator(contracts["evidence-reviewer"][1]).iter_errors(rejected_with_text)
    )

    majority = next(
        case for case in fixture["cases"] if case["case_id"] == "majority-cannot-override-policy"
    )
    approving_evidence = next(
        output for output in majority["agent_outputs"] if output["agent_role"] == "evidence-reviewer"
    )
    approval_without_text = json.loads(json.dumps(approving_evidence))
    approval_without_text["decision"]["approved_safe_claim"] = None
    assert list(
        Draft202012Validator(contracts["evidence-reviewer"][1]).iter_errors(approval_without_text)
    )

    approving_requirement = next(
        output for output in majority["agent_outputs"] if output["agent_role"] == "requirement-reviewer"
    )
    requirement_with_text = json.loads(json.dumps(approving_requirement))
    requirement_with_text["decision"]["approved_safe_claim"] = "requirements never approve claim text"
    assert list(
        Draft202012Validator(contracts["requirement-reviewer"][1]).iter_errors(requirement_with_text)
    )

    unknown_p2 = next(
        case for case in fixture["cases"] if case["case_id"] == "unknown-p2-permission"
    )["agent_outputs"][0]
    agent_claimed_confirmation = json.loads(json.dumps(unknown_p2))
    agent_claimed_confirmation["decision"]["user_confirmed"] = True
    assert list(
        Draft202012Validator(contracts["privacy-reviewer"][1]).iter_errors(agent_claimed_confirmation)
    )


def test_reviewed_semantic_outputs_copy_exact_runtime_authorization_receipts() -> None:
    fixture = _fixture()
    receipts = fixture["authorization_receipts"]
    allowed_receipt_fields = {
        "ok",
        "authorizationId",
        "provider",
        "model",
        "locality",
        "requestId",
        "mode",
        "consumer",
        "purpose",
        "path",
        "startLine",
        "endLine",
        "category",
        "bytes",
    }
    assert receipts
    for receipt in receipts:
        assert set(receipt) <= allowed_receipt_fields
        assert {
            "ok",
            "authorizationId",
            "provider",
            "model",
            "locality",
            "mode",
            "consumer",
            "purpose",
            "path",
            "startLine",
            "endLine",
            "bytes",
        } <= set(receipt)
        assert receipt["ok"] is True
        assert receipt["mode"] == "reviewed-semantic"
        assert receipt["consumer"] in {
            "source-mapper",
            "role-analyst",
            "requirement-reviewer",
            "evidence-reviewer",
            "contribution-reviewer",
            "privacy-reviewer",
        }
        assert receipt["provider"] and receipt["model"]
        assert receipt["locality"] in {"local", "remote"}
        assert receipt["purpose"]
        assert receipt["path"].startswith("/")
        assert receipt["startLine"] >= 1
        assert receipt["endLine"] >= receipt["startLine"]
        assert receipt["bytes"] >= 0

    reviewed_outputs = [
        output
        for case in fixture["cases"]
        for output in case.get("agent_outputs", [])
        if output.get("mode") == "reviewed_semantic"
    ]
    assert reviewed_outputs
    for output in reviewed_outputs:
        matching = [
            receipt
            for receipt in receipts
            if receipt["authorizationId"] == output["authorization_id"]
            and receipt["consumer"] == output["agent_role"]
        ]
        assert len(matching) == 1

    invented = json.loads(json.dumps(reviewed_outputs[0]))
    invented["authorization_id"] = "authorization:invented"
    assert not [
        receipt
        for receipt in receipts
        if receipt["authorizationId"] == invented["authorization_id"]
        and receipt["consumer"] == invented["agent_role"]
    ]


def test_disagreement_fixtures_are_schema_valid_and_cover_every_hard_gate() -> None:
    contracts = _contracts()
    fixture = _fixture()
    assert fixture["fixture_version"] == 1
    assert {case["case_id"] for case in fixture["cases"]} == EXPECTED_CASES

    for case in fixture["cases"]:
        if "agent_outputs" not in case:
            continue
        for output in case["agent_outputs"]:
            validator = Draft202012Validator(contracts[output["agent_role"]][1])
            assert not list(validator.iter_errors(output)), case["case_id"]

        aggregate_outcome, hard_gate, user_confirmation_required = _resolve_hard_gate(case["agent_outputs"])
        assert aggregate_outcome == case["expected"]["aggregate_outcome"]
        assert hard_gate == case["expected"]["hard_gate"]
        assert user_confirmation_required is case["expected"]["user_confirmation_required"]
        assert case["expected"]["compose_allowed"] is False


def test_reviewer_majority_does_not_override_hard_policy() -> None:
    case = next(item for item in _fixture()["cases"] if item["case_id"] == "majority-cannot-override-policy")
    approvals = [output for output in case["agent_outputs"] if _decision(output)["outcome"] == "approve"]
    rejections = [output for output in case["agent_outputs"] if _decision(output)["outcome"] == "reject"]
    assert len(approvals) > len(rejections)
    assert _resolve_hard_gate(case["agent_outputs"]) == ("reject", "p3_forbidden", False)


def test_advisor_attempted_approval_is_rejected_by_schema() -> None:
    case = next(item for item in _fixture()["cases"] if item["case_id"] == "advisor-attempted-approval")
    _, schema, body = _agent_contract("resume-advisor")
    errors = list(Draft202012Validator(schema).iter_errors(case["attempted_output"]))
    assert errors
    assert case["attempted_output"]["outcome"] == "approve"
    assert case["attempted_output"]["approval_granted"] is True
    assert "never approve" in body.casefold()
    assert schema["properties"]["approval_granted"] == {"const": False}
    assert "approve" not in schema["properties"]["outcome"]["enum"]


def test_fixtures_contain_no_raw_or_forbidden_input_fields() -> None:
    forbidden_keys = {
        "raw_source",
        "source_body",
        "slice_text",
        "contact",
        "credential",
        "secret",
        "hidden_reasoning",
        "chain_of_thought",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(_fixture())
