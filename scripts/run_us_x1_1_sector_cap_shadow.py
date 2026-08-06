#!/usr/bin/env python3
"""Prospective shadow validation for frozen US x1.1 sector-cap contract.

Records daily baseline (Top-15 equal-weight) vs challenger (rank-aware
sector-cap Top-15) comparisons in an append-only prospective store.

The first eligible signal date must be strictly after 2026-08-03.
No historical backfill may be presented as prospective evidence.

Usage:
  python scripts/run_us_x1_1_sector_cap_shadow.py \
    --store-dir data/research/us_x1_1_sector_cap_shadow \
    --as-of 2026-08-06
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "us_x1_1_sector_cap_shadow_v1"
FIRST_ELIGIBLE_DATE = "2026-08-04"
ELIGIBLE_HORIZON = 10  # ten-session holding period
MAX_SECTOR_COUNT = 4    # sector cap
TARGET_COUNT = 15       # Top-15 selection


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-dir", type=Path, required=True)
    p.add_argument("--as-of", type=str, required=True,
                   help="Signal date (YYYY-MM-DD)")
    return p.parse_args()


def build_store(store_dir: Path) -> dict:
    """Initialize or load the append-only prospective store."""
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "observations").mkdir(exist_ok=True)

    manifest_path = store_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "first_eligible_date": FIRST_ELIGIBLE_DATE,
        "eligible_horizon": ELIGIBLE_HORIZON,
        "baseline_model": "us_x1_1",
        "baseline_contract": "Top-15 equal weight",
        "challenger_contract": "rank-aware sector-cap Top-15",
        "observation_count": 0,
        "last_signal_date": None,
        "research_only": True,
        "trade_ready": False,
        "append_only": True,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def record_observation(store_dir: Path, signal_date: str, manifest: dict):
    """Record one prospective shadow observation.

    Currently a scaffolding placeholder. When the US x1.1 scoring pipeline
    is available, this function will:
    1. Fetch latest US87 pool data
    2. Compute US x1.1 scores (formal features, XGBoost parameters)
    3. Generate baseline Top-15 and challenger sector-cap Top-15
    4. Compare weights and record both portfolios
    """
    obs_path = store_dir / "observations" / f"{signal_date}.json"

    if obs_path.exists():
        print(f"Observation {signal_date} already exists — skipping")
        return

    observation = {
        "schema_version": SCHEMA_VERSION,
        "signal_date": signal_date,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_scoring_pipeline",
        "baseline_top15": None,
        "challenger_sector_cap_top15": None,
        "eligible_names": 87,
        "note": "Scaffolding — scoring pipeline integration pending.",
        "research_only": True,
        "trade_ready": False,
    }

    obs_path.write_text(
        json.dumps(observation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest["observation_count"] = manifest.get("observation_count", 0) + 1
    manifest["last_signal_date"] = signal_date
    (store_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Recorded shadow observation: {signal_date}")


def main():
    args = parse_args()
    store_dir = args.store_dir.resolve()
    signal_date = args.as_of

    if signal_date <= FIRST_ELIGIBLE_DATE:
        print(f"Date {signal_date} is not after first eligible date "
              f"{FIRST_ELIGIBLE_DATE} — skipping")
        return

    manifest = build_store(store_dir)
    record_observation(store_dir, signal_date, manifest)


if __name__ == "__main__":
    main()
