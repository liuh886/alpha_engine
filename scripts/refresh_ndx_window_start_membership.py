"""Refresh committed NDX window-start membership from the official Nasdaq endpoint.

This CLI fetches the Nasdaq-100 (NDX) weighting data from the official Nasdaq
indexes endpoint and updates the committed membership snapshot.  It uses the
same POST endpoint Microsoft Qlib relies on for index constituent data.

The endpoint returns a JSON object whose ``aaData`` field contains holding
objects.  Each holding object uses the ``Symbol`` key (capital S) for the
ticker.  Results are written as a deterministic committed membership snapshot
under
``configs/research_universes/ndx_window_start_membership.json`` with per-date
sorted symbols, counts, and SHA-256 membership hashes.

This script is **never called in CI**.  Snapshots are committed manually from
a machine with network access to the Nasdaq indexes endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import requests

SOURCE_URL_TEMPLATE = (
    "https://indexes.nasdaqomx.com/Index/WeightingData"
    "?id=NDX&tradeDate={date}T00%3A00%3A00.000&timeOfDay=SOD"
)
DEFAULT_OUT = Path("configs/research_universes/ndx_window_start_membership.json")
DEFAULT_SNAPSHOT_DATES = [
    "2021-01-04",
    "2021-07-01",
    "2022-01-03",
    "2022-07-01",
    "2023-01-03",
    "2023-07-03",
    "2024-01-02",
    "2024-07-01",
    "2025-01-02",
    "2025-07-01",
]


def _sha256_symbols(symbols: list[str]) -> str:
    """Deterministic SHA-256 of sorted, pipe-joined symbol list."""
    canonical = "|".join(sorted(symbols)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def fetch_ndx_symbols(trade_date: str) -> list[str]:
    """Fetch NDX constituent tickers from the official Nasdaq endpoint.

    Parameters
    ----------
    trade_date
        ISO date string (YYYY-MM-DD) for the snapshot.

    Returns
    -------
    list[str]
        Sorted list of unique ticker symbols returned by the endpoint.

    Raises
    ------
    requests.RequestException
        On network or HTTP errors.
    ValueError
        If the response cannot be parsed or contains no tickers.
    """
    url = SOURCE_URL_TEMPLATE.format(date=trade_date)
    resp = requests.post(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("aaData"), list):
        raise ValueError("Nasdaq response must contain an aaData list")

    symbols: list[str] = []
    for item in data["aaData"]:
        if isinstance(item, dict):
            ticker = item.get("Symbol")
            if ticker and isinstance(ticker, str):
                symbols.append(ticker.strip().upper())
    if not symbols:
        raise ValueError(f"no tickers found in response for {trade_date}")
    return sorted(set(symbols))


def build_snapshot(dates: list[str], *, url_template: str) -> dict[str, Any]:
    """Fetch NDX symbols for each date and build the membership snapshot."""
    snapshot_dates: list[dict[str, Any]] = []
    for date_str in dates:
        print(f"  fetching {date_str} ...")
        symbols = fetch_ndx_symbols(date_str)
        sorted_symbols = sorted(set(s.strip().upper() for s in symbols if s.strip()))
        snapshot_dates.append({
            "date": date_str,
            "symbols": sorted_symbols,
            "count": len(sorted_symbols),
            "sha256_membership_hash": _sha256_symbols(sorted_symbols),
        })

    return {
        "schema_version": "1.0",
        "index": "NDX",
        "index_name": "NASDAQ-100",
        "source_url_template": url_template,
        "source_notes": (
            "Official Nasdaq index weighting data endpoint.  "
            "POST with Content-Type: application/x-www-form-urlencoded.  "
            "Response is a JSON object whose aaData field contains holdings."
        ),
        "snapshot_dates": snapshot_dates,
        "refresh_command": (
            "uv run python scripts/refresh_ndx_window_start_membership.py"
            " --out configs/research_universes/ndx_window_start_membership.json"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dates",
        nargs="+",
        default=DEFAULT_SNAPSHOT_DATES,
        help="Trade dates to fetch (ISO format, YYYY-MM-DD).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--url-template",
        default=SOURCE_URL_TEMPLATE,
        help="Nasdaq endpoint URL template with {date} placeholder.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print("Refreshing NDX window-start membership snapshot ...")
    data = build_snapshot(args.dates, url_template=args.url_template)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {args.out}")
    for d in data["snapshot_dates"]:
        print(f"  {d['date']}: {d['count']} symbols  sha256={d['sha256_membership_hash']}")
    print("\nDone (research only — never called in CI)")


if __name__ == "__main__":
    main()
