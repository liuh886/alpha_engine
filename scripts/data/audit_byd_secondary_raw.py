#!/usr/bin/env python3
"""Audit canonical BYD raw prices against an independent unadjusted source."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.adapters.base import FetchRequest
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.byd_canonical_bundle import compare_raw_providers, dataframe_sha256


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def _akshare(start: str, cutoff: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_hist(
        symbol="002594",
        period="daily",
        start_date=start.replace("-", ""),
        end_date=cutoff.replace("-", ""),
        adjust="",
    )
    if frame is None or frame.empty:
        raise RuntimeError("empty AkShare unadjusted history")
    rename = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }
    missing = sorted(set(rename) - set(frame.columns))
    if missing:
        raise RuntimeError(f"AkShare missing raw columns: {missing}")
    out = frame[list(rename)].rename(columns=rename).copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise")
    out["volume"] = out["volume"] * 100.0
    return out.sort_values("date").drop_duplicates("date", keep="last")


def _baostock(start: str, cutoff: str) -> pd.DataFrame:
    result = BaoStockAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="002594",
            market="cn",
            start=start,
            end=cutoff,
        )
    )
    return result.df[["date", "open", "high", "low", "close", "volume"]].copy()


def _attempt(provider: str, start: str, cutoff: str, retries: int) -> tuple[pd.DataFrame | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    fetcher = _akshare if provider == "akshare_eastmoney_unadjusted" else _baostock
    for attempt in range(1, retries + 1):
        try:
            frame = fetcher(start, cutoff)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "success",
                    "rows": int(len(frame)),
                    "last_date": pd.Timestamp(frame["date"].iloc[-1]).strftime(
                        "%Y-%m-%d"
                    ),
                }
            )
            return frame, attempts
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            time.sleep(float(attempt))
    return None, attempts


def main() -> None:
    args = _parse_args()
    root = args.canonical_dir
    primary = pd.read_csv(root / "raw_ohlcv.csv", parse_dates=["date"])
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start = str(manifest["first_date"])
    cutoff = str(manifest["cutoff"])

    provider_results: dict[str, Any] = {}
    selected: pd.DataFrame | None = None
    selected_provider: str | None = None
    for provider in (
        "akshare_eastmoney_unadjusted",
        "baostock_adjustflag_3_unadjusted",
    ):
        frame, attempts = _attempt(provider, start, cutoff, args.retries)
        provider_results[provider] = attempts
        if frame is not None:
            selected = frame
            selected_provider = provider
            break

    (root / "secondary_provider_attempts.json").write_text(
        json.dumps(provider_results, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if selected is None or selected_provider is None:
        raise RuntimeError("no independent unadjusted BYD source was available")

    selected.to_csv(
        root / "secondary_raw_ohlcv.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    comparison = compare_raw_providers(primary, selected)
    comparison.to_csv(
        root / "provider_comparison.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    valid = comparison.dropna(
        subset=["primary_open_return", "secondary_open_return"]
    )
    if valid.empty:
        raise RuntimeError("no common return observations with secondary source")
    correlation = float(
        valid["primary_open_return"].corr(valid["secondary_open_return"])
    )
    mean_absolute_difference = float(
        valid["absolute_return_difference"].mean()
    )
    over_1pct = int((valid["absolute_return_difference"] > 0.01).sum())

    manifest.update(
        {
            "secondary_provider": selected_provider,
            "secondary_raw_sha256": dataframe_sha256(selected),
            "provider_comparison_sha256": dataframe_sha256(comparison),
            "common_return_correlation": correlation,
            "mean_absolute_return_difference": mean_absolute_difference,
            "return_differences_over_1pct": over_1pct,
            "common_return_rows": int(len(valid)),
            "secondary_provider_attempts": provider_results,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with (root / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\n## Independent raw-source audit\n\n")
        handle.write(f"- Secondary provider: `{selected_provider}`\n")
        handle.write(f"- Common return rows: `{len(valid)}`\n")
        handle.write(f"- Open-return correlation: `{correlation:.8f}`\n")
        handle.write(
            f"- Mean absolute open-return difference: `{mean_absolute_difference:.8f}`\n"
        )
        handle.write(f"- Sessions over 1% return difference: `{over_1pct}`\n")

    # This is a reconciliation gate, not an equality requirement. Different
    # suspension calendars and provider repairs can create isolated outliers,
    # but a raw stream with materially weak correlation is not an independent
    # confirmation of the canonical primary history.
    if correlation < 0.995:
        raise RuntimeError(
            f"secondary raw-return correlation below 0.995: {correlation:.8f}"
        )
    print(
        json.dumps(
            {
                "secondary_provider": selected_provider,
                "common_return_rows": int(len(valid)),
                "correlation": correlation,
                "mean_absolute_difference": mean_absolute_difference,
                "over_1pct": over_1pct,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
