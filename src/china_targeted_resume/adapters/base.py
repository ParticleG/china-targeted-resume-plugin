"""Source adapter boundary for deterministic career-data access."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from china_targeted_resume.models import (
    CompanyRef,
    EvidenceCandidate,
    EvidenceRecord,
    Requirement,
    RoleRef,
    RoleRequest,
    SourceManifest,
    TargetContext,
)


@runtime_checkable
class CareerSourceAdapter(Protocol):
    """Read a career source without making its private contents persistent."""

    def discover(self, root: Path) -> SourceManifest: ...

    def list_companies(self) -> list[CompanyRef]: ...

    def load_company(self, company_ref: str | CompanyRef) -> dict[str, str]: ...

    def list_roles(self, company_ref: str | CompanyRef) -> list[RoleRef]: ...

    def resolve_role(self, request: RoleRequest) -> TargetContext: ...

    def load_policy(self) -> dict[str, Any]: ...

    def search_evidence(self, requirements: list[Requirement]) -> list[EvidenceCandidate]: ...

    def load_evidence(self, ref: EvidenceCandidate) -> EvidenceRecord: ...

    def verify_links(self, refs: list[Any]) -> list[dict[str, Any]]: ...
