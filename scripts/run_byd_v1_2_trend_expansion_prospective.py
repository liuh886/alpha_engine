#!/usr/bin/env python3
"""Append and settle the frozen BYD v1.2 trend-expansion shadow ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.byd_v1_2_trend_expansion_prospective import (
    _read_records,
    build_observations,
    persist_store,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--byd-store", type=Path, required=True)
    parser.add_argument("--paired-store", type=Path, required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    existing = _read_records(args.store_dir / "observations")
    new_observations = build_observations(
        baseline_dir=args.baseline_dir,
        byd_store=args.byd_store,
        paired_store=args.paired_store,
        existing_records=existing,
    )
    manifest = persist_store(args.store_dir, new_observations)
    print(
        json.dumps(
            {
                "status": "trend_expansion_prospective_updated",
                "new_observations": len(new_observations),
                "observation_count": manifest["observation_count"],
                "outcome_count": manifest["outcome_count"],
                "first_signal_date": manifest["first_signal_date"],
                "last_signal_date": manifest["last_signal_date"],
                "ledger_sha256": manifest["ledger_sha256"],
                "scorecard_sha256": manifest["scorecard_sha256"],
                "research_only": True,
                "trade_ready": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
