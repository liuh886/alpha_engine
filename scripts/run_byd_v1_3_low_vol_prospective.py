#!/usr/bin/env python3
"""Append the frozen BYD v1.3 low-vol prospective shadow store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.byd_v1_3_low_vol_prospective import (
    build_observations,
    persist_store,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-store", type=Path, required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    return parser.parse_args()


def _existing(store_dir: Path) -> list[dict[str, object]]:
    observation_dir = store_dir / "observations"
    if not observation_dir.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(observation_dir.glob("*.json"))
    ]


def main() -> None:
    args = _parse_args()
    new_observations = build_observations(
        source_store=args.source_store,
        existing_records=_existing(args.store_dir),
    )
    manifest = persist_store(args.store_dir, new_observations)
    print(
        json.dumps(
            {
                "status": "byd_v1_3_low_vol_prospective_updated",
                "new_observations": len(new_observations),
                "observation_count": manifest["observation_count"],
                "prospective_observation_count": manifest[
                    "prospective_observation_count"
                ],
                "outcome_count": manifest["outcome_count"],
                "last_signal_date": manifest["last_signal_date"],
                "ledger_sha256": manifest["ledger_sha256"],
                "scorecard_sha256": manifest["scorecard_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
