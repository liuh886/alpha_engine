#!/usr/bin/env python3
"""Audit canonical BYD bars against independent unadjusted histories.

Independent providers are normalized to the current-share split basis before
comparison. Rare field disagreements are retained in an anomaly ledger and the
corresponding opens are excluded from research labels; no provider row is
silently copied into the canonical primary series.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.data.adapters.base import FetchRequest
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.byd_canonical_bundle import dataframe_sha256

PRICE_COLUMNS = ("open", "high", "low", "close")
OPEN_LEVEL_QUARANTINE = 0.01
MIN_COVERAGE = 0.99
MIN_CLOSE_RETURN_CORRELATION = 0.995
MAX_MEDIAN_OPEN_LEVEL_DIFFERENCE = 1e-5
MAX_P99_OPEN_RETURN_DIFFERENCE = 0.002
MAX_OPEN_QUARANTINE_RATE = 0.01


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    for column in (*PRICE_COLUMNS, "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise").astype(float)
    return out[["date", *PRICE_COLUMNS, "volume"]].sort_values("date").drop_duplicates("date", keep="last")


def _akshare_eastmoney(start: str, cutoff: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_hist(
        symbol="002594",
        period="daily",
        start_date=start.replace("-", ""),
        end_date=cutoff.replace("-", ""),
        adjust="",
    )
    if frame is None or frame.empty:
        raise RuntimeError("empty AkShare/Eastmoney unadjusted history")
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
    out = frame[list(rename)].rename(columns=rename)
    out["volume"] = pd.to_numeric(out["volume"], errors="raise") * 100.0
    return _normalise_columns(out)


def _akshare_sina(start: str, cutoff: str) -> pd.DataFrame:
    import akshare as ak

    frame = ak.stock_zh_a_daily(
        symbol="sz002594",
        start_date=start.replace("-", ""),
        end_date=cutoff.replace("-", ""),
        adjust="",
    )
    if frame is None or frame.empty:
        raise RuntimeError("empty AkShare/Sina unadjusted history")
    out = frame.reset_index() if "date" not in frame.columns else frame.copy()
    out.columns = [str(column).strip().lower() for column in out.columns]
    required = {"date", *PRICE_COLUMNS, "volume"}
    missing = sorted(required - set(out.columns))
    if missing:
        raise RuntimeError(f"AkShare/Sina missing columns: {missing}")
    return _normalise_columns(out)


def _baostock(start: str, cutoff: str) -> pd.DataFrame:
    result = BaoStockAdapter().fetch_daily_bars(
        FetchRequest(symbol="002594", market="cn", start=start, end=cutoff)
    )
    return _normalise_columns(result.df)


def _attempt(
    provider: str,
    fetcher: Callable[[str, str], pd.DataFrame],
    start: str,
    cutoff: str,
    retries: int,
) -> tuple[pd.DataFrame | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, retries + 1):
        try:
            frame = fetcher(start, cutoff)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "success",
                    "rows": int(len(frame)),
                    "first_date": frame["date"].iloc[0].strftime("%Y-%m-%d"),
                    "last_date": frame["date"].iloc[-1].strftime("%Y-%m-%d"),
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


def _to_current_share_basis(
    frame: pd.DataFrame,
    actions: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize an actually unadjusted source to the latest split basis."""

    out = frame.copy(deep=True)
    splits = actions.loc[actions["stock_split"] > 0].sort_values("date")
    for row in splits.itertuples(index=False):
        ratio = float(row.stock_split)
        mask = out["date"] < pd.Timestamp(row.date)
        for column in PRICE_COLUMNS:
            out.loc[mask, column] = out.loc[mask, column] / ratio
        out.loc[mask, "volume"] = out.loc[mask, "volume"] * ratio
    return out


def _audit_provider(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    provider: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    merged = primary.merge(
        secondary,
        on="date",
        how="inner",
        suffixes=("_primary", "_secondary"),
        validate="one_to_one",
    ).sort_values("date")
    for column in PRICE_COLUMNS:
        merged[f"{column}_level_abs_pct_difference"] = (
            merged[f"{column}_primary"] / merged[f"{column}_secondary"] - 1.0
        ).abs()
        merged[f"{column}_return_primary"] = merged[f"{column}_primary"].pct_change()
        merged[f"{column}_return_secondary"] = merged[f"{column}_secondary"].pct_change()
        merged[f"{column}_return_abs_difference"] = (
            merged[f"{column}_return_primary"]
            - merged[f"{column}_return_secondary"]
        ).abs()

    valid_open = merged.dropna(
        subset=["open_return_primary", "open_return_secondary"]
    )
    valid_close = merged.dropna(
        subset=["close_return_primary", "close_return_secondary"]
    )
    coverage = len(merged) / len(primary)
    quarantine = (
        (merged["open_level_abs_pct_difference"] > OPEN_LEVEL_QUARANTINE)
        | (merged["volume_primary"] <= 0)
        | (merged["volume_secondary"] <= 0)
    )
    summary = {
        "provider": provider,
        "rows": int(len(secondary)),
        "common_rows": int(len(merged)),
        "coverage": float(coverage),
        "open_return_correlation": float(
            valid_open["open_return_primary"].corr(
                valid_open["open_return_secondary"]
            )
        ),
        "close_return_correlation": float(
            valid_close["close_return_primary"].corr(
                valid_close["close_return_secondary"]
            )
        ),
        "median_open_level_difference": float(
            merged["open_level_abs_pct_difference"].median()
        ),
        "p99_open_return_difference": float(
            valid_open["open_return_abs_difference"].quantile(0.99)
        ),
        "mean_open_return_difference": float(
            valid_open["open_return_abs_difference"].mean()
        ),
        "open_level_differences_over_1pct": int(
            (merged["open_level_abs_pct_difference"] > 0.01).sum()
        ),
        "open_quarantine_rows": int(quarantine.sum()),
        "open_quarantine_rate": float(quarantine.mean()),
    }
    summary["quality_pass"] = bool(
        summary["coverage"] >= MIN_COVERAGE
        and summary["close_return_correlation"] >= MIN_CLOSE_RETURN_CORRELATION
        and summary["median_open_level_difference"]
        <= MAX_MEDIAN_OPEN_LEVEL_DIFFERENCE
        and summary["p99_open_return_difference"]
        <= MAX_P99_OPEN_RETURN_DIFFERENCE
        and summary["open_quarantine_rate"] <= MAX_OPEN_QUARANTINE_RATE
    )
    merged["provider"] = provider
    merged["open_quarantined"] = quarantine
    return merged, summary


def main() -> None:
    args = _parse_args()
    root = args.canonical_dir
    primary = _normalise_columns(
        pd.read_csv(root / "raw_ohlcv.csv", parse_dates=["date"])
    )
    actions = pd.read_csv(root / "corporate_actions.csv", parse_dates=["date"])
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start = str(manifest["first_date"])
    cutoff = str(manifest["cutoff"])

    fetchers: dict[str, Callable[[str, str], pd.DataFrame]] = {
        "akshare_eastmoney_unadjusted": _akshare_eastmoney,
        "akshare_sina_unadjusted": _akshare_sina,
        "baostock_adjustflag_3_unadjusted": _baostock,
    }
    attempts_by_provider: dict[str, Any] = {}
    comparisons: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    successful_frames: dict[str, pd.DataFrame] = {}
    for provider, fetcher in fetchers.items():
        frame, attempts = _attempt(provider, fetcher, start, cutoff, args.retries)
        attempts_by_provider[provider] = attempts
        if frame is None:
            continue
        normalized = _to_current_share_basis(frame, actions)
        comparison, summary = _audit_provider(primary, normalized, provider)
        comparisons.append(comparison)
        summaries.append(summary)
        successful_frames[provider] = normalized

    (root / "secondary_provider_attempts.json").write_text(
        json.dumps(attempts_by_provider, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if not summaries:
        raise RuntimeError("no independent unadjusted BYD source was available")

    summary_frame = pd.DataFrame(summaries).sort_values(
        ["quality_pass", "close_return_correlation", "p99_open_return_difference"],
        ascending=[False, False, True],
    )
    summary_frame.to_csv(
        root / "provider_audit_summary.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    all_comparisons = pd.concat(comparisons, ignore_index=True)
    all_comparisons.to_csv(
        root / "provider_comparison.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    passed = summary_frame.loc[summary_frame["quality_pass"]]
    if passed.empty:
        raise RuntimeError(
            "no independent provider passed robust canonical audit: "
            + summary_frame.to_json(orient="records")
        )

    selected_provider = str(passed.iloc[0]["provider"])
    selected = successful_frames[selected_provider]
    selected.to_csv(
        root / "secondary_raw_split_normalized.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    selected_comparison = all_comparisons.loc[
        all_comparisons["provider"] == selected_provider
    ].copy()
    quarantined = selected_comparison.loc[
        selected_comparison["open_quarantined"],
        [
            "date",
            "open_primary",
            "open_secondary",
            "open_level_abs_pct_difference",
            "volume_primary",
            "volume_secondary",
            "provider",
        ],
    ].copy()
    quarantined["reason"] = np.select(
        [
            quarantined["open_level_abs_pct_difference"] > OPEN_LEVEL_QUARANTINE,
            quarantined["volume_primary"] <= 0,
            quarantined["volume_secondary"] <= 0,
        ],
        ["open_level_disagreement", "primary_zero_volume", "secondary_zero_volume"],
        default="multiple_or_other",
    )
    quarantined.to_csv(
        root / "quarantined_open_dates.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )

    session_path = root / "session_audit.csv"
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    common_dates = set(selected_comparison["date"])
    quarantined_dates = set(pd.to_datetime(quarantined["date"]))
    sessions["independent_raw_status"] = np.where(
        sessions["date"].isin(common_dates), "confirmed", "missing_secondary"
    )
    sessions["open_research_eligible"] = (
        sessions["date"].isin(common_dates)
        & ~sessions["date"].isin(quarantined_dates)
        & (sessions["volume"] > 0)
    )
    sessions.to_csv(
        session_path,
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )

    selected_summary = passed.iloc[0].to_dict()
    manifest.update(
        {
            "secondary_provider": selected_provider,
            "secondary_raw_sha256": dataframe_sha256(selected),
            "provider_comparison_sha256": dataframe_sha256(all_comparisons),
            "provider_audit_summary_sha256": dataframe_sha256(summary_frame),
            "secondary_provider_attempts": attempts_by_provider,
            "secondary_quality": selected_summary,
            "quarantined_open_rows": int(len(quarantined)),
            "open_label_policy": "entry_and_exit_open_must_be_independently_confirmed_and_not_quarantined",
            "research_eligible_open_rows": int(
                sessions["open_research_eligible"].sum()
            ),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with (root / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\n## Independent raw-source reconciliation\n\n")
        handle.write(f"- Selected provider: `{selected_provider}`\n")
        handle.write(
            f"- Close-return correlation: `{selected_summary['close_return_correlation']:.8f}`\n"
        )
        handle.write(
            f"- Median open-level difference: `{selected_summary['median_open_level_difference']:.10f}`\n"
        )
        handle.write(
            f"- 99th percentile open-return difference: `{selected_summary['p99_open_return_difference']:.8f}`\n"
        )
        handle.write(f"- Quarantined open rows: `{len(quarantined)}`\n")
        handle.write(
            "- Quarantined opens are not replaced; any 10-session label using one is removed.\n"
        )

    print(
        json.dumps(
            {
                "selected_provider": selected_provider,
                "quality_pass": True,
                "close_return_correlation": selected_summary[
                    "close_return_correlation"
                ],
                "p99_open_return_difference": selected_summary[
                    "p99_open_return_difference"
                ],
                "quarantined_open_rows": int(len(quarantined)),
                "research_eligible_open_rows": int(
                    sessions["open_research_eligible"].sum()
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
