"""Isolate Yahoo/yfinance adjustment and repair nondeterminism.

The audit downloads a bounded US symbol set twice under three modes and retains
all frames. It distinguishes raw-bar, Adj Close, auto-adjust and repair-layer
instability without training a model.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SYMBOLS = (
    "AAPL",
    "ASML",
    "AVGO",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "QQQ",
    "TSM",
    "VRT",
)
MODES: dict[str, dict[str, bool]] = {
    "adjusted_repair": {"auto_adjust": True, "repair": True},
    "adjusted_no_repair": {"auto_adjust": True, "repair": False},
    "raw_no_repair": {"auto_adjust": False, "repair": False},
}
PRICE_COLUMNS = ("open", "high", "low", "close")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _normalise_download(frame: pd.DataFrame, *, auto_adjust: bool) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("Yahoo returned an empty frame")
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    result = result.reset_index()
    result.columns = [str(column).strip().lower().replace(" ", "_") for column in result.columns]
    if "datetime" in result.columns and "date" not in result.columns:
        result = result.rename(columns={"datetime": "date"})
    required = ["date", "open", "high", "low", "close", "volume"]
    if not auto_adjust:
        required.append("adj_close")
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise ValueError(f"Yahoo frame is missing columns: {missing}")
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    if result["date"].dt.tz is not None:
        result["date"] = result["date"].dt.tz_localize(None)
    result["date"] = result["date"].dt.normalize()
    for column in required[1:]:
        result[column] = pd.to_numeric(result[column], errors="raise")
    return result.loc[:, required].sort_values("date").reset_index(drop=True)


def download_mode(
    symbol: str,
    *,
    start: str,
    cutoff: str,
    auto_adjust: bool,
    repair: bool,
) -> pd.DataFrame:
    import yfinance as yf

    provider_end = (pd.Timestamp(cutoff) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Timestamp.utcnow is deprecated.*")
        frame = yf.download(
            symbol,
            start=start,
            end=provider_end,
            progress=False,
            auto_adjust=auto_adjust,
            repair=repair,
            threads=False,
        )
    result = _normalise_download(frame, auto_adjust=auto_adjust)
    return result.loc[result["date"] <= pd.Timestamp(cutoff)].reset_index(drop=True)


def _relative_difference(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), 1e-12)
    return np.abs(left - right) / scale


def compare_frames(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    left_dates = pd.Index(left["date"])
    right_dates = pd.Index(right["date"])
    missing_left = right_dates.difference(left_dates)
    missing_right = left_dates.difference(right_dates)
    common = left_dates.intersection(right_dates)
    left_common = left.set_index("date").loc[common]
    right_common = right.set_index("date").loc[common]
    columns = sorted(set(left_common.columns) & set(right_common.columns))
    column_rows: dict[str, Any] = {}
    changed_dates = pd.Series(False, index=common)
    for column in columns:
        l_values = left_common[column].to_numpy(dtype=float)
        r_values = right_common[column].to_numpy(dtype=float)
        exact = l_values != r_values
        material = ~np.isclose(l_values, r_values, rtol=1e-8, atol=1e-8)
        changed_dates |= material
        absolute = np.abs(l_values - r_values)
        relative = _relative_difference(l_values, r_values)
        column_rows[column] = {
            "exact_difference_count": int(exact.sum()),
            "material_difference_count_1e_8": int(material.sum()),
            "max_absolute_difference": float(absolute.max(initial=0.0)),
            "max_relative_difference": float(relative.max(initial=0.0)),
        }
    changed_index = common[changed_dates.to_numpy(dtype=bool)]
    return {
        "row_calendar_match": len(missing_left) == 0 and len(missing_right) == 0,
        "missing_from_left": [item.date().isoformat() for item in missing_left],
        "missing_from_right": [item.date().isoformat() for item in missing_right],
        "exact_match": (
            len(missing_left) == 0
            and len(missing_right) == 0
            and all(row["exact_difference_count"] == 0 for row in column_rows.values())
        ),
        "material_match_1e_8": (
            len(missing_left) == 0
            and len(missing_right) == 0
            and all(
                row["material_difference_count_1e_8"] == 0
                for row in column_rows.values()
            )
        ),
        "material_changed_date_count_1e_8": int(len(changed_index)),
        "first_material_changed_date": (
            None if len(changed_index) == 0 else changed_index.min().date().isoformat()
        ),
        "last_material_changed_date": (
            None if len(changed_index) == 0 else changed_index.max().date().isoformat()
        ),
        "columns": column_rows,
    }


def derive_adjusted_ohlc(raw: pd.DataFrame) -> pd.DataFrame:
    if "adj_close" not in raw.columns:
        raise ValueError("raw frame must contain adj_close")
    ratio = raw["adj_close"] / raw["close"]
    result = pd.DataFrame({"date": raw["date"]})
    for column in PRICE_COLUMNS:
        result[column] = raw[column] * ratio
    result["volume"] = raw["volume"]
    return result


def decide(summary: dict[str, Any]) -> str:
    raw = summary["mode_reproducibility"]["raw_no_repair"]
    adjusted_no_repair = summary["mode_reproducibility"]["adjusted_no_repair"]
    adjusted_repair = summary["mode_reproducibility"]["adjusted_repair"]
    raw_ohlcv_stable = all(
        row["raw_ohlcv_exact"] for row in raw.values()
    )
    adj_close_stable = all(
        row["adj_close_exact"] for row in raw.values()
    )
    no_repair_stable = all(row["exact_match"] for row in adjusted_no_repair.values())
    repair_stable = all(row["exact_match"] for row in adjusted_repair.values())
    if not raw_ohlcv_stable:
        return "upstream_raw_bar_nondeterminism"
    if not adj_close_stable:
        return "upstream_adjustment_revision"
    if not no_repair_stable:
        return "auto_adjust_computation_nondeterminism"
    if not repair_stable:
        return "repair_induced_nondeterminism"
    if all(
        row["exact_match"]
        for pass_rows in summary["derived_adjustment_comparison"].values()
        for row in pass_rows.values()
    ):
        return "bounded_subset_reproducible"
    return "mixed_or_unexplained_source_nondeterminism"


def run(*, start: str, cutoff: str, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    frames: dict[str, dict[str, dict[str, pd.DataFrame]]] = {
        "a": {},
        "b": {},
    }
    for pass_id in ("a", "b"):
        for mode, settings in MODES.items():
            frames[pass_id][mode] = {}
            for symbol in SYMBOLS:
                frame = download_mode(
                    symbol,
                    start=start,
                    cutoff=cutoff,
                    auto_adjust=settings["auto_adjust"],
                    repair=settings["repair"],
                )
                frames[pass_id][mode][symbol] = frame
                path = output_dir / "snapshots" / pass_id / mode / f"{symbol}.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                export = frame.copy()
                export["date"] = export["date"].dt.strftime("%Y-%m-%d")
                export.to_csv(path, index=False, lineterminator="\n")

    mode_reproducibility: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        mode_reproducibility[mode] = {}
        for symbol in SYMBOLS:
            comparison = compare_frames(
                frames["a"][mode][symbol],
                frames["b"][mode][symbol],
            )
            if mode == "raw_no_repair":
                comparison["raw_ohlcv_exact"] = all(
                    comparison["columns"][column]["exact_difference_count"] == 0
                    for column in (*PRICE_COLUMNS, "volume")
                ) and comparison["row_calendar_match"]
                comparison["adj_close_exact"] = (
                    comparison["columns"]["adj_close"]["exact_difference_count"] == 0
                    and comparison["row_calendar_match"]
                )
            mode_reproducibility[mode][symbol] = comparison

    repair_effect: dict[str, dict[str, Any]] = {"a": {}, "b": {}}
    derived_comparison: dict[str, dict[str, Any]] = {"a": {}, "b": {}}
    for pass_id in ("a", "b"):
        for symbol in SYMBOLS:
            repair_effect[pass_id][symbol] = compare_frames(
                frames[pass_id]["adjusted_repair"][symbol],
                frames[pass_id]["adjusted_no_repair"][symbol],
            )
            derived = derive_adjusted_ohlc(frames[pass_id]["raw_no_repair"][symbol])
            derived_comparison[pass_id][symbol] = compare_frames(
                frames[pass_id]["adjusted_no_repair"][symbol],
                derived,
            )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_type": "yahoo_adjustment_mode_reproducibility_audit",
        "issue": 386,
        "research_only": True,
        "trade_ready": False,
        "symbols": list(SYMBOLS),
        "start": start,
        "cutoff": cutoff,
        "modes": MODES,
        "mode_reproducibility": mode_reproducibility,
        "repair_effect": repair_effect,
        "derived_adjustment_comparison": derived_comparison,
    }
    payload["decision"] = decide(payload)
    _write_json(output_dir / "audit.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", default="2026-07-31")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/yahoo_adjustment_mode_audit"),
    )
    args = parser.parse_args()
    payload = run(start=args.start, cutoff=args.cutoff, output_dir=args.output_dir)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
