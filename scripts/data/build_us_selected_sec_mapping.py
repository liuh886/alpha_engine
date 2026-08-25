#!/usr/bin/env python3
"""Build an exact reviewable US87 ticker-to-CIK mapping from SEC company tickers."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import yaml

from src.data.fundamentals.sec_companyfacts import resolve_sec_user_agent
from src.data.sec_transport import SecTransport, read_sec_json_response

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool",
        type=Path,
        default=Path("configs/research_universes/us_selected_equities_v2.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/data/us_selected_equities_sec_cik_v3.yaml"),
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="Optional override; a declared project identity is used by default.",
    )
    args = parser.parse_args()

    pool = yaml.safe_load(args.pool.read_text(encoding="utf-8"))
    symbols = [str(value).strip().upper() for value in pool.get("symbols", [])]
    expected = int(pool.get("candidate_count", 0))
    if len(symbols) != expected or len(set(symbols)) != expected:
        raise SystemExit("selected pool identity is not exact")

    request = urllib.request.Request(
        SEC_TICKERS_URL,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": resolve_sec_user_agent(args.user_agent),
        },
    )
    transport = SecTransport.from_env()
    with transport.open(request, timeout=30) as response:
        payload = read_sec_json_response(response)
    lookup = {
        str(row["ticker"]).strip().upper(): {
            "cik": str(int(row["cik_str"])).zfill(10),
            "title": str(row.get("title", "")).strip(),
        }
        for row in payload.values()
        if isinstance(row, dict) and row.get("ticker") and row.get("cik_str") is not None
    }
    mapped = {symbol: lookup[symbol] for symbol in symbols if symbol in lookup}
    missing = [symbol for symbol in symbols if symbol not in lookup]
    output = {
        "schema_version": "1.1",
        "mapping_id": "us_selected_equities_sec_cik_v3_candidate",
        "status": "ready_for_review" if not missing else "partial_requires_review",
        "pool_id": pool.get("pool_id"),
        "source": {
            "authority": "U.S. Securities and Exchange Commission",
            "url": SEC_TICKERS_URL,
            "declared_user_agent": True,
            "secret_required": False,
            "transport": transport.evidence(),
        },
        "expected_symbol_count": expected,
        "mapped_symbol_count": len(mapped),
        "missing_symbols": missing,
        "symbols": mapped,
        "governance": {
            "runtime_symbol_substitution_allowed": False,
            "manual_review_required_before_authoritative_use": True,
            "TIGO_and_TYGO_must_remain_distinct": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(output, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(yaml.safe_dump(output, sort_keys=False, allow_unicode=True))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
