"""Build the frozen CN x1.2 reporting-only score ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn_x1_2_prospective import build_cn_x1_2_prospective_ledger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_cn_x1_2_prospective_ledger(
        repository_root=args.repository_root.resolve(),
        provider_dir=args.provider_dir.resolve(),
        cutoff=args.cutoff,
        output=args.output.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
