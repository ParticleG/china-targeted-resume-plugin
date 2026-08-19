"""Explicit, one-way export of confirmed gaps to a growth roadmap."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from china_targeted_resume.models import Gap, GapSeverity, RoadmapHandoffItem, RoleMatchState


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _safe_file_part(value: str) -> str:
    part = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return part or "gap"


def _suggested_artifacts(gap: Gap) -> list[str]:
    artifacts = [
        "reproducible implementation artifact",
        "automated test or validation record",
        "technical design and verification report",
    ]
    context = f"{gap.job_impact} {gap.reason}".casefold()
    if re.search(r"(?:performance|latency|throughput|性能|延迟|吞吐)", context):
        artifacts.append("repeatable performance benchmark")
    if re.search(r"(?:deploy|rollback|kubernetes|部署|回滚|集群)", context):
        artifacts.append("deployment and rollback record")
    return artifacts


def export_roadmap_handoff(
    gaps: Sequence[Any],
    *,
    explicitly_requested: bool = False,
    severities: Sequence[str] = ("Critical", "Major"),
) -> list[RoadmapHandoffItem]:
    """Export confirmed, material gaps only after an explicit request.

    This is a one-way planning handoff. It copies the existing match state and
    baseline references; completing an item cannot update either evidence or match.
    """

    if not explicitly_requested:
        return []
    allowed: set[GapSeverity] = set()
    for value in severities:
        try:
            allowed.add(GapSeverity(_value(value)))
        except (TypeError, ValueError):
            continue
    result: list[RoadmapHandoffItem] = []
    for raw in gaps:
        try:
            gap = raw if isinstance(raw, Gap) else Gap.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if gap.match_state in {RoleMatchState.PENDING_CONFIRMATION, RoleMatchState.DIRECT_EVIDENCE}:
            continue
        if gap.severity is None or gap.severity not in allowed:
            continue
        description = f"{gap.reason} {gap.job_impact}".casefold()
        if gap.severity == GapSeverity.MINOR and ("preferred" in description or "加分" in description or "优先" in description):
            continue
        target_file = f"personal-data/personal-projects/{_safe_file_part(gap.gap_id)}.md"
        result.append(
            RoadmapHandoffItem(
                gap_id=gap.gap_id,
                requirement_id=gap.requirement_id,
                source_role_refs=[
                    f"role-dossier/gap-analysis.md#{_safe_file_part(gap.gap_id)}"
                ],
                match_state=gap.match_state,
                severity=gap.severity,
                priority_reason=f"{gap.severity.value} job impact: {gap.reason}",
                baseline_evidence_refs=list(gap.baseline_evidence_refs),
                target_capability=gap.job_impact,
                suggested_artifacts=_suggested_artifacts(gap),
                verification_signals=list(gap.validation_direction),
                target_owning_file=target_file,
            )
        )
    return result
