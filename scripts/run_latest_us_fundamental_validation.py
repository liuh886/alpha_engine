#!/usr/bin/env python3
"""Refresh US sources and run validation on the active selected pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.selected_us_fundamental_validation import (
    run_selected_us_fundamental_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requested-through", default=None)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/evidence/selected_us_fundamental_validation_v2"),
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("artifacts/market_snapshots/us_small_pool_v2"),
    )
    parser.add_argument(
        "--registry-db",
        type=Path,
        default=Path("artifacts/factor_registry.db"),
    )
    args = parser.parse_args()
    result = run_selected_us_fundamental_validation(
        output_root=args.output_root,
        snapshot_root=args.snapshot_root,
        registry_db=args.registry_db,
        requested_through=args.requested_through,
        start_date=args.start_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
