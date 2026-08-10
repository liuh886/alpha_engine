#!/usr/bin/env python3
"""Append the frozen BYD recovery event lifecycle prospective shadow store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.byd_recovery_event_prospective import (
    build_observations,
    persist_store,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--byd-store", type=Path, required=True)
    parser.add_argument("--paired-store", type=Path, required=True)
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
    existing = _existing(args.store_dir)
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
                "status": "byd_recovery_event_prospective_updated",
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
