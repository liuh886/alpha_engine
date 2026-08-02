from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.audit_us_provider_refresh_reproducibility import audit, compare_symbol


COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["2025-01-02", 10.0, 11.0, 9.0, 10.5, 100.0, 1050.0, 1.0],
            ["2025-01-03", 11.0, 12.0, 10.0, 11.5, 110.0, 1265.0, 1.0],
            ["2025-01-06", 12.0, 13.0, 11.0, 12.5, 120.0, 1500.0, 1.0],
        ],
        columns=COLUMNS,
    )


def _write_root(root: Path, frame: pd.DataFrame, identity: str) -> None:
    source = root / "data" / "csv_source"
    provider = root / "data" / "providers" / "us"
    artifacts = root / "artifacts"
    source.mkdir(parents=True)
    provider.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    frame.to_csv(source / "AAA.csv", index=False, lineterminator="\n")
    refresh = {
        "provider_identity_sha256": identity,
        "promotion_eligible": True,
        "cutoff": "2025-01-06",
        "targets": ["AAA"],
    }
    provider_manifest = {
        "provider_identity_sha256": identity,
        "calendar": {"sha256": "calendar"},
        "instruments": {"sha256": "instruments"},
        "features_sha256": "features",
        "source_csvs": {"AAA.csv": "source"},
    }
    (artifacts / "selected_pool_price_refresh_manifest.json").write_text(
        json.dumps(refresh),
        encoding="utf-8",
    )
    (provider / "provider_manifest.json").write_text(
        json.dumps(provider_manifest),
        encoding="utf-8",
    )


def test_identical_sources_are_reproducible(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    frame = _frame()
    _write_root(left, frame, "same")
    _write_root(right, frame, "same")
    result = audit(left, right)
    assert result["provider_identity_match"] is True
    assert result["changed_symbol_count"] == 0
    assert result["classification_counts"] == {"identical": 1}
    assert result["preliminary_decision"] == "append_only_reproducible"


def test_latest_row_revision_is_classified(tmp_path: Path) -> None:
    left_path = tmp_path / "left.csv"
    right_path = tmp_path / "right.csv"
    left = _frame()
    right = left.copy()
    right.loc[2, "close"] = 12.6
    right.loc[2, "amount"] = 1512.0
    left.to_csv(left_path, index=False)
    right.to_csv(right_path, index=False)
    result = compare_symbol(left_path, right_path, "AAA")
    assert result["classification"] == "latest_row_revision_only"
    assert result["changed_date_count"] == 1
    assert result["first_changed_date"] == "2025-01-06"


def test_historical_adjustment_pattern_is_detected(tmp_path: Path) -> None:
    left_path = tmp_path / "left.csv"
    right_path = tmp_path / "right.csv"
    left = _frame()
    right = left.copy()
    for column in ("open", "high", "low", "close"):
        right[column] = right[column] * 0.5
    right["amount"] = right["close"] * right["volume"]
    left.to_csv(left_path, index=False)
    right.to_csv(right_path, index=False)
    result = compare_symbol(left_path, right_path, "AAA")
    assert result["classification"] == (
        "historical_adjusted_price_revision_candidate"
    )
    assert result["adjusted_price_pattern"]["candidate"] is True
    assert result["changed_date_count"] == 3


def test_unexplained_numeric_revision_blocks(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_frame = _frame()
    right_frame = left_frame.copy()
    right_frame.loc[0, "open"] = 17.0
    right_frame.loc[1, "volume"] = 999.0
    _write_root(left, left_frame, "left-id")
    _write_root(right, right_frame, "right-id")
    result = audit(left, right)
    assert result["provider_identity_match"] is False
    assert result["changed_symbol_count"] == 1
    assert result["classification_counts"] == {
        "unexplained_numeric_revision": 1
    }
    assert result["preliminary_decision"] == (
        "unexplained_provider_drift_blocking"
    )
    assert result["controlled_yahoo_mode_audit_required"] is True
