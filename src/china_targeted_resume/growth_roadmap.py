"""Validated, private, non-overwriting growth-roadmap artifacts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from .io import (
    create_run_directory,
    validate_output_root,
    write_json,
    write_text,
)
from .models import (
    CanonicalModel,
    GapSeverity,
    RoadmapHandoffItem,
    RoleMatchState,
)

_MAX_INPUT_BYTES = 1024 * 1024
_STAGE_ORDER = ("baseline", "learn", "practice", "verify", "record", "refresh")
_POST_COMPLETION_ACTION = (
    "verify the real artifact, update the owning source with user approval, "
    "then run refresh-match"
)


class GrowthPlanningConstraints(CanonicalModel):
    deadline: date | None = None
    hours_per_week: float = Field(gt=0, le=168)
    available_environment: list[str] = Field(min_length=1)
    preferred_language: str = Field(min_length=1)
    budget_cny: float | None = Field(default=None, ge=0)


class GrowthRoadmapResource(CanonicalModel):
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    url: HttpUrl
    accessed_at: date
    stage: Literal["learn", "practice", "verify"]
    source_authority: Literal[
        "official_documentation",
        "official_tutorial",
        "standard",
        "maintainer_guide",
        "reputable_course_provider",
    ]
    relevance: str = Field(min_length=1)

    @model_validator(mode="after")
    def https_only(self) -> GrowthRoadmapResource:
        if self.url.scheme != "https":
            raise ValueError("growth roadmap resources must use HTTPS")
        return self


class GrowthRoadmapStage(CanonicalModel):
    stage: Literal["baseline", "learn", "practice", "verify", "record", "refresh"]
    objective: str = Field(min_length=1)
    prerequisite_gap_ids: list[str] = Field(default_factory=list)
    work_items: list[str] = Field(min_length=1)
    expected_artifacts: list[str] = Field(min_length=1)
    pass_criteria: list[str] = Field(min_length=1)
    effort_hours_min: float = Field(gt=0)
    effort_hours_max: float = Field(gt=0)
    failure_retry: str = Field(min_length=1)

    @model_validator(mode="after")
    def effort_is_ordered(self) -> GrowthRoadmapStage:
        if self.effort_hours_max < self.effort_hours_min:
            raise ValueError("effort_hours_max must not be less than effort_hours_min")
        return self


class GrowthRoadmapPlan(CanonicalModel):
    gap_id: str = Field(min_length=1)
    requirement_id: str | None = None
    source_role_refs: list[str] = Field(default_factory=list)
    match_state: RoleMatchState
    severity: GapSeverity
    priority_reason: str = Field(min_length=1)
    target_capability: str = Field(min_length=1)
    prerequisite_gap_ids: list[str] = Field(default_factory=list)
    baseline_evidence_refs: list[str] = Field(default_factory=list)
    suggested_artifacts: list[str] = Field(default_factory=list)
    verification_signals: list[str] = Field(default_factory=list)
    target_owning_file: str = Field(min_length=1)
    stages: list[GrowthRoadmapStage] = Field(min_length=6, max_length=6)
    resources: list[GrowthRoadmapResource] = Field(min_length=1)
    completion_does_not_change_match_state: Literal[True] = True

    @model_validator(mode="after")
    def stage_and_owner_contract(self) -> GrowthRoadmapPlan:
        if tuple(stage.stage for stage in self.stages) != _STAGE_ORDER:
            raise ValueError(
                "growth roadmap stages must be baseline, learn, practice, verify, record, refresh"
            )
        owner = PurePosixPath(self.target_owning_file.replace("\\", "/"))
        if owner.is_absolute() or ".." in owner.parts or not owner.parts:
            raise ValueError("target_owning_file must be a safe relative path")
        return self


class GrowthRoadmapDocument(CanonicalModel):
    schema_version: Literal[1] = 1
    created_at: datetime
    source_handoff_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    planning_constraints: GrowthPlanningConstraints
    plans: list[GrowthRoadmapPlan] = Field(min_length=1)
    post_completion_action: Literal[
        "verify the real artifact, update the owning source with user approval, then run refresh-match"
    ] = _POST_COMPLETION_ACTION

    @model_validator(mode="after")
    def unique_gap_plans(self) -> GrowthRoadmapDocument:
        gap_ids = [plan.gap_id for plan in self.plans]
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("growth roadmap must contain one plan per gap_id")
        known = set(gap_ids)
        for plan in self.plans:
            if not set(plan.prerequisite_gap_ids) <= known:
                raise ValueError("plan prerequisite_gap_ids must reference planned gaps")
            for stage in plan.stages:
                if not set(stage.prerequisite_gap_ids) <= known:
                    raise ValueError("stage prerequisite_gap_ids must reference planned gaps")
        return self


def _read_private_json(path: str | Path, label: str) -> tuple[object, bytes, Path]:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = candidate.resolve(strict=True)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"{label} permissions must be 0600 or stricter")
    getuid = getattr(os, "getuid", None)
    if getuid is not None and metadata.st_uid != getuid():
        raise ValueError(f"{label} owner must be the current user")
    if metadata.st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds the 1 MiB limit")
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be UTF-8 JSON") from error
    return value, raw, resolved


def _handoff_digest(raw: bytes) -> str:
    return f"sha256:{sha256(raw).hexdigest()}"


def validate_growth_roadmap(
    handoff_value: object,
    handoff_raw: bytes,
    plan_value: object,
) -> tuple[list[RoadmapHandoffItem], GrowthRoadmapDocument, dict[str, object]]:
    if not isinstance(handoff_value, list) or not handoff_value:
        raise ValueError("roadmap handoff must be a non-empty JSON array")
    handoff = [RoadmapHandoffItem.model_validate(item) for item in handoff_value]
    plan = GrowthRoadmapDocument.model_validate(plan_value)
    digest = _handoff_digest(handoff_raw)
    if plan.source_handoff_sha256 != digest:
        raise ValueError("growth roadmap source_handoff_sha256 does not match handoff bytes")
    handoff_by_gap = {item.gap_id: item for item in handoff}
    plan_by_gap = {item.gap_id: item for item in plan.plans}
    if set(plan_by_gap) != set(handoff_by_gap):
        raise ValueError("growth roadmap must plan every handoff gap exactly once")
    for gap_id, item in handoff_by_gap.items():
        candidate = plan_by_gap[gap_id]
        expected = {
            "requirement_id": item.requirement_id,
            "source_role_refs": item.source_role_refs,
            "match_state": item.match_state,
            "severity": item.severity,
            "priority_reason": item.priority_reason,
            "target_capability": item.target_capability,
            "prerequisite_gap_ids": item.prerequisite_gap_ids,
            "baseline_evidence_refs": item.baseline_evidence_refs,
            "suggested_artifacts": item.suggested_artifacts,
            "verification_signals": item.verification_signals,
            "target_owning_file": item.target_owning_file,
        }
        actual = {
            key: getattr(candidate, key)
            for key in expected
        }
        if actual != expected:
            raise ValueError(
                f"growth roadmap plan {gap_id} does not preserve the validated handoff"
            )
    receipt = {
        "schema_version": 1,
        "success": True,
        "checked_at": datetime.now(UTC),
        "source_handoff_sha256": digest,
        "gap_ids": sorted(handoff_by_gap),
        "plan_count": len(plan.plans),
        "stage_count": sum(len(item.stages) for item in plan.plans),
        "resource_count": sum(len(item.resources) for item in plan.plans),
    }
    return handoff, plan, receipt


def render_growth_roadmap_markdown(plan: GrowthRoadmapDocument) -> str:
    lines = [
        "# Growth roadmap",
        "",
        f"- Created: {plan.created_at.isoformat()}",
        f"- Source handoff: `{plan.source_handoff_sha256}`",
        f"- Hours per week: {plan.planning_constraints.hours_per_week:g}",
        f"- Preferred language: {plan.planning_constraints.preferred_language}",
        "- Completion changes match state: no",
        "",
    ]
    for item in plan.plans:
        lines.extend(
            [
                f"## {item.gap_id}: {item.target_capability}",
                "",
                f"- Match state: `{item.match_state.value}`",
                f"- Severity: `{item.severity.value}`",
                f"- Priority reason: {item.priority_reason}",
                f"- Intended owner: `{item.target_owning_file}`",
                "",
                "### Handoff artifact and verification contract",
                "",
                *(
                    [f"- Suggested artifact: {value}" for value in item.suggested_artifacts]
                    or ["- Suggested artifact: none"]
                ),
                *(
                    [f"- Verification signal: {value}" for value in item.verification_signals]
                    or ["- Verification signal: none"]
                ),
                "",
                "### Stages",
                "",
            ]
        )
        for stage in item.stages:
            lines.extend(
                [
                    f"#### {stage.stage}",
                    "",
                    f"- Objective: {stage.objective}",
                    f"- Effort: {stage.effort_hours_min:g}–{stage.effort_hours_max:g} hours",
                    *[f"- Work: {value}" for value in stage.work_items],
                    *[f"- Artifact: {value}" for value in stage.expected_artifacts],
                    *[f"- Pass: {value}" for value in stage.pass_criteria],
                    f"- Retry: {stage.failure_retry}",
                    "",
                ]
            )
        lines.extend(["### Learning resources", ""])
        for resource in item.resources:
            lines.append(
                f"- [{resource.title}]({resource.url}) — {resource.publisher}; "
                f"stage `{resource.stage}`; accessed {resource.accessed_at.isoformat()}; "
                f"{resource.relevance}"
            )
        lines.append("")
    lines.extend(["## Post-completion boundary", "", plan.post_completion_action, ""])
    return "\n".join(lines)


def write_growth_roadmap(
    *,
    source_root: str | Path,
    handoff_path: str | Path,
    plan_path: str | Path,
    output_root: str | Path,
) -> dict[str, object]:
    _, destination_root = validate_output_root(source_root, output_root)
    handoff_value, handoff_raw, _ = _read_private_json(
        handoff_path,
        "roadmap handoff",
    )
    plan_value, _, _ = _read_private_json(plan_path, "growth roadmap plan")
    _, plan, receipt = validate_growth_roadmap(
        handoff_value,
        handoff_raw,
        plan_value,
    )
    run_dir = create_run_directory(
        destination_root,
        "growth-roadmap",
        "capability-plan",
    )
    roadmap_json = write_json(run_dir / "growth-roadmap.json", plan)
    roadmap_markdown = write_text(
        run_dir / "growth-roadmap.md",
        render_growth_roadmap_markdown(plan),
    )
    validation_json = write_json(
        run_dir / "growth-roadmap.validation.json",
        receipt,
    )
    artifacts = [roadmap_json, roadmap_markdown, validation_json]
    return {
        "operation": "write-growth-roadmap",
        "run_dir": str(run_dir),
        "artifacts": [str(path) for path in artifacts],
        "summary": receipt,
    }
