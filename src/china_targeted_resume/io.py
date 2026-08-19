"""Secure, atomic run artifact I/O."""
from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import unicodedata


class OutputBoundaryError(ValueError):
    """Raised when an output would overlap the read-only source."""


def slug(value: str | None, *, fallback: str = "target") -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    result = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if result:
        return result[:64].rstrip("-")
    if value:
        return f"{fallback}-{sha256(value.encode('utf-8')).hexdigest()[:10]}"
    return fallback


def validate_output_root(source_root: str | Path, output_root: str | Path) -> tuple[Path, Path]:
    source = Path(source_root).expanduser().resolve(strict=True)
    output = Path(output_root).expanduser().resolve(strict=False)
    if output == source or output.is_relative_to(source):
        raise OutputBoundaryError("output root must be outside the source root")
    return source, output


def secure_directory(path: str | Path, *, exist_ok: bool = True) -> Path:
    target = Path(path)
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=exist_ok, mode=0o700)
    if target.is_symlink():
        raise OutputBoundaryError(f"directory must not be a symlink: {target}")
    resolved = target.resolve(strict=True)
    if not resolved.is_dir():
        raise OutputBoundaryError(f"not a directory: {resolved}")
    if existed and resolved.stat().st_mode & 0o077:
        raise OutputBoundaryError(f"directory permissions must be 0700 or stricter: {resolved}")
    os.chmod(resolved, 0o700)
    return resolved


def create_run_directory(output_root: Path, company: str | None, role: str | None) -> Path:
    existed = output_root.exists()
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_root.is_symlink():
        raise OutputBoundaryError(f"output root must not be a symlink: {output_root}")
    root = output_root.resolve(strict=True)
    if not root.is_dir():
        raise OutputBoundaryError(f"output root is not a directory: {root}")
    if not existed:
        os.chmod(root, 0o700)
    prefix = f"{slug(company, fallback='company')}--{slug(role, fallback='role')}"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for sequence in range(1000):
        suffix = "" if sequence == 0 else f"-{sequence:03d}"
        candidate = root / f"{prefix}--{timestamp}{suffix}"
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            continue
        os.chmod(candidate, 0o700)
        return candidate.resolve(strict=True)
    raise FileExistsError("could not allocate a non-overwriting run directory")


def _atomic_write(path: Path, data: bytes) -> Path:
    parent = secure_directory(path.parent)
    destination = parent / path.name
    if destination.exists() and destination.is_symlink():
        raise OutputBoundaryError(f"refusing to write through symlink: {destination}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


def write_text(path: str | Path, text: str) -> Path:
    return _atomic_write(Path(path), text.encode("utf-8"))


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def write_json(path: str | Path, value: Any) -> Path:
    payload = json.dumps(jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return write_text(path, payload)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
