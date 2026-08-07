#!/usr/bin/env python3
"""Publish the governed Strategy Console operations read model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.strategy_operations import (
    build_operations_payload,
    validate_operations_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formal-catalog",
        type=Path,
        default=Path("data/research/formal_model_runs/catalog.json"),
    )
    parser.add_argument(
        "--ledger-root",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/strategy_operations/snapshots.json"),
    )
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()

    payload = build_operations_payload(
        formal_catalog=args.formal_catalog,
        ledger_root=args.ledger_root,
        generated_at=args.generated_at,
    )
    validate_operations_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
