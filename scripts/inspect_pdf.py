#!/usr/bin/env python3
"""Inspect a local PDF using a JSON configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from china_targeted_resume.rendering.inspect import InspectionConfig, inspect_pdf


def _load(path: str | None) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def main() -> int:
    try:
        payload = _load(sys.argv[1] if len(sys.argv) > 1 else None)
        report = inspect_pdf(payload["pdf_path"], InspectionConfig.from_mapping(payload.get("inspection", {})))
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if report.success else 2
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
