#!/usr/bin/env python3
"""Validate resume provenance and deterministic evidence policy gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from china_targeted_resume.models import (
    EvidenceRecord,
    OutputMode,
    ProvenanceRecord,
    ResumeDocument,
    ValidationReport,
)
from china_targeted_resume.policy import apply_evidence_policy, detect_sensitive_content


def _load(path: str | None) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def _validate(payload: dict[str, Any]) -> ValidationReport:
    mode = OutputMode(payload["mode"])
    evidence = [EvidenceRecord.model_validate(item) for item in payload.get("evidence_records", [])]
    provenance = [ProvenanceRecord.model_validate(item) for item in payload.get("provenance_records", [])]
    document = ResumeDocument.model_validate(payload["document"])
    checks: dict[str, bool] = {}
    errors: list[str] = []

    evidence_by_id = {record.evidence_id: record for record in evidence}
    provenance_by_id = {record.claim_id: record for record in provenance}
    checks["unique_evidence_ids"] = len(evidence_by_id) == len(evidence)
    checks["unique_claim_ids"] = len(provenance_by_id) == len(provenance)
    if not checks["unique_evidence_ids"]:
        errors.append("evidence IDs are not unique")
    if not checks["unique_claim_ids"]:
        errors.append("provenance claim IDs are not unique")

    rejected_candidates: dict[str, list[str]] = {}
    for record in evidence:
        decision = apply_evidence_policy(record, mode)
        if not decision.allowed_as_candidate:
            rejected_candidates[record.evidence_id] = list(decision.reason_codes)
    checks["ingestion_policy"] = not rejected_candidates
    if rejected_candidates:
        errors.append("one or more evidence records are excluded from processing")

    missing_evidence: dict[str, list[str]] = {}
    blocked_evidence: dict[str, list[str]] = {}
    wrong_modes: list[str] = []
    mismatched_policy_metadata: list[str] = []
    sensitive_claims: list[str] = []
    for record in provenance:
        if record.output_mode != mode:
            wrong_modes.append(record.claim_id)
        for evidence_id in record.evidence_ids:
            evidence_record = evidence_by_id.get(evidence_id)
            if evidence_record is None:
                missing_evidence.setdefault(record.claim_id, []).append(evidence_id)
                continue
            decision = apply_evidence_policy(evidence_record, mode)
            if not decision.allowed_in_output:
                blocked_evidence.setdefault(record.claim_id, []).extend(decision.reason_codes)
            if evidence_record.fact_state != record.fact_state or evidence_record.disclosure != record.disclosure:
                mismatched_policy_metadata.append(record.claim_id)
        if detect_sensitive_content(record.rendered_claim):
            sensitive_claims.append(record.claim_id)
    checks["provenance_evidence_exists"] = not missing_evidence
    checks["final_output_policy"] = not blocked_evidence
    checks["provenance_mode"] = not wrong_modes
    checks["provenance_policy_metadata"] = not mismatched_policy_metadata
    checks["rendered_claim_disclosure"] = not sensitive_claims
    if missing_evidence:
        errors.append("provenance references unknown evidence IDs")
    if blocked_evidence:
        errors.append("rendered claims reference evidence blocked by final-output policy")
    if wrong_modes:
        errors.append("provenance output mode does not match requested mode")
    if mismatched_policy_metadata:
        errors.append("provenance policy metadata does not match its evidence")
    if sensitive_claims:
        errors.append("one or more rendered provenance claims contain excluded sensitive content")

    rendered_claim_ids: list[str] = []
    for item in (*document.experience, *document.projects):
        for bullet in item.bullets:
            rendered_claim_ids.extend(bullet.claim_ids)
    rendered_set = set(rendered_claim_ids)
    checks["rendered_claims_have_provenance"] = rendered_set.issubset(provenance_by_id)
    checks["document_provenance_present"] = not rendered_set or bool(document.provenance_refs)
    if not checks["rendered_claims_have_provenance"]:
        errors.append("one or more rendered bullet claims lack provenance")
    if not checks["document_provenance_present"]:
        errors.append("rendered content has no document provenance ledger references")

    return ValidationReport(
        success=not errors,
        checks=checks,
        errors=errors,
        details={
            "blocked_claim_ids": sorted(blocked_evidence),
            "missing_evidence_claim_ids": sorted(missing_evidence),
            "rejected_evidence_ids": sorted(rejected_candidates),
            "wrong_mode_claim_ids": sorted(wrong_modes),
            "metadata_mismatch_claim_ids": sorted(set(mismatched_policy_metadata)),
            "sensitive_claim_ids": sorted(set(sensitive_claims)),
        },
    )


def main() -> int:
    try:
        report = _validate(_load(sys.argv[1] if len(sys.argv) > 1 else None))
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if report.success else 2
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
