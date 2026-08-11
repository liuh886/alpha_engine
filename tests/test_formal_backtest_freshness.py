from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_formal_backtest_freshness import (
    FormalBacktestFreshnessError,
    verify,
)


def _write(path: Path, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(
    tmp_path: Path,
    *,
    evidence_cutoff: str = "2026-07-31",
    range_end: str = "2026-07-31",
    receipt_required: bool = True,
    declared_cutoff: str = "2026-07-31",
    next_close: str = "2026-08-03T20:00:00Z",
) -> Path:
    root = tmp_path / "formal"
    root.mkdir()
    _write(
        root / "freshness.json",
        {
            "cutoff_policy": "latest_completed_trading_session",
            "markets": {"us": declared_cutoff},
            "next_session_close_utc": {"us": next_close},
            "required_models": ["model_a"],
            "freshness_receipt_required_models": (
                ["model_a"] if receipt_required else []
            ),
            "date_range_end_required_models": (
                ["model_a"] if receipt_required else []
            ),
            "research_only": True,
            "trade_ready": False,
        },
    )
    package: dict[str, object] = {
        "model_id": "model_a",
        "market": "us",
        "publication_status": "accepted_formal_baseline",
        "evidence_cutoff": evidence_cutoff,
        "date_range": {"start": "2024-01-01", "end": range_end},
        "research_only": True,
        "trade_ready": False,
    }
    if receipt_required:
        package["freshness"] = {
            "status": "current",
            "required_cutoff": declared_cutoff,
            "latest_completed_session": declared_cutoff,
            "latest_realized_holding_end": "2026-07-30",
            "model_selection_reopened": False,
        }
    digest = _write(root / "model_a.json", package)
    _write(
        root / "catalog.json",
        {
            "records": [
                {
                    "model_id": "model_a",
                    "path": "model_a.json",
                    "sha256": digest,
                }
            ]
        },
    )
    return root


def test_accepts_provider_resolved_cutoff_before_next_session_close(tmp_path: Path) -> None:
    result = verify(
        _fixture(tmp_path),
        as_of="2026-08-03T02:16:00Z",
    )
    assert result["status"] == "current"
    assert result["next_session_close_utc"] == {
        "us": "2026-08-03T20:00:00+00:00"
    }
    assert result["verified_models"][0]["required_cutoff"] == "2026-07-31"


def test_accepts_provider_resolved_cutoff_after_market_close(tmp_path: Path) -> None:
    result = verify(
        _fixture(tmp_path),
        as_of="2026-08-04T00:00:00Z",
    )
    assert result["status"] == "current"
    assert result["as_of"] == "2026-08-04T00:00:00+00:00"
    assert result["verified_models"][0]["required_cutoff"] == "2026-07-31"


def test_rejects_naive_as_of_timestamp(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    with pytest.raises(FormalBacktestFreshnessError, match="must include a timezone"):
        verify(root, as_of="2026-08-03T02:16:00")


def test_accepts_current_provider_with_earlier_realized_range(tmp_path: Path) -> None:
    root = _fixture(
        tmp_path,
        range_end="2026-07-30",
        receipt_required=False,
    )
    assert verify(root)["status"] == "current"


def test_rejects_stale_evidence_cutoff(tmp_path: Path) -> None:
    root = _fixture(tmp_path, evidence_cutoff="2026-06-30")
    with pytest.raises(FormalBacktestFreshnessError, match="stale formal package"):
        verify(root)


def test_rejects_stale_required_reporting_range(tmp_path: Path) -> None:
    root = _fixture(tmp_path, range_end="2026-07-30")
    with pytest.raises(FormalBacktestFreshnessError, match="stale reporting range"):
        verify(root)


def test_rejects_catalog_digest_mismatch(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    package = root / "model_a.json"
    package.write_text(package.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(FormalBacktestFreshnessError, match="catalog SHA-256 mismatch"):
        verify(root)


def test_rejects_missing_freshness_receipt(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    package = json.loads((root / "model_a.json").read_text(encoding="utf-8"))
    package.pop("freshness")
    digest = _write(root / "model_a.json", package)
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    catalog["records"][0]["sha256"] = digest
    _write(root / "catalog.json", catalog)
    with pytest.raises(FormalBacktestFreshnessError, match="freshness receipt is missing"):
        verify(root)


def test_rejects_model_selection_reopened(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    package = json.loads((root / "model_a.json").read_text(encoding="utf-8"))
    package["freshness"]["model_selection_reopened"] = True
    digest = _write(root / "model_a.json", package)
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    catalog["records"][0]["sha256"] = digest
    _write(root / "catalog.json", catalog)
    with pytest.raises(FormalBacktestFreshnessError, match="reopened model selection"):
        verify(root)