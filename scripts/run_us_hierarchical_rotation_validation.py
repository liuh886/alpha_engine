#!/usr/bin/env python3
"""Validate frozen US hierarchical cross-sectional rotation v2 on observed evidence.

Produces after-cost evidence for four predeclared baselines, checks
provider readiness and predeclared gates, and writes a fail-closed decision.
All rows >= 2026-07-01 are reserved and excluded before any computation.

Requires --provider-manifest for evidence-bound provider input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.hierarchical_rotation_validation import (
    run_us_hierarchical_rotation_validation,
)

DEFAULT_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml"
)
DEFAULT_OUTPUT = Path("artifacts/evidence/us_hierarchical_rotation_validation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        required=True,
        help="Long-form OHLCV CSV containing every frozen candidate plus QQQ and ^SOX.",
    )
    parser.add_argument(
        "--provider-manifest",
        type=Path,
        required=True,
        help=(
            "Path to a provider_manifest.json or provider directory.  The manifest "
            "binds the source file identity, calendar coverage, instrument list, "
            "and attestation fields.  Unhashed CSVs are not accepted as authoritative "
            "evidence."
        ),
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_us_hierarchical_rotation_validation(
        spec_path=args.spec,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
        provider_manifest_path=args.provider_manifest,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
