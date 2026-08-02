#!/usr/bin/env python3
"""Build or finalize resumable governed US87 price shards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.adapters.polygon_adapter import PolygonAdapter
from src.data.adapters.tiingo_adapter import TiingoAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.us87_professional_prices import (
    build_professional_price_shard,
    finalize_professional_price_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data/us87_professional_prices_v1.yaml"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/data/us87_professional_prices_v1"),
    )
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--shard-index", type=int, default=None)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    if args.finalize == (args.shard_index is not None):
        parser.error("choose exactly one of --shard-index or --finalize")
    if args.finalize:
        payload = finalize_professional_price_bundle(
            root=args.root,
            contract_path=args.contract,
            output_root=args.output_root,
            cutoff=args.cutoff,
        )
    else:
        tiingo = TiingoAdapter()
        polygon = PolygonAdapter()
        payload = build_professional_price_shard(
            root=args.root,
            contract_path=args.contract,
            output_root=args.output_root,
            cutoff=args.cutoff,
            shard_index=int(args.shard_index),
            canonical_adapter=YFinanceAdapter(),
            validation_adapters={
                "tiingo": tiingo if tiingo.client is not None else None,
                "polygon": polygon if polygon.client is not None else None,
            },
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("complete", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
