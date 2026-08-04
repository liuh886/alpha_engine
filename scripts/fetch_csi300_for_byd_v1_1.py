#!/usr/bin/env python3
"""Fetch exact-cutoff CSI300 OHLCV for the frozen BYD V1.1 contract."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import yaml

from src.research.byd_single_asset_v1 import normalise_ohlcv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/byd_v1_1_xgb.yaml"),
    )
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=2)
    return parser.parse_args()


def _load_contract(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    if not isinstance(contract, dict):
        raise ValueError("contract must be a YAML mapping")
    return contract


def _fetch_akshare(
    *, symbol: str, start: str, cutoff: str
) -> pd.DataFrame:
    import akshare as ak

    raw = ak.index_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start.replace("-", ""),
        end_date=cutoff.replace("-", ""),
    )
    return normalise_ohlcv(raw)


def main() -> None:
    args = _parse_args()
    if args.attempts <= 0:
        raise ValueError("attempts must be positive")
    contract = _load_contract(args.contract)
    data = contract["data"]
    benchmark = contract["benchmark_context"]
    if not isinstance(data, dict) or not isinstance(benchmark, dict):
        raise ValueError("contract data and benchmark_context must be mappings")
    start = str(data["history_start"])
    cutoff = str(data["cutoff"])
    symbol = str(benchmark["provider_symbol"])
    attempts: list[dict[str, object]] = []
    frame: pd.DataFrame | None = None

    for attempt in range(1, args.attempts + 1):
        try:
            candidate = _fetch_akshare(symbol=symbol, start=start, cutoff=cutoff)
            candidate = candidate.loc[: pd.Timestamp(cutoff)]
            if candidate.empty or candidate.index[-1] != pd.Timestamp(cutoff):
                latest = (
                    candidate.index[-1].strftime("%Y-%m-%d")
                    if not candidate.empty
                    else "none"
                )
                raise ValueError(
                    f"expected exact cutoff {cutoff}, latest available date is {latest}"
                )
            frame = candidate
            attempts.append(
                {
                    "provider": "akshare_index_zh_a_hist_eastmoney",
                    "attempt": attempt,
                    "status": "accepted",
                    "rows": int(len(candidate)),
                    "first_date": candidate.index[0].strftime("%Y-%m-%d"),
                    "last_date": candidate.index[-1].strftime("%Y-%m-%d"),
                }
            )
            break
        except Exception as exc:
            attempts.append(
                {
                    "provider": "akshare_index_zh_a_hist_eastmoney",
                    "attempt": attempt,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
            if attempt < args.attempts:
                time.sleep(2.0)

    if frame is None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(
                {
                    "status": "data_blocked",
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "attempts": attempts,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            "CSI300 AkShare exact-cutoff fetch failed: "
            + json.dumps(attempts, ensure_ascii=False, sort_keys=True)
        )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_csv, index=True, date_format="%Y-%m-%d")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "status": "enabled",
                "provider": "akshare_index_zh_a_hist_eastmoney",
                "endpoint": "index_zh_a_hist",
                "symbol": symbol,
                "period": "daily",
                "start": start,
                "cutoff": cutoff,
                "rows": int(len(frame)),
                "first_date": frame.index[0].strftime("%Y-%m-%d"),
                "last_date": frame.index[-1].strftime("%Y-%m-%d"),
                "attempts": attempts,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "provider": "akshare_index_zh_a_hist_eastmoney",
                "symbol": symbol,
                "rows": int(len(frame)),
                "last_date": frame.index[-1].strftime("%Y-%m-%d"),
                "output_csv": str(args.output_csv),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
