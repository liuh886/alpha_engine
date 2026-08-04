#!/usr/bin/env python3
"""Build the governed BYD canonical raw/factor/adjusted daily-bar bundle."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.byd_canonical_bundle import CanonicalBundle, build_canonical_bundle


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2011-06-30")
    parser.add_argument("--cutoff", default="2026-08-03")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--secondary-retries", type=int, default=2)
    return parser.parse_args()


def _flatten_yahoo(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out = out.reset_index()
    out.columns = [str(column).strip().lower().replace(" ", "_") for column in out.columns]
    return out


def _fetch_yahoo_primary(start: str, cutoff: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    import yfinance as yf

    provider_end = (pd.Timestamp(cutoff) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    symbol = "002594.SZ"
    history = yf.download(
        symbol,
        start=start,
        end=provider_end,
        progress=False,
        auto_adjust=False,
        repair=True,
        actions=True,
        threads=False,
    )
    if history is None or history.empty:
        raise RuntimeError("Yahoo returned empty BYD history")
    frame = _flatten_yahoo(history)
    required = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"Yahoo raw history missing columns: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    frame = frame.loc[frame["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))].copy()
    for column in ("open", "high", "low", "close", "volume", "adj_close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    raw = frame[["date", "open", "high", "low", "close", "volume"]].copy()
    adjusted_close = frame[["date", "adj_close"]].rename(
        columns={"adj_close": "adjusted_close"}
    )

    action_columns = [column for column in ("dividends", "stock_splits") if column in frame]
    if action_columns:
        actions = frame.loc[
            frame[action_columns].fillna(0.0).abs().sum(axis=1) > 0,
            ["date", *action_columns],
        ].copy()
    else:
        actions = pd.DataFrame(columns=["date", "dividends", "stock_splits"])
    actions = actions.rename(
        columns={"dividends": "dividend", "stock_splits": "stock_split"}
    )
    if "dividend" not in actions:
        actions["dividend"] = 0.0
    if "stock_split" not in actions:
        actions["stock_split"] = 0.0
    actions["event_source"] = "yfinance_download_actions"
    actions = actions[["date", "dividend", "stock_split", "event_source"]]

    metadata = {
        "provider": "yfinance",
        "provider_symbol": symbol,
        "auto_adjust": False,
        "repair": True,
        "actions": True,
        "provider_end_exclusive": provider_end,
        "raw_and_adjusted_close_same_response": True,
    }
    return raw, adjusted_close, actions, metadata


def _fetch_akshare_raw(start: str, cutoff: str, retries: int) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    import akshare as ak

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max(1, retries) + 1):
        try:
            frame = ak.stock_zh_a_hist(
                symbol="002594",
                period="daily",
                start_date=start.replace("-", ""),
                end_date=cutoff.replace("-", ""),
                adjust="",
            )
            if frame is None or frame.empty:
                raise RuntimeError("empty AkShare raw history")
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
                raise RuntimeError(f"AkShare raw history missing columns: {missing}")
            out = frame[list(rename)].rename(columns=rename).copy()
            out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
            for column in ("open", "high", "low", "close", "volume"):
                out[column] = pd.to_numeric(out[column], errors="raise")
            out["volume"] = out["volume"] * 100.0
            out = out.sort_values("date").drop_duplicates("date", keep="last")
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "success",
                    "rows": int(len(out)),
                    "last_date": out["date"].iloc[-1].strftime("%Y-%m-%d"),
                }
            )
            return out, {
                "provider": "akshare_eastmoney_unadjusted",
                "provider_symbol": "002594",
                "adjust": "",
                "attempts": attempts,
            }
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
    return None, {
        "provider": "akshare_eastmoney_unadjusted",
        "provider_symbol": "002594",
        "adjust": "",
        "attempts": attempts,
        "status": "unavailable",
    }


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def _report(bundle: CanonicalBundle, secondary_manifest: dict[str, Any]) -> str:
    manifest = bundle.manifest
    lines = [
        "# BYD canonical adjusted OHLCV v1",
        "",
        "> One primary raw history, one same-provider adjustment-factor history, no row stitching.",
        "",
        "## Identity",
        "",
        f"- Cutoff: `{manifest['cutoff']}`",
        f"- Primary provider: `{manifest['primary_provider']}`",
        f"- Secondary provider: `{manifest['secondary_provider']}`",
        f"- Rows: `{manifest['rows']}`",
        f"- Range: `{manifest['first_date']}` to `{manifest['last_date']}`",
        f"- Raw SHA-256: `{manifest['raw_sha256']}`",
        f"- Factor SHA-256: `{manifest['factor_sha256']}`",
        f"- Adjusted SHA-256: `{manifest['adjusted_sha256']}`",
        f"- Manifest SHA-256: `{manifest['manifest_sha256']}`",
        "",
        "## Price roles",
        "",
        "- Raw OHLCV: execution simulation and corporate-action accounting.",
        "- Cutoff-anchored adjusted OHLCV: features, labels, and return research.",
        "- Adjustment factors: same-provider adjusted close divided by raw close, anchored to 1.0 at cutoff.",
        "- Secondary raw data: audit only; never used to fill primary rows.",
        "",
        "## Quality evidence",
        "",
        f"- Zero-volume sessions: `{manifest['zero_volume_sessions']}`",
        f"- Unexplained factor jumps: `{manifest['unexplained_factor_jumps']}`",
        f"- Common raw-return correlation: `{manifest['common_return_correlation']}`",
        f"- Mean absolute raw-return difference: `{manifest['mean_absolute_return_difference']}`",
        f"- Common sessions over 1% return difference: `{manifest['return_differences_over_1pct']}`",
        f"- Secondary retrieval: `{json.dumps(secondary_manifest, ensure_ascii=False)}`",
        "",
        "## Governance",
        "",
        "- `cross_provider_stitching=false`",
        "- adjusted prices retain at least eight decimal places",
        "- cutoff must exist exactly in the primary raw series",
        "- every raw session must have an explicit adjustment factor",
        "- training and backtests must consume `adjusted_ohlcv.csv` from this bundle",
        "- execution studies must consume `raw_ohlcv.csv` from this bundle",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    try:
        raw, adjusted_close, actions, primary_meta = _fetch_yahoo_primary(
            args.start, args.cutoff
        )
        secondary, secondary_meta = _fetch_akshare_raw(
            args.start, args.cutoff, args.secondary_retries
        )
        bundle = build_canonical_bundle(
            raw_primary=raw,
            provider_adjusted_close=adjusted_close,
            cutoff=args.cutoff,
            primary_provider="yfinance_unadjusted_plus_adj_close",
            raw_secondary=secondary,
            secondary_provider=(
                "akshare_eastmoney_unadjusted" if secondary is not None else None
            ),
            corporate_actions=actions,
            provider_parameters={
                "primary": primary_meta,
                "secondary": secondary_meta,
            },
        )
        _write_frame(output / "raw_ohlcv.csv", bundle.raw_bars)
        _write_frame(output / "adjustment_factors.csv", bundle.adjustment_factors)
        _write_frame(output / "adjusted_ohlcv.csv", bundle.adjusted_bars)
        _write_frame(output / "corporate_actions.csv", bundle.corporate_actions)
        _write_frame(output / "session_audit.csv", bundle.session_audit)
        _write_frame(output / "provider_comparison.csv", bundle.provider_comparison)
        with (output / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(bundle.manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        with (output / "report.md").open("w", encoding="utf-8") as handle:
            handle.write(_report(bundle, secondary_meta))
        print(json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        blocker = {
            "status": "data_blocked",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cutoff": args.cutoff,
        }
        with (output / "data_blocked.json").open("w", encoding="utf-8") as handle:
            json.dump(blocker, handle, ensure_ascii=False, indent=2, sort_keys=True)
        raise


if __name__ == "__main__":
    main()
