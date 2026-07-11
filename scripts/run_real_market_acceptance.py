"""Run fail-closed real-market data acceptance for one research paradigm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.real_market_acceptance import run_real_market_acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Research paradigm YAML")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--provider-dir", type=Path, default=None, help="Qlib provider directory")
    parser.add_argument("--csv-dir", type=Path, default=None, help="Source OHLCV CSV directory")
    parser.add_argument("--output", type=Path, default=None, help="Acceptance report JSON path")
    args = parser.parse_args()

    report = run_real_market_acceptance(
        args.spec,
        root=args.root,
        provider_dir=args.provider_dir,
        csv_dir=args.csv_dir,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
