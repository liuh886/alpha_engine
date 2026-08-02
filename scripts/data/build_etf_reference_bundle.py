#!/usr/bin/env python3
"""Build the governed QQQ/QQQI/TQQQ reference-data bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.etf_reference_bundle import build_etf_reference_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/data/qqqi_qqq_tqqq_reference_bundle_v1"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--require-professional",
        action="store_true",
        help="Fail unless Tiingo and independent reconciliation pass for all three ETFs.",
    )
    args = parser.parse_args()

    manifest = build_etf_reference_bundle(
        contract_path=args.contract,
        output_root=args.output_root,
        end=args.end_date,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest.get("strategy_data_ready") is not True:
        return 2
    if args.require_professional and manifest.get("professional_source_ready") is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
