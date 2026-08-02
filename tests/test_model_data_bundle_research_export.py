from __future__ import annotations

import json
from pathlib import Path

from src.artifacts.research_bundle import build_research_bundle, verify_bundle


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_research_bundle_classifies_data_readiness_indexes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "bundle"
    _write_json(
        source / "data" / "manifest.json",
        {
            "generated_at": "2026-08-02T00:00:00+00:00",
            "evidence_cutoff": "2026-07-31",
            "snapshot_id": "fixture",
        },
    )
    _write_json(source / "data" / "models.json", [])
    _write_json(
        source / "data" / "model-data-readiness.json",
        {
            "schema_version": "1.0",
            "bundle_id": "fixture-data-bundle",
            "evidence_cutoff": "2026-07-31",
            "summary": {
                "ready_component_count": 3,
                "blocked_training_profiles": ["fundamental-model"],
            },
            "research_only": True,
            "trade_ready": False,
        },
    )
    _write_json(source / "data" / "data-components.json", [])
    _write_json(source / "data" / "training-profiles.json", [])

    manifest = build_research_bundle(source, output)
    kinds = {record["path"]: record["kind"] for record in manifest["artifacts"]}

    assert kinds["data/model-data-readiness.json"] == "data_readiness_index"
    assert kinds["data/data-components.json"] == "data_component_index"
    assert kinds["data/training-profiles.json"] == "training_readiness_index"
    assert manifest["data_readiness"] == {
        "bundle_id": "fixture-data-bundle",
        "evidence_cutoff": "2026-07-31",
        "summary": {
            "ready_component_count": 3,
            "blocked_training_profiles": ["fundamental-model"],
        },
    }
    assert "data/model-data-readiness.json" in verify_bundle(output)
