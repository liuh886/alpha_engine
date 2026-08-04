#!/usr/bin/env python3
"""Build the governed 515180.SH canonical ETF bundle."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.etf_515180_canonical import (
    CUTOFF,
    PROVIDER_SYMBOL,
    START_DATE,
    build_515180_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--cutoff", default=CUTOFF)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--secondary-retries", type=int, default=3)
    return parser.parse_args()


def flatten_yahoo(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.reset_index()
    out.columns = [str(column).strip().lower().replace(" ", "_") for column in out.columns]
    return out


def fetch_primary(start: str, cutoff: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    import yfinance as yf

    provider_end = (pd.Timestamp(cutoff) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    history = yf.download(
        PROVIDER_SYMBOL,
        start=start,
        end=provider_end,
        progress=False,
        auto_adjust=False,
        repair=True,
        actions=True,
        threads=False,
    )
    if history is None or history.empty:
        raise RuntimeError("Yahoo returned empty 515180 history")
    frame = flatten_yahoo(history)
    required = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Yahoo 515180 history missing columns: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    frame = frame.loc[frame["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))].copy()
    for column in ("open", "high", "low", "close", "volume", "adj_close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    raw = frame[["date", "open", "high", "low", "close", "volume"]].copy()
    adjusted_close = frame[["date", "adj_close"]].rename(columns={"adj_close": "adjusted_close"})
    action_columns = [column for column in ("dividends", "stock_splits") if column in frame]
    if action_columns:
        actions = frame.loc[
            frame[action_columns].fillna(0.0).abs().sum(axis=1) > 0,
            ["date", *action_columns],
        ].copy()
    else:
        actions = pd.DataFrame(columns=["date", "dividends", "stock_splits"])
    actions = actions.rename(columns={"dividends": "dividend", "stock_splits": "stock_split"})
    if "dividend" not in actions:
        actions["dividend"] = 0.0
    if "stock_split" not in actions:
        actions["stock_split"] = 0.0
    actions["event_source"] = "yfinance_download_actions"
    actions = actions[["date", "dividend", "stock_split", "event_source"]]
    metadata = {
        "provider": "yfinance",
        "provider_symbol": PROVIDER_SYMBOL,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "provider_end_exclusive": provider_end,
        "raw_and_adjusted_close_same_response": True,
    }
    return raw, adjusted_close, actions, metadata


def normalise_akshare(frame: pd.DataFrame) -> pd.DataFrame:
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
        raise RuntimeError(f"AkShare ETF history missing columns: {missing}")
    out = frame[list(rename)].rename(columns=rename).copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise")
    return out.sort_values("date").drop_duplicates("date", keep="last")


def fetch_secondary(start: str, cutoff: str, retries: int) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    import akshare as ak

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max(1, retries) + 1):
        try:
            frame = ak.fund_etf_hist_em(
                symbol="515180",
                period="daily",
                start_date=start.replace("-", ""),
                end_date=cutoff.replace("-", ""),
                adjust="",
            )
            if frame is None or frame.empty:
                raise RuntimeError("empty Eastmoney ETF history")
            out = normalise_akshare(frame)
            attempts.append({"provider": "akshare_eastmoney_unadjusted", "attempt": attempt, "status": "success", "rows": int(len(out))})
            return out, {"provider": "akshare_eastmoney_unadjusted", "provider_symbol": "515180", "attempts": attempts}
        except Exception as exc:
            attempts.append({"provider": "akshare_eastmoney_unadjusted", "attempt": attempt, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
            time.sleep(float(attempt))

    try:
        frame = ak.fund_etf_hist_sina(symbol="sh515180")
        if frame is None or frame.empty:
            raise RuntimeError("empty Sina ETF history")
        out = normalise_akshare(frame)
        out = out.loc[out["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))].copy()
        attempts.append({"provider": "akshare_sina_unadjusted", "attempt": 1, "status": "success", "rows": int(len(out))})
        return out, {"provider": "akshare_sina_unadjusted", "provider_symbol": "sh515180", "attempts": attempts}
    except Exception as exc:
        attempts.append({"provider": "akshare_sina_unadjusted", "attempt": 1, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        return None, {"provider": "secondary_unavailable", "attempts": attempts, "status": "unavailable"}


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def main() -> None:
    args = parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw, adjusted_close, actions, primary_meta = fetch_primary(args.start, args.cutoff)
    secondary, secondary_meta = fetch_secondary(args.start, args.cutoff, args.secondary_retries)
    bundle, quality = build_515180_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted_close,
        corporate_actions=actions,
        raw_secondary=secondary,
        secondary_provider=(secondary_meta.get("provider") if secondary is not None else None),
        provider_parameters={"primary": primary_meta, "secondary": secondary_meta},
        cutoff=args.cutoff,
    )
    write_frame(output / "raw_ohlcv.csv", bundle.raw_bars)
    write_frame(output / "adjustment_factors.csv", bundle.adjustment_factors)
    write_frame(output / "adjusted_ohlcv.csv", bundle.adjusted_bars)
    write_frame(output / "corporate_actions.csv", bundle.corporate_actions)
    write_frame(output / "session_audit.csv", bundle.session_audit)
    write_frame(output / "provider_comparison.csv", bundle.provider_comparison)
    (output / "manifest.json").write_text(
        json.dumps(bundle.manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = [
        "# 515180.SH canonical ETF data",
        "",
        f"- Status: `{bundle.manifest['data_quality_status']}`",
        f"- Range: `{bundle.manifest['first_date']}` to `{bundle.manifest['last_date']}`",
        f"- Rows: `{bundle.manifest['rows']}`",
        f"- Adjusted SHA-256: `{bundle.manifest['adjusted_sha256']}`",
        f"- Manifest SHA-256: `{bundle.manifest['manifest_sha256']}`",
        f"- Secondary coverage: `{bundle.manifest['secondary_coverage']:.6f}`",
        f"- Open-return correlation: `{bundle.manifest['common_return_correlation']}`",
        f"- P99 open-return difference: `{bundle.manifest['p99_open_return_difference']}`",
        f"- Quality gates: `{json.dumps(quality.gates, ensure_ascii=False, sort_keys=True)}`",
        "",
        "Secondary data is audit-only. No rows are stitched or substituted.",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
