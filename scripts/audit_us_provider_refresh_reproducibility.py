"""Compare two isolated selected-pool refresh snapshots field by field.

The auditor consumes complete refresh output roots created by
``refresh_selected_pool_prices_v2.py``. It never fetches data itself. Results
classify byte, row/calendar, floating-point and historical price revisions and
remain research-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CANONICAL_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
)
PRICE_COLUMNS = ("open", "high", "low", "close")
NUMERIC_COLUMNS = CANONICAL_COLUMNS[1:]
MANIFEST = Path("artifacts/selected_pool_price_refresh_manifest.json")
PROVIDER_MANIFEST = Path("data/providers/us/provider_manifest.json")
SOURCE_DIR = Path("data/csv_source")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_source(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if tuple(frame.columns) != CANONICAL_COLUMNS:
        raise ValueError(f"unexpected columns in {path}: {list(frame.columns)}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    for column in NUMERIC_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        raise ValueError(f"duplicate dates in {path}")
    return result


def _safe_relative_difference(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), 1e-12)
    return np.abs(left - right) / scale


def _column_metrics(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    left_values = left.to_numpy(dtype=float)
    right_values = right.to_numpy(dtype=float)
    absolute = np.abs(left_values - right_values)
    relative = _safe_relative_difference(left_values, right_values)
    return {
        "exact_difference_count": int(np.count_nonzero(left_values != right_values)),
        "difference_count_at_1e_12": int(
            np.count_nonzero(~np.isclose(left_values, right_values, rtol=1e-12, atol=1e-12))
        ),
        "difference_count_at_1e_10": int(
            np.count_nonzero(~np.isclose(left_values, right_values, rtol=1e-10, atol=1e-10))
        ),
        "difference_count_at_1e_8": int(
            np.count_nonzero(~np.isclose(left_values, right_values, rtol=1e-8, atol=1e-8))
        ),
        "max_absolute_difference": float(absolute.max(initial=0.0)),
        "max_relative_difference": float(relative.max(initial=0.0)),
    }


def _adjusted_price_pattern(
    left: pd.DataFrame,
    right: pd.DataFrame,
    changed_mask: pd.Series,
) -> dict[str, Any]:
    changed = changed_mask.to_numpy(dtype=bool)
    if not changed.any():
        return {
            "candidate": False,
            "reason": "no changed rows",
        }
    volume_equal = np.isclose(
        left.loc[changed_mask, "volume"].to_numpy(dtype=float),
        right.loc[changed_mask, "volume"].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
    ).all()
    ratios: list[np.ndarray] = []
    for column in PRICE_COLUMNS:
        l_values = left.loc[changed_mask, column].to_numpy(dtype=float)
        r_values = right.loc[changed_mask, column].to_numpy(dtype=float)
        valid = np.abs(l_values) > 1e-12
        column_ratio = np.full_like(l_values, np.nan, dtype=float)
        column_ratio[valid] = r_values[valid] / l_values[valid]
        ratios.append(column_ratio)
    ratio_matrix = np.column_stack(ratios)
    row_spread = np.nanmax(ratio_matrix, axis=1) - np.nanmin(ratio_matrix, axis=1)
    ohlc_scale_consistent = bool(np.nanmax(row_spread, initial=0.0) <= 1e-8)
    return {
        "candidate": bool(volume_equal and ohlc_scale_consistent),
        "volume_unchanged_on_changed_rows": bool(volume_equal),
        "ohlc_ratio_consistent_by_date": ohlc_scale_consistent,
        "max_within_date_ohlc_ratio_spread": float(
            np.nanmax(row_spread, initial=0.0)
        ),
    }


def compare_symbol(left_path: Path, right_path: Path, symbol: str) -> dict[str, Any]:
    left_sha = _sha256(left_path)
    right_sha = _sha256(right_path)
    left = _read_source(left_path)
    right = _read_source(right_path)
    left_dates = pd.Index(left["date"])
    right_dates = pd.Index(right["date"])
    missing_left = right_dates.difference(left_dates)
    missing_right = left_dates.difference(right_dates)
    common_dates = left_dates.intersection(right_dates)
    left_common = left.set_index("date").loc[common_dates].reset_index()
    right_common = right.set_index("date").loc[common_dates].reset_index()

    column_metrics = {
        column: _column_metrics(left_common[column], right_common[column])
        for column in NUMERIC_COLUMNS
    }
    numeric_changed = pd.Series(False, index=left_common.index)
    for column in NUMERIC_COLUMNS:
        numeric_changed |= ~np.isclose(
            left_common[column].to_numpy(dtype=float),
            right_common[column].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-12,
        )
    changed_dates = left_common.loc[numeric_changed, "date"]
    exact_numeric_equal = all(
        item["exact_difference_count"] == 0 for item in column_metrics.values()
    )
    equal_at_1e_10 = all(
        item["difference_count_at_1e_10"] == 0 for item in column_metrics.values()
    )
    row_calendar_same = len(missing_left) == 0 and len(missing_right) == 0
    latest_common_date = common_dates.max() if len(common_dates) else None
    only_latest_row_changed = bool(
        len(changed_dates) > 0
        and latest_common_date is not None
        and changed_dates.nunique() == 1
        and changed_dates.iloc[0] == latest_common_date
    )
    adjustment = _adjusted_price_pattern(left_common, right_common, numeric_changed)

    if left_sha == right_sha:
        classification = "identical"
    elif not row_calendar_same:
        classification = "row_calendar_revision"
    elif exact_numeric_equal:
        classification = "serialization_only"
    elif equal_at_1e_10:
        classification = "floating_point_precision_only"
    elif only_latest_row_changed:
        classification = "latest_row_revision_only"
    elif adjustment["candidate"]:
        classification = "historical_adjusted_price_revision_candidate"
    else:
        classification = "unexplained_numeric_revision"

    return {
        "symbol": symbol,
        "classification": classification,
        "left_sha256": left_sha,
        "right_sha256": right_sha,
        "byte_identical": left_sha == right_sha,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_first_date": left["date"].min().date().isoformat(),
        "right_first_date": right["date"].min().date().isoformat(),
        "left_last_date": left["date"].max().date().isoformat(),
        "right_last_date": right["date"].max().date().isoformat(),
        "missing_from_left": [item.date().isoformat() for item in missing_left],
        "missing_from_right": [item.date().isoformat() for item in missing_right],
        "changed_date_count": int(changed_dates.nunique()),
        "first_changed_date": (
            None if changed_dates.empty else changed_dates.min().date().isoformat()
        ),
        "last_changed_date": (
            None if changed_dates.empty else changed_dates.max().date().isoformat()
        ),
        "column_metrics": column_metrics,
        "adjusted_price_pattern": adjustment,
    }


def _manifest_identity(root: Path) -> dict[str, Any]:
    refresh = _load_json(root / MANIFEST)
    provider = _load_json(root / PROVIDER_MANIFEST)
    return {
        "provider_identity_sha256": str(refresh.get("provider_identity_sha256", "")),
        "provider_manifest_identity_sha256": str(
            provider.get("provider_identity_sha256", "")
        ),
        "calendar": provider.get("calendar"),
        "instruments": provider.get("instruments"),
        "features_sha256": provider.get("features_sha256"),
        "source_csvs": provider.get("source_csvs"),
        "promotion_eligible": refresh.get("promotion_eligible"),
        "cutoff": refresh.get("cutoff"),
        "targets": refresh.get("targets"),
    }


def audit(left_root: Path, right_root: Path) -> dict[str, Any]:
    left_root = left_root.resolve()
    right_root = right_root.resolve()
    left_source = left_root / SOURCE_DIR
    right_source = right_root / SOURCE_DIR
    left_symbols = {path.stem for path in left_source.glob("*.csv")}
    right_symbols = {path.stem for path in right_source.glob("*.csv")}
    if not left_symbols or left_symbols != right_symbols:
        raise ValueError(
            "refresh source symbol sets must be non-empty and identical: "
            f"left={len(left_symbols)} right={len(right_symbols)}"
        )
    symbols = sorted(left_symbols)
    rows = [
        compare_symbol(
            left_source / f"{symbol}.csv",
            right_source / f"{symbol}.csv",
            symbol,
        )
        for symbol in symbols
    ]
    counts = Counter(str(row["classification"]) for row in rows)
    changed = [row for row in rows if row["classification"] != "identical"]
    material = [
        row
        for row in changed
        if row["classification"]
        not in {"serialization_only", "floating_point_precision_only"}
    ]
    left_identity = _manifest_identity(left_root)
    right_identity = _manifest_identity(right_root)
    if not changed:
        preliminary_decision = "append_only_reproducible"
    elif not material:
        preliminary_decision = "metadata_only_identity_change"
    elif any(
        row["classification"] == "unexplained_numeric_revision" for row in material
    ):
        preliminary_decision = "unexplained_provider_drift_blocking"
    else:
        preliminary_decision = "legitimate_historical_revision_explained"
    return {
        "schema_version": "1.0",
        "evidence_type": "us_provider_refresh_reproducibility_audit",
        "research_only": True,
        "trade_ready": False,
        "left_root": str(left_root),
        "right_root": str(right_root),
        "symbol_count": len(symbols),
        "left_identity": left_identity,
        "right_identity": right_identity,
        "provider_identity_match": (
            left_identity["provider_identity_sha256"]
            == right_identity["provider_identity_sha256"]
        ),
        "classification_counts": dict(sorted(counts.items())),
        "changed_symbol_count": len(changed),
        "material_changed_symbol_count": len(material),
        "changed_symbols": [str(row["symbol"]) for row in changed],
        "preliminary_decision": preliminary_decision,
        "controlled_yahoo_mode_audit_required": bool(material),
        "symbols": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-root", type=Path, required=True)
    parser.add_argument("--right-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit(args.left_root, args.right_root)
    _write_json(args.output.resolve(), payload)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
