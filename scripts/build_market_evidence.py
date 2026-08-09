#!/usr/bin/env python3
"""Publish one market's governed browser-ready market evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.dashboard.market_evidence import build_market_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--provider-root", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/market_evidence"),
    )
    parser.add_argument(
        "--factor-library",
        type=Path,
        default=Path("configs/factor_libraries/ohlcv.yaml"),
    )
    parser.add_argument(
        "--reuse-root",
        type=Path,
        help=(
            "Reuse a prior market tree only when its content-addressed provider, "
            "formal-package, factor-library and implementation identity matches."
        ),
    )
    args = parser.parse_args()
    result = build_market_evidence(
        market=args.market,
        provider_root=args.provider_root,
        formal_root=args.formal_root,
        output_root=args.output_root,
        factor_library_path=args.factor_library,
        reuse_root=args.reuse_root,
    )
    catalog_path = args.output_root / args.market / "catalog.json"
    if not catalog_path.is_file():
        raise RuntimeError(
            f"Market Evidence build completed without catalog: {catalog_path}"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
