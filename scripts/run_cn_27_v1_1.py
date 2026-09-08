#!/usr/bin/env python3
"""Run the frozen CN_27 V1.1 evidence build."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn27_v1_1 import run_cn27_v1_1_evidence


DEFAULT_SPEC = Path("configs/research_paradigms/cn_27_v1_1.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_cn27_v1_1_evidence(args.spec, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
