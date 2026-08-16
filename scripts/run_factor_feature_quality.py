"""Run Issue #966 Gate-1 structural factor quality on a governed Qlib provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.factor_feature_quality import run_factor_feature_quality_from_files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Research paradigm YAML")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument(
        "--provider-dir",
        type=Path,
        default=None,
        help="Exact-cutoff Qlib provider; defaults to the market provider path",
    )
    parser.add_argument("--output", type=Path, required=True, help="Feature-quality receipt JSON")
    args = parser.parse_args()

    report = run_factor_feature_quality_from_files(
        args.spec,
        repository_root=args.root,
        provider_dir=args.provider_dir,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["gate1_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
