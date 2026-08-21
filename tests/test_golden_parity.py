from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from china_targeted_resume.validation import (
    IRValidationError,
    approve_claims,
    check_provenance_closure,
    lock_approved_claims,
    validate_schema_document,
)
from china_targeted_resume.policy import apply_evidence_policy
from china_targeted_resume.provenance import build_provenance


GOLDEN_ROOT = Path(__file__).with_name("golden")
MANIFEST_PATH = GOLDEN_ROOT / "manifest.json"
SCHEMA_CASES_PATH = GOLDEN_ROOT / "schema-cases.json"
KERNEL_CASES_PATH = GOLDEN_ROOT / "kernel-cases.json"
SCHEMA_NORMALIZED_PATH = GOLDEN_ROOT / "schema-normalized.json"
APPROVAL_CASES_PATH = GOLDEN_ROOT / "approval-cases.json"


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _canonical(value: Any) -> Any:
    """Normalize only the documented JSON representation, never semantics."""
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value



def _ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_id") and isinstance(item, str):
                found.add(item)
            elif key.endswith("_ids") and isinstance(item, list):
                found.update(item for item in item if isinstance(item, str))
            found.update(_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_ids(item))
    return found


def _resolve_derived_approval(
    derived: dict[str, Any],
    base_cases: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = copy.deepcopy(next(case for case in base_cases["cases"] if case["case_id"] == derived["base_case"]))
    evidence = base["evidence"]
    candidate = evidence["candidates"][0]
    overrides = derived["candidate_overrides"]
    evidence["input_id"] = overrides["input_id"]
    candidate["evidence_id"] = overrides["evidence_id"]
    if "owner" in overrides:
        candidate["owner"] = overrides["owner"]
    if "claim_mode" in overrides:
        candidate["claim_mode"] = overrides["claim_mode"]
    if "unresolved_questions" in overrides:
        candidate["unresolved_questions"] = overrides["unresolved_questions"]
    if "evidence_unresolved_questions" in derived:
        evidence["unresolved_questions"] = derived["evidence_unresolved_questions"]
    flags = candidate["source"]["structural_flags"]
    flags["effective_fact_policy"] = overrides["effective_fact_policy"]
    flags["effective_disclosure_policy"] = overrides["effective_disclosure_policy"]
    return evidence, derived["reviews"], derived["options"]




@pytest.fixture(scope="module")
def golden_manifest() -> dict[str, Any]:
    return _load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def schema_cases() -> dict[str, Any]:
    return _load(SCHEMA_CASES_PATH)

@pytest.fixture(scope="module")
def normalized_schema_cases() -> dict[str, Any]:
    return _load(SCHEMA_NORMALIZED_PATH)
 
@pytest.fixture(scope="module")
def approval_cases() -> dict[str, Any]:
    return _load(APPROVAL_CASES_PATH)


@pytest.fixture(scope="module")
def kernel_cases() -> dict[str, Any]:
    return _load(KERNEL_CASES_PATH)


def test_golden_source_hash_and_utf8_spans(golden_manifest: dict[str, Any]) -> None:
    source = golden_manifest["source_fixtures"]
    path = GOLDEN_ROOT / source["record"]
    data = path.read_bytes()
    assert f"sha256:{hashlib.sha256(data).hexdigest()}" == source["sha256"]
    for span in source["utf8_spans"]:
        actual = data[span["start_byte"] : span["end_byte"]].decode("utf-8")
        assert actual == span["quote"]
        assert data[: span["start_byte"]].count(b"\n") + 1 == span["start_line"]
        assert data[: max(span["start_byte"], span["end_byte"] - 1)].count(b"\n") + 1 == span["end_line"]


def test_golden_schema_acceptance_and_rejection(
    schema_cases: dict[str, Any],
    normalized_schema_cases: dict[str, Any],
) -> None:
    for case in schema_cases["cases"]:
        value = case["input"]
        if case["accepted"]:
            model = validate_schema_document(value, case["schema"])
            normalized = model.model_dump(mode="json")
            expected = normalized_schema_cases["cases"][case["case_id"]]
            assert _canonical(normalized) == _canonical(expected)
            expected_ids = set(case.get("expected", {}).get("stable_ids", []))
            assert expected_ids <= _ids(normalized)
            expected_hashes = set(case.get("expected", {}).get("source_hashes", []))
            assert expected_hashes <= {item for item in json.dumps(normalized).split('"') if item.startswith("sha256:")}
            if case["schema"] == "approved-claims":
                final_claims = {
                    claim["claim_id"]: claim["approved_safe_claim"]
                    for claim in value.get("claims", [])
                }
                locked = lock_approved_claims(value, final_claims)
                assert locked.model_dump(mode="json") == normalized
                claim_id = next(iter(final_claims))
                mutated = dict(final_claims)
                mutated[claim_id] = f"{mutated[claim_id]} changed"
                with pytest.raises(IRValidationError):
                    lock_approved_claims(value, mutated)
        else:
            with pytest.raises((IRValidationError, ValueError)):
                validate_schema_document(value, case["schema"])


def test_golden_executable_p2_approval_cases(approval_cases: dict[str, Any]) -> None:
    for case in approval_cases["cases"]:
        expected = case["expected"]
        options = case["options"]
        if expected["accepted"]:
            result = approve_claims(
                case["evidence"],
                case["reviews"],
                approved_safe_claims=options["approved_safe_claims"],
                user_confirmations=options["user_confirmations"],
            )
            claim = result.claims[0]
            expected_claim = {key: value for key, value in expected.items() if key != "accepted"}
            assert _canonical(claim.model_dump(mode="json")) == _canonical(expected_claim)
            assert claim.claim_id == expected["claim_id"]
            assert claim.approval_basis.value == expected["approval_basis"]
            assert claim.reviewer_decision_ids == expected["reviewer_decision_ids"]
            assert claim.approved_safe_claim == expected["approved_safe_claim"]
            assert claim.disclosure_decision.value == expected["disclosure_decision"]
            assert claim.disclosure_audience.value == expected["disclosure_audience"]
            assert claim.disclosure_purpose == expected["disclosure_purpose"]
        else:
            if "error_message" in expected:
                with pytest.raises(IRValidationError) as error:
                    approve_claims(
                        case["evidence"],
                        case["reviews"],
                        approved_safe_claims=options["approved_safe_claims"],
                        user_confirmations=options["user_confirmations"],
                    )
                assert str(error.value) == expected.get("error_message_python", expected["error_message"])
            else:
                with pytest.raises(IRValidationError, match=expected["error_contains"]):
                    approve_claims(
                        case["evidence"],
                        case["reviews"],
                        approved_safe_claims=options["approved_safe_claims"],
                        user_confirmations=options["user_confirmations"],
                    )


def test_golden_normalization_is_semantic_and_not_timestamp_erasure(golden_manifest: dict[str, Any]) -> None:
    assert golden_manifest["normalization"]["omit_fields"] == []
    assert golden_manifest["nondeterministic_fields"] == [
        "run.started_at",
        "run.finished_at",
        "run.directory_suffix",
        "artifact.generated_at",
    ]
    left = {"claim_id": "claim.queue.extractive", "approved_safe_claim": "Built a queue worker."}
    right = {"claim_id": "claim.queue.extractive", "approved_safe_claim": "Owned a queue worker."}
    assert _canonical(left) != _canonical(right)

def test_golden_executable_policy_approval_lock_and_provenance_cases(
    kernel_cases: dict[str, Any],
    approval_cases: dict[str, Any],
) -> None:
    for case in kernel_cases["policy_cases"]:
        decision = apply_evidence_policy(case["python_record"], case["mode"])
        assert _canonical(decision.model_dump(mode="json")) == _canonical(case["expected_python"])

    for case in kernel_cases["approval_cases"]:
        evidence, reviews, options = _resolve_derived_approval(case, approval_cases)
        expected = case["expected"]
        if expected["accepted"]:
            result = approve_claims(
                evidence,
                reviews,
                approved_safe_claims=options["approved_safe_claims"],
                user_confirmations=options["user_confirmations"],
            )
            claim = result.claims[0]
            expected_claim = {key: value for key, value in expected.items() if key != "accepted"}
            assert _canonical(claim.model_dump(mode="json")) == _canonical(expected_claim)
            assert claim.approval_basis.value == expected["approval_basis"]
            assert claim.reviewer_decision_ids == expected["reviewer_decision_ids"]
            assert claim.approved_safe_claim == expected["approved_safe_claim"]
            assert claim.disclosure_decision.value == expected["disclosure_decision"]
            assert claim.disclosure_audience.value == expected["disclosure_audience"]
            assert claim.disclosure_purpose == expected["disclosure_purpose"]
        else:
            if "error_message" in expected:
                with pytest.raises(IRValidationError) as error:
                    approve_claims(
                        evidence,
                        reviews,
                        approved_safe_claims=options["approved_safe_claims"],
                        user_confirmations=options["user_confirmations"],
                    )
                assert str(error.value) == expected["error_message"]
            else:
                with pytest.raises(IRValidationError, match=expected["error_contains"]):
                    approve_claims(
                        evidence,
                        reviews,
                        approved_safe_claims=options["approved_safe_claims"],
                        user_confirmations=options["user_confirmations"],
                    )

    for case in kernel_cases["lock_cases"]:
        expected = case["expected"]
        locked = lock_approved_claims(case["approved_claims"], case["exact_final_claims"])
        assert expected["exact_accepted"] is True
        assert locked.claims[0].approved_safe_claim == case["exact_final_claims"]["claim.lock"]
        with pytest.raises(IRValidationError) as error:
            lock_approved_claims(case["approved_claims"], case["mutated_final_claims"])
        assert str(error.value) == expected["error_message"]

    for case in kernel_cases["provenance_cases"]:
        records = build_provenance(case["records"], case["visible_claim_ids"])
        assert _canonical([record.model_dump(mode="json") for record in records]) == _canonical(case["expected"]["records"])
    schema_cases = {
        case["case_id"]: case
        for case in _load(SCHEMA_CASES_PATH)["cases"]
        if "case_id" in case
    }
    for case in kernel_cases["closure_cases"]:
        approved = copy.deepcopy(schema_cases[case["approved_claim_case"]]["input"])
        evidence = copy.deepcopy(schema_cases[case["evidence_case"]]["input"])
        reviews = copy.deepcopy(schema_cases[case["review_case"]]["input"])
        if "origin_evidence_override" in case:
            approved["claims"][0]["origin_evidence_ids"] = [case["origin_evidence_override"]]
        result = check_provenance_closure(
            approved,
            evidence,
            reviews,
            case["visible_claim_ids"],
        )
        assert result == case["expected"]


def test_golden_policy_approval_provenance_variants_audit_render_io_contracts(
    golden_manifest: dict[str, Any],
) -> None:
    policies = {case["case_id"]: case for case in golden_manifest["policy_cases"]}
    assert policies["explicit-public"]["blocked"] is False
    assert policies["inherited-f6-p3"]["effective_fact_policy"] == "F6"
    assert policies["inherited-f6-p3"]["effective_disclosure_policy"] == "P3"
    assert policies["inherited-f6-p3"]["decision"] == "denied"
    assert policies["p2-without-confirmation"]["user_confirmation_required"] is True
    assert policies["fenced-example"]["blocked"] is True

    approvals = {case["case_id"]: case for case in golden_manifest["approval_cases"]}
    for case in approvals.values():
        assert case["locked"] is True
        if "mutation_rejected" in case:
            assert case["mutation_rejected"] is True
    assert approvals["extractive-mechanical"]["approval_basis"] == "mechanical"
    assert approvals["reviewed-semantic-independent"]["claim_mode"] == "reviewed-semantic"
    assert approvals["user-confirmed-p2"]["requires_confirmation"] is True

    provenance = {case["case_id"]: case for case in golden_manifest["provenance_cases"]}
    assert provenance["closed-provenance"]["expected"]["closed"] is True
    assert provenance["reviewed-closed-provenance"]["review_ids"] == ["review.evidence.queue"]
    assert provenance["missing-origin-rejected"]["expected"]["closed"] is False

    manifest = golden_manifest["variants"]["all"]
    assert [item["variant"] for item in manifest["variants"]] == [
        "recruiter-one-page",
        "technical-two-page",
        "extended-three-page",
    ]
    assert manifest["variants"][0]["artifacts"]["pdf"] == "resume-recruiter-1p.pdf"
    assert manifest["variants"][1]["artifacts"]["pdf"] == "resume-technical-2p.pdf"
    assert manifest["variants"][2]["artifacts"]["pdf"] == "technical-profile-3p.pdf"
    partial = golden_manifest["variants"]["partial-failure"]["expected"]
    assert partial == {"complete": False, "false_completion": False, "failed_variants": ["technical-two-page"]}


    audit = {case["case_id"]: case for case in golden_manifest["audit_cases"]}
    assert audit["clean-semantic-audit"]["success"] is True
    assert audit["unsupported-and-placeholder"]["success"] is False
    assert any("placeholder" in finding.casefold() for finding in audit["unsupported-and-placeholder"]["errors"])
    assert audit["provenance-gap"]["checks"]["all_visible_claims_provenance_closed"] is False

    html = golden_manifest["html_cases"][0]
    assert html["expected_text_order"] == [
        "Synthetic Candidate",
        "Platform Engineer",
        "Summary",
        "Skills",
        "Experience",
        "Projects",
        "Education",
        "Honors",
    ]
    assert html["forbidden_text"] == ["sources/record.md", "F6", "P3", "TOKEN-FICTIONAL"]
    pdf = {case["case_id"]: case for case in golden_manifest["pdf_cases"]}
    assert pdf["pdf-clean"]["success"] is True
    assert pdf["pdf-overflow-and-blank"]["overflow"] is True
    assert pdf["pdf-overflow-and-blank"]["blank_pages"] == [2]

    io_cases = {case["case_id"]: case for case in golden_manifest["io_cases"]}
    assert io_cases["private-modes"]["directory_mode"] == "0700"
    assert io_cases["private-modes"]["file_mode"] == "0600"
    assert io_cases["symlink-rejected"]["accepted"] is False
    assert io_cases["atomic-non-overwrite"]["existing_bytes_preserved"] is True
    assert io_cases["normalized-run-suffix"]["collision_free"] is True
def test_golden_variant_manifests_are_authoritative_schema_valid(
    golden_manifest: dict[str, Any],
) -> None:
    schema_path = GOLDEN_ROOT.parents[1] / "schemas" / "resume-variants.schema.json"
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    validator = Draft202012Validator(schema)
    validator.validate(golden_manifest["variants"]["all"])
    validator.validate(golden_manifest["variants"]["partial-failure"]["manifest"])


def test_golden_verification_matrix_has_explicit_backend_and_expected_outcome(
    golden_manifest: dict[str, Any],
) -> None:
    matrix = golden_manifest["verification_matrix"]
    required = {
        "known-adapter",
        "heterogeneous-agent-assisted",
        "extractive-claims",
        "reviewed-semantic",
        "unsupported-claim",
        "inherited-f6-p3",
        "fenced-example",
        "p2-confirmation",
        "stale-conflicting-jd",
        "all-variants",
        "partial-manifest-failure",
    }
    assert {case["case_id"] for case in matrix} == required
    for case in matrix:
        assert case["expected_backend"]
        assert case["expected"]


def test_golden_backend_matrix_preserves_explicit_python_specialists(
    golden_manifest: dict[str, Any],
) -> None:
    backend = golden_manifest["backend_matrix"]
    assert backend["schema-validation"] == "typescript"
    assert backend["normalization"] == "typescript"
    assert backend["secure-io"] == "typescript"
    assert backend["source-map-parser"] == "python"
    assert backend["role-input-validation"] == "python"
    assert backend["evidence-input-validation"] == "python"
    assert backend["policy-approval-provenance"] == "typescript"
    assert backend["composition"] == "python"
    assert backend["pdf-inspection"] == "python-pymupdf"
    assert backend["semantic-audit"] == "python"
