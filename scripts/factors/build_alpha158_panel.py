#!/usr/bin/env python3
"""Materialize a governed Alpha158 panel from one promoted Qlib provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.factors.panel import build_alpha158_panel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data/alpha158_panel_v1.yaml"),
    )
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    payload = build_alpha158_panel(
        root=args.root,
        contract_path=args.contract,
        provider_uri=args.provider_uri,
        market=args.market,
        start=args.start,
        cutoff=args.cutoff,
        output_root=args.output_root,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") in {"ready", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
