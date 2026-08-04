#!/usr/bin/env python3
"""Append BYD/515180 prospective sleeve observations from sealed BYD records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.data.fetch_515180_secondary_v2 import fetch_secondary_v2
from src.data.byd_canonical_bundle import dataframe_sha256
from src.research.byd_515180_prospective import (
    ETF_ADJUSTED_SHA256,
    ETF_ARTIFACT_SHA256,
    ETF_CUTOFF,
    ETF_MANIFEST_SHA256,
    build_paired_observations,
    load_byd_observations,
    persist_store,
    read_paired_observations,
)
from src.research.byd_prospective_shadow import (
    audit_independent_raw,
    chain_link_provider_history,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-store", type=Path, required=True)
    parser.add_argument("--etf-baseline-dir", type=Path, required=True)
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
        "515180.SS",
        start=ETF_CUTOFF,
        end=provider_end,
        progress=False,
        auto_adjust=False,
        repair=True,
        actions=True,
        threads=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError("Yahoo returned empty prospective 515180 history")
    out = _flatten_yahoo(frame)
    required = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_close",
    }
    missing = sorted(required - set(out.columns))
    if missing:
        raise RuntimeError(f"Yahoo 515180 payload missing columns: {missing}")
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
    market = ["open", "high", "low", "close", "volume", "adj_close"]
    if out[market].isna().any().any():
        raise RuntimeError("Yahoo 515180 payload contains missing market fields")
    invalid = (
        out["high"].lt(out[["open", "close"]].max(axis=1))
        | out["low"].gt(out[["open", "close"]].min(axis=1))
    )
    if invalid.any():
        dates = out.loc[invalid, "date"].dt.strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"Yahoo 515180 OHLC envelope invalid: {dates}")
    return out[["date", *numeric]], {
        "provider": "yfinance",
        "provider_symbol": "515180.SS",
        "start": ETF_CUTOFF,
        "provider_end_exclusive": provider_end,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "raw_and_adjusted_close_same_response": True,
    }


def _verify_baseline(directory: Path) -> None:
    manifest = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    exact = {
        "symbol": "515180.SH",
        "cutoff": ETF_CUTOFF,
        "data_quality_status": "canonical_v1_pass",
        "adjusted_sha256": ETF_ADJUSTED_SHA256,
        "manifest_sha256": ETF_MANIFEST_SHA256,
    }
    for key, expected in exact.items():
        if manifest.get(key) != expected:
            raise RuntimeError(
                f"515180 baseline identity mismatch for {key}: "
                f"{manifest.get(key)!r} != {expected!r}"
            )


def main() -> None:
    args = _parse_args()
    as_of = args.as_of or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    _verify_baseline(args.etf_baseline_dir)

    baseline_adjusted = pd.read_csv(
        args.etf_baseline_dir / "adjusted_ohlcv.csv",
        parse_dates=["date"],
    )
    provider_history, primary_meta = _fetch_yahoo(as_of)
    extension = chain_link_provider_history(
        baseline_adjusted,
        provider_history,
    )
    if extension.adjusted_new.empty:
        print(
            json.dumps(
                {"status": "no_post_cutoff_etf_rows", "as_of": as_of}
            )
        )
        return

    secondary, secondary_meta = fetch_secondary_v2(
        ETF_CUTOFF,
        as_of,
        args.secondary_retries,
    )
    if secondary is None:
        raise RuntimeError(
            "no independent 515180 source available: "
            + json.dumps(secondary_meta, ensure_ascii=False)
        )
    audit = audit_independent_raw(
        extension.primary_raw_new,
        secondary,
        secondary_provider=str(secondary_meta["provider"]),
    )
    extended_adjusted = pd.concat(
        [baseline_adjusted, extension.adjusted_new],
        ignore_index=True,
    ).sort_values("date")
    if extended_adjusted["date"].duplicated().any():
        raise RuntimeError("515180 extension would overwrite canonical history")
    extended_sha = dataframe_sha256(extended_adjusted)

    byd_observations = load_byd_observations(args.byd_store)
    existing = read_paired_observations(args.store_dir)
    existing_dates = {row["signal_date"] for row in existing}
    observed_at = datetime.now(timezone.utc).isoformat()
    new_observations = build_paired_observations(
        byd_observations=byd_observations,
        extension=extension,
        audit=audit,
        provider_history=provider_history,
        existing_dates=existing_dates,
        observed_at_utc=observed_at,
        primary_provider="yfinance_unadjusted_plus_adj_close",
        provider_parameters={
            **primary_meta,
            "etf_artifact_sha256": ETF_ARTIFACT_SHA256,
        },
        secondary_attempts=list(secondary_meta.get("attempts", [])),
        extended_adjusted_sha256=extended_sha,
    )
    manifest = persist_store(args.store_dir, new_observations)
    print(
        json.dumps(
            {
                "status": "byd_515180_prospective_updated",
                "as_of": as_of,
                "new_observations": len(new_observations),
                "observation_count": manifest["observation_count"],
                "prospective_eligible_observation_count": manifest[
                    "prospective_eligible_observation_count"
                ],
                "outcome_count": manifest["outcome_count"],
                "last_signal_date": manifest["last_signal_date"],
                "ledger_sha256": manifest["ledger_sha256"],
                "scorecard_sha256": manifest["scorecard_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
