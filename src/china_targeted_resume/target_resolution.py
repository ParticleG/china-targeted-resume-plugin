"""Deterministic target identity and source-tier resolution."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import RoleRequest, TargetContext

TARGET_BASES = {
    "A": "exact-current-jd",
    "B": "exact-role-partial-evidence",
    "C": "company-role-family",
    "D": "insufficient-target",
}


def _dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python", exclude_none=False)
    return dict(value)


def _make_context(data: dict[str, Any]) -> TargetContext:
    fields = TargetContext.model_fields
    aliases = {field.alias: name for name, field in fields.items() if field.alias}
    selected: dict[str, Any] = {}
    for key, value in data.items():
        target = key if key in fields else aliases.get(key)
        if target is not None:
            selected[target] = value
    return TargetContext.model_validate(selected)


def _read_bounded(path: str | Path, roots: Iterable[str | Path]) -> str:
    resolved = Path(path).expanduser().resolve(strict=True)
    allowed = [Path(root).expanduser().resolve(strict=True) for root in roots]
    if not allowed:
        raise ValueError("allowed_source_roots is required for JD file input")
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise ValueError(f"JD file is outside allowed source roots: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"JD path is not a regular file: {resolved}")
    return resolved.read_text(encoding="utf-8")


def _read_allowed_url(
    url: str,
    *,
    allowed_url_hosts: Iterable[str],
    url_loader: Callable[[str], str] | None,
) -> str:
    parsed = urlparse(url)
    hosts = {host.casefold() for host in allowed_url_hosts}
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() not in hosts:
        raise ValueError("JD URL must be HTTPS and its exact host must be allowlisted")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("JD URL credentials and nonstandard ports are not allowed")
    if url_loader is None:
        raise ValueError("an explicit url_loader is required for allowed URL input")
    text = url_loader(url)
    if not isinstance(text, str):
        raise TypeError("url_loader must return text")
    return text


def resolve_target(
    request: RoleRequest | Mapping[str, Any],
    *,
    jd_text: str | None = None,
    jd_file: str | Path | None = None,
    jd_url: str | None = None,
    allowed_source_roots: Iterable[str | Path] = (),
    allowed_url_hosts: Iterable[str] = (),
    url_loader: Callable[[str], str] | None = None,
    partial_dossier: str | Mapping[str, Any] | None = None,
    hiring_evidence: Iterable[str | Mapping[str, Any]] = (),
    jd_complete: bool | None = None,
    source_date: date | str | None = None,
) -> TargetContext:
    """Resolve target bases A-D without inventing missing target detail.

    Tier B intentionally remains analyzable, but carries ``coverage=None`` and
    explicit limitations/staleness. Tier selection is based on source identity
    and declared completeness, never a fixed percentage threshold.
    """
    values = _dump(request)
    request_jd = values.get("jd") or {}
    if hasattr(request_jd, "model_dump"):
        request_jd = request_jd.model_dump(mode="python", exclude_none=False)
    jd_text = jd_text if jd_text is not None else request_jd.get("text")
    jd_file = jd_file if jd_file is not None else request_jd.get("file")
    request_url = request_jd.get("url")
    jd_url = jd_url if jd_url is not None else (str(request_url) if request_url else None)
    provided = sum(value is not None for value in (jd_text, jd_file, jd_url))
    if provided > 1:
        raise ValueError("provide only one current JD source")
    source_kind: str | None = None
    current_jd: str | None = None
    if jd_text is not None:
        current_jd, source_kind = jd_text, "inline-current-jd"
    elif jd_file is not None:
        current_jd = _read_bounded(jd_file, allowed_source_roots)
        source_kind = "file-current-jd"
    elif jd_url is not None:
        current_jd = _read_allowed_url(
            jd_url, allowed_url_hosts=allowed_url_hosts, url_loader=url_loader
        )
        source_kind = "url-current-jd"

    company_ref = values.get("company_ref")
    role_ref = values.get("role_ref")
    company_record = _dump(company_ref) if company_ref is not None else {}
    role_record = _dump(role_ref) if role_ref is not None else {}
    company = (
        company_record.get("display_name")
        or values.get("company")
        or values.get("company_name")
    )
    role = (
        role_record.get("title")
        or values.get("role")
        or values.get("role_name")
        or values.get("title")
    )
    role_family = role_record.get("role_family") or values.get("role_family") or values.get("family")
    exact_role = bool(role_ref and company_ref) or bool(company and role)
    has_partial = partial_dossier is not None or any(True for _ in hiring_evidence)
    declared_complete = bool(current_jd and current_jd.strip()) if jd_complete is None else jd_complete
    limitations: list[str] = []
    stale = False

    if current_jd and current_jd.strip() and declared_complete:
        tier = "A"
    elif exact_role and (has_partial or (current_jd and current_jd.strip())):
        tier = "B"
        limitations.append("Current complete JD is unavailable; coverage is indeterminate.")
        if partial_dossier is not None:
            limitations.append("Partial or historical dossier may not reflect the current opening.")
            stale = True
        if current_jd:
            limitations.append("Available JD text was explicitly marked incomplete.")
    elif company and role_family:
        tier = "C"
        limitations.append("Only company and role-family expectations are established.")
    else:
        tier = "D"
        limitations.append("Target identity is insufficient for role-specific conclusions.")

    digest = f"sha256:{sha256(current_jd.encode('utf-8')).hexdigest()}" if current_jd else None
    base = TARGET_BASES[tier]
    return _make_context({
        "target_basis": base,
        "company": company,
        "role": role,
        "company_ref": company_ref
            if hasattr(company_ref, "model_dump")
            or isinstance(company_ref, Mapping) else None,
        "role_ref": role_ref
            if hasattr(role_ref, "model_dump")
            or isinstance(role_ref, Mapping) else None,
        "jd_completeness": (
            "complete" if tier == "A"
            else "stale" if stale
            else "partial" if current_jd or has_partial
            else "unavailable"
        ),
        "jd_source_date": source_date,
        "explicit_requirement_coverage": None,
        "evidence_coverage_summary": (
            "Coverage is intentionally not asserted from partial or stale sources."
            if tier == "B" else None
        ),
        "staleness_risk": "high" if stale else ("unknown" if tier != "A" else "none"),
        "limitations": limitations,
        "source_refs": [
            f"{source_kind}:{digest}" if source_kind and digest else source_kind
        ] if source_kind else [],
    })


def resolve_role(*, request: RoleRequest, adapter: Any) -> TargetContext:
    """Resolve adapter references, then apply the same deterministic tier rules."""
    company_ref = request.company_ref
    role_ref = request.role_ref
    if company_ref is not None and isinstance(company_ref, str):
        list_companies = getattr(adapter, "list_companies", None)
        if list_companies is not None:
            company_ref = next(
                (item for item in list_companies() if item.company_id == company_ref),
                company_ref,
            )
    if role_ref is not None and isinstance(role_ref, str) and company_ref is not None:
        role_ref = next(
            (item for item in adapter.list_roles(company_ref) if item.role_id == role_ref),
            role_ref,
        )
    normalized = RoleRequest(
        company_ref=company_ref,
        role_ref=role_ref,
        jd=request.jd,
    )
    source_refs = getattr(role_ref, "source_refs", []) if role_ref is not None else []
    root = getattr(adapter, "root", None)
    return resolve_target(
        normalized,
        allowed_source_roots=(root,) if root is not None else (),
        partial_dossier={"source_refs": list(source_refs)} if source_refs else None,
    )


resolve_target_context = resolve_target
