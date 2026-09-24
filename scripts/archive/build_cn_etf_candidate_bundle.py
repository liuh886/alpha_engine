#!/usr/bin/env python3
"""Build a governed canonical bundle for one frozen CN ETF candidate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.cn_etf_candidate_canonical import ETFSpec, build_candidate_bundle

MAX_ENVELOPE_REPAIR_PCT = 0.002


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, choices=("512890.SH", "511010.SH"))
    parser.add_argument("--provider-symbol", required=True)
    parser.add_argument("--sina-symbol", required=True)
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--cutoff", default="2026-08-03")
    parser.add_argument("--secondary-retries", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def flatten_yahoo(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.reset_index()
    out.columns = [
        str(column).strip().lower().replace(" ", "_")
        for column in out.columns
    ]
    return out


def audit_and_repair_envelope(
    raw: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Audit every provider envelope issue before any fail-closed decision."""

    repaired = raw.copy(deep=True)
    rows: list[dict[str, object]] = []
    blocked: list[str] = []
    for index, row in raw.iterrows():
        required_high = max(float(row["open"]), float(row["close"]))
        required_low = min(float(row["open"]), float(row["close"]))
        high_gap = max(required_high - float(row["high"]), 0.0)
        low_gap = max(float(row["low"]) - required_low, 0.0)
        scale = max(abs(float(row["close"])), 1e-12)
        violation = max(high_gap, low_gap) / scale
        if violation <= 0.0:
            continue
        date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
        within = violation <= MAX_ENVELOPE_REPAIR_PCT
        rows.append(
            {
                "date": pd.Timestamp(row["date"]),
                "provider_open": float(row["open"]),
                "provider_high": float(row["high"]),
                "provider_low": float(row["low"]),
                "provider_close": float(row["close"]),
                "high_gap": high_gap,
                "low_gap": low_gap,
                "violation_pct": violation,
                "within_repair_tolerance": within,
            }
        )
        if not within:
            blocked.append(date)
            continue
        repaired.loc[index, "high"] = max(float(row["high"]), required_high)
        repaired.loc[index, "low"] = min(float(row["low"]), required_low)
    return repaired, pd.DataFrame(rows), blocked


def fetch_primary(
    provider_symbol: str,
    start: str,
    cutoff: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    import yfinance as yf

    provider_end = (
        pd.Timestamp(cutoff) + pd.Timedelta(days=1)
    ).strftime("%Y-%m-%d")
    history = yf.download(
        provider_symbol,
        start=start,
        end=provider_end,
        progress=False,
        auto_adjust=False,
        repair=True,
        actions=True,
        threads=False,
    )
    if history is None or history.empty:
        raise RuntimeError(f"Yahoo returned empty history for {provider_symbol}")
    frame = flatten_yahoo(history)
    required = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Yahoo history missing columns: {missing}")
    frame["date"] = (
        pd.to_datetime(frame["date"], errors="raise")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    frame = frame.loc[
        frame["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))
    ].copy()
    numeric = ("open", "high", "low", "close", "volume", "adj_close")
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    raw_reference = frame[["date", "open", "high", "low", "close", "volume"]].copy()
    adjusted = frame[["date", "adj_close"]].rename(
        columns={"adj_close": "adjusted_close"}
    )
    for column in ("dividends", "stock_splits"):
        if column not in frame:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    actions = frame.loc[
        frame[["dividends", "stock_splits"]].abs().sum(axis=1) > 0,
        ["date", "dividends", "stock_splits"],
    ].rename(
        columns={"dividends": "dividend", "stock_splits": "stock_split"}
    )
    actions["event_source"] = "yfinance_download_actions"
    metadata = {
        "provider": "yfinance",
        "provider_symbol": provider_symbol,
        "requested_start": start,
        "provider_end_exclusive": provider_end,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "raw_and_adjusted_close_same_response": True,
    }
    return raw_reference, adjusted, actions, metadata


def normalise_secondary(frame: pd.DataFrame) -> pd.DataFrame:
    chinese = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }
    english = {
        column: column
        for column in ("date", "open", "high", "low", "close", "volume")
    }
    if set(chinese).issubset(frame.columns):
        out = frame[list(chinese)].rename(columns=chinese).copy()
    elif set(english).issubset(frame.columns):
        out = frame[list(english)].copy()
    else:
        raise RuntimeError(
            "secondary ETF history missing supported OHLCV schema: "
            + ", ".join(map(str, frame.columns))
        )
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise")
    return out.sort_values("date").drop_duplicates("date", keep="last")


def fetch_secondary(
    code: str,
    sina_symbol: str,
    start: str,
    cutoff: str,
    retries: int,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    import akshare as ak

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max(1, retries) + 1):
        try:
            frame = ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=cutoff.replace("-", ""),
                adjust="",
            )
            if frame is None or frame.empty:
                raise RuntimeError("empty Eastmoney ETF history")
            out = normalise_secondary(frame)
            attempts.append(
                {
                    "provider": "akshare_eastmoney_unadjusted",
                    "attempt": attempt,
                    "status": "success",
                    "rows": int(len(out)),
                }
            )
            return out, {
                "provider": "akshare_eastmoney_unadjusted",
                "provider_symbol": code,
                "attempts": attempts,
            }
        except Exception as exc:
            attempts.append(
                {
                    "provider": "akshare_eastmoney_unadjusted",
                    "attempt": attempt,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            time.sleep(float(attempt))
    try:
        frame = ak.fund_etf_hist_sina(symbol=sina_symbol)
        if frame is None or frame.empty:
            raise RuntimeError("empty Sina ETF history")
        out = normalise_secondary(frame)
        out = out.loc[
            out["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))
        ].copy()
        attempts.append(
            {
                "provider": "akshare_sina_unadjusted",
                "attempt": 1,
                "status": "success",
                "rows": int(len(out)),
            }
        )
        return out, {
            "provider": "akshare_sina_unadjusted",
            "provider_symbol": sina_symbol,
            "attempts": attempts,
        }
    except Exception as exc:
        attempts.append(
            {
                "provider": "akshare_sina_unadjusted",
                "attempt": 1,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return None, {
            "provider": "secondary_unavailable",
            "status": "unavailable",
            "attempts": attempts,
        }


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def main() -> None:
    args = parse_args()
    output: Path = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    code = args.symbol.split(".")[0]
    try:
        raw_reference, adjusted, actions, primary = fetch_primary(
            args.provider_symbol,
            args.start,
            args.cutoff,
        )
        write_frame(output / "provider_reference_ohlcv.csv", raw_reference)
        raw, envelope_audit, blocked_dates = audit_and_repair_envelope(raw_reference)
        write_frame(output / "provider_envelope_audit.csv", envelope_audit)
        primary["envelope_policy"] = {
            "max_repair_pct": MAX_ENVELOPE_REPAIR_PCT,
            "open_close_volume_immutable": True,
            "high_only_raised": True,
            "low_only_lowered": True,
            "repaired_rows": int(
                envelope_audit["within_repair_tolerance"].sum()
            )
            if not envelope_audit.empty
            else 0,
            "blocked_rows": len(blocked_dates),
        }
        if blocked_dates:
            raise RuntimeError(
                "provider OHLC envelope violations exceed tolerance: "
                + ", ".join(blocked_dates)
            )
        secondary, secondary_meta = fetch_secondary(
            code,
            args.sina_symbol,
            args.start,
            args.cutoff,
            args.secondary_retries,
        )
        bundle, quality = build_candidate_bundle(
            spec=ETFSpec(
                symbol=args.symbol,
                provider_symbol=args.provider_symbol,
                cutoff=args.cutoff,
            ),
            raw_primary=raw,
            provider_adjusted_close=adjusted,
            corporate_actions=actions,
            raw_secondary=secondary,
            secondary_provider=(
                str(secondary_meta["provider"]) if secondary is not None else None
            ),
            provider_parameters={
                "primary": primary,
                "secondary": secondary_meta,
            },
        )
        write_frame(output / "raw_ohlcv.csv", bundle.raw_bars)
        write_frame(output / "adjustment_factors.csv", bundle.adjustment_factors)
        write_frame(output / "adjusted_ohlcv.csv", bundle.adjusted_bars)
        write_frame(output / "corporate_actions.csv", bundle.corporate_actions)
        write_frame(output / "session_audit.csv", bundle.session_audit)
        write_frame(output / "provider_comparison.csv", bundle.provider_comparison)
        (output / "manifest.json").write_text(
            json.dumps(bundle.manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        report = [
            f"# {args.symbol} canonical candidate data",
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
        (output / "report.md").write_text(
            "\n".join(report) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True))
        if not quality.passed:
            raise RuntimeError(f"{args.symbol} canonical quality gates failed")
    except Exception as exc:
        blocker = {
            "status": "data_blocked",
            "symbol": args.symbol,
            "cutoff": args.cutoff,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "provider_reference_preserved": (
                output / "provider_reference_ohlcv.csv"
            ).exists(),
            "provider_envelope_audit_preserved": (
                output / "provider_envelope_audit.csv"
            ).exists(),
        }
        (output / "data_blocked.json").write_text(
            json.dumps(blocker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
