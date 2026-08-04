#!/usr/bin/env python3
"""Append v2 BYD shadow observations and settle from sealed records only."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.research.byd_prospective_evidence_v2 import (
    enrich_observations,
    persist_shadow_store_v2,
)
from src.research.byd_prospective_shadow import (
    audit_independent_raw,
    build_extended_inputs,
    chain_link_provider_history,
    make_signal_observations,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--secondary-retries", type=int, default=2)
    return parser.parse_args()


def _flatten_yahoo(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.reset_index()
    out.columns = [
        str(column).strip().lower().replace(" ", "_")
        for column in out.columns
    ]
    return out


def _fetch_yahoo(as_of: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    import yfinance as yf

    provider_end = (
        pd.Timestamp(as_of) + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")
    frame = yf.download(
        "002594.SZ",
        start="2026-08-03",
        end=provider_end,
        progress=False,
        auto_adjust=False,
        repair=True,
        actions=True,
        threads=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError("Yahoo returned empty prospective BYD history")
    out = _flatten_yahoo(frame)
    required = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    missing = sorted(required - set(out.columns))
    if missing:
        raise RuntimeError(f"Yahoo prospective payload missing columns: {missing}")
    for column in ("dividends", "stock_splits"):
        if column not in out:
            out[column] = 0.0
    out["date"] = (
        pd.to_datetime(out["date"], errors="raise")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    out = out.loc[out["date"].le(pd.Timestamp(as_of))].copy()
    numeric = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_close",
        "dividends",
        "stock_splits",
    )
    for column in numeric:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["dividends"] = out["dividends"].fillna(0.0)
    out["stock_splits"] = out["stock_splits"].fillna(0.0)
    if out[["open", "high", "low", "close", "volume", "adj_close"]].isna().any().any():
        raise RuntimeError("Yahoo prospective payload contains missing market fields")
    return out[["date", *numeric]], {
        "provider": "yfinance",
        "provider_symbol": "002594.SZ",
        "start": "2026-08-03",
        "provider_end_exclusive": provider_end,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "raw_and_adjusted_close_same_response": True,
    }


def _eastmoney(as_of: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_hist(
        symbol="002594",
        period="daily",
        start_date="20260803",
        end_date=as_of.replace("-", ""),
        adjust="",
    )
    if frame is None or frame.empty:
        raise RuntimeError("AkShare/Eastmoney returned empty prospective history")
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
        raise RuntimeError(f"AkShare/Eastmoney missing columns: {missing}")
    out = frame[list(rename)].rename(columns=rename).copy()
    out["volume"] = pd.to_numeric(out["volume"], errors="raise") * 100.0
    return out


def _sina(as_of: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_daily(
        symbol="sz002594",
        start_date="20260803",
        end_date=as_of.replace("-", ""),
        adjust="",
    )
    if frame is None or frame.empty:
        raise RuntimeError("AkShare/Sina returned empty prospective history")
    out = frame.reset_index() if "date" not in frame.columns else frame.copy()
    out.columns = [str(column).strip().lower() for column in out.columns]
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(out.columns))
    if missing:
        raise RuntimeError(f"AkShare/Sina missing columns: {missing}")
    return out[["date", "open", "high", "low", "close", "volume"]]


def _fetch_secondary(
    as_of: str,
    retries: int,
) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    fetchers: tuple[tuple[str, Callable[[str], pd.DataFrame]], ...] = (
        ("akshare_eastmoney_unadjusted", _eastmoney),
        ("akshare_sina_unadjusted", _sina),
    )
    attempts: list[dict[str, Any]] = []
    for provider, fetcher in fetchers:
        for attempt in range(1, max(1, retries) + 1):
            try:
                frame = fetcher(as_of)
                attempts.append(
                    {
                        "provider": provider,
                        "attempt": attempt,
                        "status": "success",
                        "rows": int(len(frame)),
                    }
                )
                return frame, provider, attempts
            except Exception as exc:
                attempts.append(
                    {
                        "provider": provider,
                        "attempt": attempt,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                time.sleep(float(attempt))
    raise RuntimeError(
        "no independent prospective BYD raw source was available: "
        + json.dumps(attempts, ensure_ascii=False)
    )


def _existing_signal_dates(store_dir: Path) -> set[str]:
    observation_dir = store_dir / "observations"
    if not observation_dir.exists():
        return set()
    return {path.stem for path in observation_dir.glob("*.json")}


def main() -> None:
    args = _parse_args()
    as_of = args.as_of or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    baseline_adjusted = pd.read_csv(
        args.baseline_dir / "adjusted_ohlcv.csv",
        parse_dates=["date"],
    )
    baseline_sessions = pd.read_csv(
        args.baseline_dir / "session_audit.csv",
        parse_dates=["date"],
    )

    provider_history, primary_meta = _fetch_yahoo(as_of)
    extension = chain_link_provider_history(baseline_adjusted, provider_history)
    if extension.adjusted_new.empty:
        print(json.dumps({"status": "no_post_cutoff_rows", "as_of": as_of}))
        return

    secondary, secondary_provider, attempts = _fetch_secondary(
        as_of,
        args.secondary_retries,
    )
    secondary["date"] = pd.to_datetime(secondary["date"], errors="raise")
    for column in ("open", "high", "low", "close", "volume"):
        secondary[column] = pd.to_numeric(secondary[column], errors="raise")
    audit = audit_independent_raw(
        extension.primary_raw_new,
        secondary,
        secondary_provider=secondary_provider,
    )
    extended_adjusted, extended_sessions = build_extended_inputs(
        baseline_adjusted,
        baseline_sessions,
        extension,
        audit,
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    observations, _, _ = make_signal_observations(
        extended_adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc=observed_at,
    )
    observations = enrich_observations(
        observations,
        extension,
        audit,
        provider_history,
        primary_provider="yfinance_unadjusted_plus_adj_close",
    )
    existing = _existing_signal_dates(args.store_dir)
    new_observations = [
        row for row in observations if row["signal_date"] not in existing
    ]
    for observation in new_observations:
        observation["provider_parameters"] = primary_meta
        observation["secondary_attempts"] = attempts
    manifest = persist_shadow_store_v2(args.store_dir, new_observations)
    print(
        json.dumps(
            {
                "status": "prospective_shadow_v2_updated",
                "as_of": as_of,
                "new_observations": len(new_observations),
                "observation_count": manifest["observation_count"],
                "prospective_eligible_observation_count": manifest[
                    "prospective_eligible_observation_count"
                ],
                "outcome_count": manifest["outcome_count"],
                "last_signal_date": manifest["last_signal_date"],
                "ledger_sha256": manifest["ledger_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
