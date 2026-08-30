from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator
import pytest

from china_targeted_resume.growth_roadmap import write_growth_roadmap


SCHEMA = json.loads(
    (
        Path(__file__).parents[1]
        / "schemas"
        / "growth-roadmap.schema.json"
    ).read_text(encoding="utf-8")
)


def _write_private(path: Path, value: object) -> bytes:
    raw = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    path.chmod(0o600)
    return raw


def _handoff() -> list[dict[str, object]]:
    return [
        {
            "schema_version": 1,
            "gap_id": "gap-kubernetes-operations",
            "requirement_id": "REQ-K8S",
            "source_role_refs": [
                "role-dossier/gap-analysis.md#gap-kubernetes-operations"
            ],
            "match_state": "有知识无实践",
            "severity": "Major",
            "priority_reason": "Major role impact: production operations evidence is absent.",
            "baseline_evidence_refs": ["ev-k8s-study"],
            "target_capability": "Operate and troubleshoot Kubernetes workloads",
            "prerequisite_gap_ids": [],
            "suggested_artifacts": ["deployment and rollback record"],
            "verification_signals": ["repeatable failure and recovery exercise"],
            "target_owning_file": "personal-data/personal-projects/gap-kubernetes-operations.md",
        }
    ]


def _stages() -> list[dict[str, object]]:
    return [
        {
            "stage": stage,
            "objective": f"Complete the {stage} boundary for Kubernetes operations.",
            "prerequisite_gap_ids": [],
            "work_items": [f"Execute the {stage} work item in a local cluster."],
            "expected_artifacts": [f"{stage} evidence artifact"],
            "pass_criteria": [f"The {stage} artifact is reproducible."],
            "effort_hours_min": 1,
            "effort_hours_max": 2,
            "failure_retry": f"Record the {stage} failure and repeat after correction.",
        }
        for stage in (
            "baseline",
            "learn",
            "practice",
            "verify",
            "record",
            "refresh",
        )
    ]


def _plan(handoff_raw: bytes) -> dict[str, object]:
    return {
        "schema_version": 1,
        "created_at": "2026-08-30T00:00:00Z",
        "source_handoff_sha256": f"sha256:{sha256(handoff_raw).hexdigest()}",
        "planning_constraints": {
            "deadline": "2026-10-01",
            "hours_per_week": 8,
            "available_environment": ["local Linux workstation"],
            "preferred_language": "zh-CN",
            "budget_cny": 0,
        },
        "plans": [
            {
                "gap_id": "gap-kubernetes-operations",
                "requirement_id": "REQ-K8S",
                "source_role_refs": [
                    "role-dossier/gap-analysis.md#gap-kubernetes-operations"
                ],
                "match_state": "有知识无实践",
                "severity": "Major",
                "priority_reason": "Major role impact: production operations evidence is absent.",
                "target_capability": "Operate and troubleshoot Kubernetes workloads",
                "prerequisite_gap_ids": [],
                "baseline_evidence_refs": ["ev-k8s-study"],
                "suggested_artifacts": ["deployment and rollback record"],
                "verification_signals": ["repeatable failure and recovery exercise"],
                "target_owning_file": "personal-data/personal-projects/gap-kubernetes-operations.md",
                "stages": _stages(),
                "resources": [
                    {
                        "title": "Kubernetes Basics",
                        "publisher": "Kubernetes Authors",
                        "url": "https://kubernetes.io/docs/tutorials/kubernetes-basics/",
                        "accessed_at": "2026-08-30",
                        "stage": "learn",
                        "source_authority": "official_tutorial",
                        "relevance": "Covers deployment, scaling, update, and debugging fundamentals used by the practice stages.",
                    }
                ],
                "completion_does_not_change_match_state": True,
            }
        ],
        "post_completion_action": "verify the real artifact, update the owning source with user approval, then run refresh-match",
    }


def test_growth_roadmap_write_is_schema_valid_private_atomic_and_non_overwriting(
    tmp_path,
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    handoff_path = tmp_path / "roadmap-handoff.json"
    handoff_raw = _write_private(handoff_path, _handoff())
    plan_path = tmp_path / "plan.json"
    _write_private(plan_path, _plan(handoff_raw))
    output = tmp_path / "output"

    first = write_growth_roadmap(
        source_root=source,
        handoff_path=handoff_path,
        plan_path=plan_path,
        output_root=output,
    )
    second = write_growth_roadmap(
        source_root=source,
        handoff_path=handoff_path,
        plan_path=plan_path,
        output_root=output,
    )

    first_run = Path(first["run_dir"])
    second_run = Path(second["run_dir"])
    assert first_run != second_run
    assert stat.S_IMODE(first_run.stat().st_mode) == 0o700
    assert stat.S_IMODE(second_run.stat().st_mode) == 0o700
    roadmap = json.loads(
        (first_run / "growth-roadmap.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(SCHEMA).validate(roadmap)
    assert roadmap["plans"][0]["resources"]
    assert roadmap["plans"][0]["stages"]
    assert "Kubernetes Basics" in (
        first_run / "growth-roadmap.md"
    ).read_text(encoding="utf-8")
    validation = json.loads(
        (first_run / "growth-roadmap.validation.json").read_text(
            encoding="utf-8"
        )
    )
    assert validation["success"] is True
    assert validation["plan_count"] == 1
    markdown = (
        first_run / "growth-roadmap.md"
    ).read_text(encoding="utf-8")
    assert "Major role impact: production operations evidence is absent." in markdown
    assert "Suggested artifact: deployment and rollback record" in markdown
    assert "Verification signal: repeatable failure and recovery exercise" in markdown
    assert validation["stage_count"] == 6
    assert validation["resource_count"] == 1
    for run in (first_run, second_run):
        assert all(
            stat.S_IMODE(path.stat().st_mode) == 0o600
            for path in run.iterdir()
            if path.is_file()
        )



@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("priority_reason", "Different priority"),
        ("suggested_artifacts", []),
        ("verification_signals", []),
    ],
)
def test_growth_roadmap_rejects_lossy_handoff_fields(
    tmp_path,
    field,
    replacement,
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    handoff_path = tmp_path / "roadmap-handoff.json"
    handoff_raw = _write_private(handoff_path, _handoff())
    plan = _plan(handoff_raw)
    plan["plans"][0][field] = replacement
    plan_path = tmp_path / "plan.json"
    _write_private(plan_path, plan)

    with pytest.raises(ValueError, match="does not preserve"):
        write_growth_roadmap(
            source_root=source,
            handoff_path=handoff_path,
            plan_path=plan_path,
            output_root=tmp_path / "output",
        )

def test_growth_roadmap_rejects_handoff_mismatch_hash_and_permissive_input(
    tmp_path,
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    handoff_path = tmp_path / "roadmap-handoff.json"
    handoff_raw = _write_private(handoff_path, _handoff())
    plan = _plan(handoff_raw)
    plan["plans"][0]["target_capability"] = "Different capability"
    plan_path = tmp_path / "plan.json"
    _write_private(plan_path, plan)

    with pytest.raises(ValueError, match="does not preserve"):
        write_growth_roadmap(
            source_root=source,
            handoff_path=handoff_path,
            plan_path=plan_path,
            output_root=tmp_path / "output-a",
        )

    plan = _plan(handoff_raw)
    plan["source_handoff_sha256"] = f"sha256:{'0' * 64}"
    _write_private(plan_path, plan)
    with pytest.raises(ValueError, match="does not match handoff bytes"):
        write_growth_roadmap(
            source_root=source,
            handoff_path=handoff_path,
            plan_path=plan_path,
            output_root=tmp_path / "output-b",
        )

    _write_private(plan_path, _plan(handoff_raw))
    os.chmod(plan_path, 0o644)
    with pytest.raises(ValueError, match="permissions"):
        write_growth_roadmap(
            source_root=source,
            handoff_path=handoff_path,
            plan_path=plan_path,
            output_root=tmp_path / "output-c",
        )
