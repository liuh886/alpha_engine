#!/usr/bin/env python3
"""Fetch adjusted OHLCV for the complete frozen US small pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.us_pool_price_snapshot import build_us_pool_price_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/market_snapshots/us_small_pool_v1"),
    )
    parser.add_argument("--requested-through", default=None)
    parser.add_argument("--start-date", default="2024-01-01")
    args = parser.parse_args()
    decision = build_us_pool_price_snapshot(
        output_root=args.output_root,
        requested_through=args.requested_through,
        start_date=args.start_date,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
