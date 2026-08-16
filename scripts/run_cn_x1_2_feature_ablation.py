#!/usr/bin/env python3
"""Run Issue #966 Phase-2 exact CN x1.2 feature ablation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn_x1_2_feature_ablation import run_cn_x1_2_feature_ablation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    receipt = run_cn_x1_2_feature_ablation(args.spec, output_dir=args.output_dir)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
