from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


_SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "resume-variants.schema.json"
)
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)

_VARIANTS = (
    ("recruiter-one-page", "resume-recruiter-1p", 1, 6),
    ("technical-two-page", "resume-technical-2p", 2, 12),
    ("extended-three-page", "technical-profile-3p", 3, 18),
)


def _variant_record(
    variant: str,
    base_name: str,
    pages: int,
    visible_claims: int,
) -> dict[str, Any]:
    return {
        "variant": variant,
        "base_name": base_name,
        "template": "ats-simple" if pages == 1 else "human-readable",
        "target_pages": pages,
        "actual_pages": pages,
        "underfilled": visible_claims < pages * 6,
        "visible_claims": visible_claims,
        "audit_success": True,
        "pdf_success": True,
        "artifacts": {
            "document": f"{base_name}.document.json",
            "provenance": f"{base_name}.provenance.json",
            "validation": f"{base_name}.validation.json",
            "audit": f"{base_name}.audit.md",
            "markdown": f"{base_name}.md",
            "ats_text": f"{base_name}.txt",
            "html": f"{base_name}.html",
            "pdf": f"{base_name}.pdf",
        },
        "previews": [
            f"{base_name}.preview.png",
            *(f"{base_name}.preview-{page}.png" for page in range(2, pages + 1)),
        ],
    }


def _manifest(*, extended: bool = True) -> dict[str, Any]:
    records = [_variant_record(*variant) for variant in _VARIANTS]
    return {
        "schema_version": 1,
        "variants": records if extended else records[:2],
    }


@pytest.mark.parametrize("extended", [False, True])
def test_resume_variants_schema_accepts_generated_manifest_shape(
    extended: bool,
) -> None:
    _VALIDATOR.validate(_manifest(extended=extended))


def test_resume_variants_schema_accepts_sparse_successful_variants() -> None:
    manifest = _manifest()
    for record in manifest["variants"][1:]:
        record["actual_pages"] = 1
        record["visible_claims"] = 5
        record["underfilled"] = True
        record["previews"] = record["previews"][:1]

    _VALIDATOR.validate(manifest)


def test_resume_variants_schema_accepts_retained_failed_page_count() -> None:
    manifest = _manifest(extended=False)
    technical = manifest["variants"][1]
    technical["actual_pages"] = 4
    technical["pdf_success"] = False
    technical["previews"].extend(
        [
            "resume-technical-2p.preview-3.png",
            "resume-technical-2p.preview-4.png",
        ]
    )

    _VALIDATOR.validate(manifest)


def test_resume_variants_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_SCHEMA)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.pop("schema_version"),
        lambda manifest: manifest.update({"schema_version": 2}),
        lambda manifest: manifest["variants"][0].pop("artifacts"),
        lambda manifest: manifest["variants"][0]["artifacts"].pop("pdf"),
        lambda manifest: manifest["variants"][0].update(
            {"variant": "unknown-variant"}
        ),
        lambda manifest: manifest["variants"][0].update({"template": "adaptive"}),
        lambda manifest: manifest["variants"][1].update({"actual_pages": 1}),
        lambda manifest: manifest["variants"][1].update({"target_pages": 1}),
        lambda manifest: manifest["variants"][1].update({"visible_claims": -1}),
        lambda manifest: manifest["variants"][1].update({"pdf_success": 1}),
        lambda manifest: manifest.update({"unexpected": True}),
        lambda manifest: manifest["variants"][0].update({"unexpected": True}),
        lambda manifest: manifest["variants"][0]["artifacts"].update(
            {"unexpected": "file.txt"}
        ),
        lambda manifest: manifest["variants"][0]["artifacts"].update(
            {"pdf": "../resume-recruiter-1p.pdf"}
        ),
        lambda manifest: manifest["variants"][1]["previews"].append(
            "resume-technical-2p.preview-3.png"
        ),
        lambda manifest: manifest["variants"][0]["artifacts"].update(
            {"pdf": "/tmp/resume-recruiter-1p.pdf"}
        ),
        lambda manifest: manifest["variants"][1]["previews"].__setitem__(
            1, "../resume-technical-2p.preview-2.png"
        ),
    ],
    ids=[
        "missing-top-level-key",
        "wrong-schema-version",
        "missing-record-key",
        "missing-artifact-key",
        "unknown-variant",
        "non-concrete-template",
        "wrong-actual-page-count",
        "wrong-target-page-count",
        "invalid-visible-claim-count",
        "invalid-success-flag",
        "extra-top-level-property",
        "extra-record-property",
        "extra-artifact-property",
        "traversal-artifact-name",
        "mismatched-preview-count",
        "absolute-artifact-name",
        "traversal-preview-name",
    ],
)
def test_resume_variants_schema_rejects_invalid_manifests(mutate: Any) -> None:
    manifest = copy.deepcopy(_manifest())
    mutate(manifest)

    with pytest.raises(ValidationError):
        _VALIDATOR.validate(manifest)


def test_resume_variants_schema_rejects_inconsistent_underfilled_flag() -> None:
    manifest = _manifest()
    manifest["variants"][1]["visible_claims"] = 11
    manifest["variants"][1]["underfilled"] = False

    with pytest.raises(ValidationError):
        _VALIDATOR.validate(manifest)
