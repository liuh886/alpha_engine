from __future__ import annotations

import hashlib
import json

from src.artifacts.pages_release_verification import (
    PublishedFormalRun,
    PublishedSection,
    validate_formal_section,
)


def test_native_formal_summary_does_not_require_source_package_hash() -> None:
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": "us_ranker",
        "model_version_id": "us_x1_2",
        "run_id": "us_x1_2-through-2026_08_10",
        "display_name": "US x1.2",
        "research_only": True,
        "trade_ready": False,
        "metrics": [],
    }
    payload = (json.dumps(summary, separators=(",", ":"), sort_keys=True) + "\n").encode()
    record = PublishedFormalRun(
        model_family_id="us_ranker",
        model_version_id="us_x1_2",
        run_id="us_x1_2-through-2026_08_10",
        bundle_id="a" * 64,
        manifest_path="us_ranker/us_x1_2/us_x1_2-through-2026_08_10/manifest.json",
        manifest_sha256="b" * 64,
        evidence_cutoff="2026-08-10",
    )
    section = PublishedSection(
        section_id="summary",
        path="summary.json",
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    validate_formal_section(record, section, payload)
