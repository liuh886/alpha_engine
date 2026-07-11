"""Run real-market acceptance followed by diagnostic-only factor research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.real_market_research_pipeline import run_real_market_research_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Canonical research paradigm YAML")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--provider-dir", type=Path, default=None, help="Qlib provider directory")
    parser.add_argument("--csv-dir", type=Path, default=None, help="Source OHLCV CSV directory")
    parser.add_argument("--output-dir", type=Path, default=None, help="Research artifact directory")
    args = parser.parse_args()

    manifest = run_real_market_research_pipeline(
        args.spec,
        repository_root=args.root,
        provider_dir=args.provider_dir,
        csv_dir=args.csv_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
