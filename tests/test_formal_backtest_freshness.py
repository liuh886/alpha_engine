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
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path, *, cutoff: str = "2026-07-31") -> Path:
    root = tmp_path / "formal"
    root.mkdir()
    _write(
        root / "freshness.json",
        {
            "cutoff_policy": "latest_completed_trading_session",
            "markets": {"us": "2026-07-31"},
            "required_models": ["model_a"],
            "research_only": True,
            "trade_ready": False,
        },
    )
    digest = _write(
        root / "model_a.json",
        {
            "model_id": "model_a",
            "market": "us",
            "publication_status": "accepted_formal_baseline",
            "evidence_cutoff": cutoff,
            "date_range": {"start": "2024-01-01", "end": cutoff},
            "freshness": {
                "status": "current",
                "required_cutoff": cutoff,
                "latest_completed_session": cutoff,
            },
            "research_only": True,
            "trade_ready": False,
        },
    )
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


def test_accepts_current_formal_package(tmp_path: Path) -> None:
    result = verify(_fixture(tmp_path))
    assert result["status"] == "current"
    assert result["verified_models"][0]["required_cutoff"] == "2026-07-31"


def test_rejects_stale_formal_package(tmp_path: Path) -> None:
    root = _fixture(tmp_path, cutoff="2026-06-30")
    with pytest.raises(FormalBacktestFreshnessError, match="stale formal package"):
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
