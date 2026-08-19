#!/usr/bin/env python3
"""Build a metadata-only source manifest outside the private source root."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from china_targeted_resume.adapters import MarkdownCareerV1Adapter


def _contained(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def write_manifest(source_root: Path, output: Path) -> None:
    root = source_root.expanduser().resolve(strict=True)
    destination = output.expanduser().resolve(strict=False)
    if _contained(destination, root):
        raise ValueError("source index output must be outside the source root")

    parent = destination.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_resolved = parent.resolve(strict=True)
    if _contained(parent_resolved, root):
        raise ValueError("source index parent must be outside the source root")
    os.chmod(parent_resolved, 0o700)

    manifest = MarkdownCareerV1Adapter(root).manifest
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=parent_resolved)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_descriptor = os.open(parent_resolved, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, help="Markdown career-source repository")
    parser.add_argument("output", type=Path, help="Destination JSON file outside source_root")
    arguments = parser.parse_args()
    write_manifest(arguments.source_root, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
