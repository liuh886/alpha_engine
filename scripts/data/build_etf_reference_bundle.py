#!/usr/bin/env python3
"""Build the governed QQQ/QQQI/TQQQ reference-data bundle."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.data.etf_reference_bundle import build_etf_reference_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data/qqqi_qqq_tqqq_reference_research_v2.yaml"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/data/qqqi_qqq_tqqq_reference_research_v2"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--require-source-policy", choices=["yahoo_research_v2", "professional_primary_v1"])
    parser.add_argument(
        "--require-professional",
        action="store_true",
        help="Fail unless Tiingo and independent reconciliation pass for all three ETFs.",
    )
    args = parser.parse_args()
    if args.end_date is None:
        from src.research.market_session_clock import completed_market_date, exchange_sessions

        today = datetime.now(timezone.utc).date()
        completed = completed_market_date("us", today.isoformat())
        args.end_date = exchange_sessions("us", (today - timedelta(days=14)).isoformat(), completed)[-1]

    manifest = build_etf_reference_bundle(
        contract_path=args.contract,
        output_root=args.output_root,
        end=args.end_date,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest.get("strategy_data_ready") is not True:
        return 2
    if args.require_source_policy and manifest.get("source_policy") != args.require_source_policy:
        return 4
    if args.require_professional and manifest.get("professional_source_ready") is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
