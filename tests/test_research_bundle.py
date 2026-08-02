from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.research_bundle import (
    BundleBuildError,
    ResearchBundleBuilder,
    _safe_relative,
    build_research_bundle,
    verify_bundle,
)


def _source(root: Path) -> Path:
    source = root / "source"
    (source / "data" / "curves").mkdir(parents=True)
    (source / "reports").mkdir()
    (source / "docs").mkdir()
    (source / "data" / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-02T00:00:00Z",
                "snapshot_id": "fixture-snapshot",
                "evidence_cutoff": "2026-07-31",
                "warnings": ["research only"],
                "blocked_gates": ["trade_ready"],
                "promotion_decision": "research_candidate",
            }
        ),
        encoding="utf-8",
    )
    (source / "data" / "models.json").write_text(
        json.dumps(
            [
                {
                    "id": "run-1",
                    "market": "us",
                    "signal_date": "2026-07-30",
                    "execution_date": "2026-07-31",
                }
            ]
        ),
        encoding="utf-8",
    )
    (source / "data" / "curves" / "run-1.json").write_text(
        json.dumps({"points": [{"date": "2026-07-31", "nav": 1.01}]}), encoding="utf-8"
    )
    (source / "reports" / "result.md").write_text("# Result\n", encoding="utf-8")
    (source / "docs" / "methodology.md").write_text("# Methodology\n", encoding="utf-8")
    return source


@pytest.mark.unit
def test_bundle_is_deterministic_and_preserves_bytes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = build_research_bundle(source, tmp_path / "bundle-a")
    second = build_research_bundle(source, tmp_path / "bundle-b")

    assert first["bundle_id"] == second["bundle_id"]
    assert first["research_only"] is True
    assert first["trade_ready"] is False
    assert first["scope"]["markets"] == ["us"]
    assert verify_bundle(tmp_path / "bundle-a") == verify_bundle(tmp_path / "bundle-b")
    assert (tmp_path / "bundle-a" / "data" / "models.json").read_bytes() == (
        source / "data" / "models.json"
    ).read_bytes()


@pytest.mark.unit
def test_signal_and_execution_dates_are_not_normalized(tmp_path: Path) -> None:
    source = _source(tmp_path)
    build_research_bundle(source, tmp_path / "bundle")
    rows = json.loads((tmp_path / "bundle" / "data" / "models.json").read_text(encoding="utf-8"))
    assert rows[0]["signal_date"] == "2026-07-30"
    assert rows[0]["execution_date"] == "2026-07-31"


@pytest.mark.unit
def test_missing_required_input_fails_closed(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "data" / "models.json").unlink()
    with pytest.raises(BundleBuildError, match="required artifact missing"):
        build_research_bundle(source, tmp_path / "bundle")


@pytest.mark.unit
def test_digest_mismatch_is_detected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    build_research_bundle(source, tmp_path / "bundle")
    (tmp_path / "bundle" / "data" / "models.json").write_text("[]", encoding="utf-8")
    with pytest.raises(BundleBuildError, match="hash mismatch"):
        verify_bundle(tmp_path / "bundle")


@pytest.mark.unit
def test_path_traversal_and_nested_output_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(BundleBuildError, match="unsafe artifact path"):
        _safe_relative("../secret.json")
    source = _source(tmp_path)
    with pytest.raises(BundleBuildError, match="must not be inside"):
        ResearchBundleBuilder(source, source / "bundle")
