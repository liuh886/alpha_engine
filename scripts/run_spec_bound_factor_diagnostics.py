"""Run spec-bound single-factor diagnostics on accepted real-market data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.spec_bound_factor_diagnostics import run_factor_diagnostics_from_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Research paradigm YAML")
    parser.add_argument(
        "--acceptance",
        type=Path,
        required=True,
        help="Accepted real_market_acceptance.json",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument(
        "--provider-dir",
        type=Path,
        default=None,
        help="Must match the provider recorded in the acceptance report",
    )
    parser.add_argument("--output", type=Path, default=None, help="Diagnostic JSON path")
    args = parser.parse_args()

    report = run_factor_diagnostics_from_files(
        args.spec,
        args.acceptance,
        repository_root=args.root,
        provider_dir=args.provider_dir,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
