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

MAX_ENVELOPE_REPAIR_PCT = 0.002


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


def _audit_and_repair_envelope(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply the frozen canonical high/low envelope policy.

    Open, close and volume remain immutable. A small provider inconsistency may
    only raise high or lower low enough to contain open and close. Every repair
    is returned as explicit metadata; a larger violation blocks the run.
    """

    repaired = frame.copy(deep=True)
    audit: list[dict[str, Any]] = []
    blocked: list[str] = []
    for index, row in frame.iterrows():
        required_high = max(float(row["open"]), float(row["close"]))
        required_low = min(float(row["open"]), float(row["close"]))
        high_gap = max(required_high - float(row["high"]), 0.0)
        low_gap = max(float(row["low"]) - required_low, 0.0)
        scale = max(abs(float(row["close"])), 1e-12)
        violation_pct = max(high_gap, low_gap) / scale
        if violation_pct <= 0.0:
            continue
        within_tolerance = violation_pct <= MAX_ENVELOPE_REPAIR_PCT
        date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
        audit.append(
            {
                "date": date,
                "provider_open": float(row["open"]),
                "provider_high": float(row["high"]),
                "provider_low": float(row["low"]),
                "provider_close": float(row["close"]),
                "high_gap": high_gap,
                "low_gap": low_gap,
                "violation_pct": violation_pct,
                "within_repair_tolerance": within_tolerance,
            }
        )
        if not within_tolerance:
            blocked.append(date)
            continue
        repaired.loc[index, "high"] = max(float(row["high"]), required_high)
        repaired.loc[index, "low"] = min(float(row["low"]), required_low)
    if blocked:
        raise RuntimeError(
            "Yahoo 515180 OHLC envelope violations exceed tolerance: "
            + ", ".join(blocked)
        )
    return repaired, audit


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
    out, envelope_audit = _audit_and_repair_envelope(out)
    return out[["date", *numeric]], {
        "provider": "yfinance",
        "provider_symbol": "515180.SS",
        "start": ETF_CUTOFF,
        "provider_end_exclusive": provider_end,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "raw_and_adjusted_close_same_response": True,
        "envelope_policy": {
            "max_repair_pct": MAX_ENVELOPE_REPAIR_PCT,
            "open_close_volume_immutable": True,
            "high_only_raised": True,
            "low_only_lowered": True,
            "repaired_rows": len(envelope_audit),
            "audit": envelope_audit,
        },
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
