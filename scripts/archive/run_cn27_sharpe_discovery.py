#!/usr/bin/env python3
"""Run the frozen CN_27 Sharpe-1 discovery screen without opening locked test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn27_sharpe_discovery import run_discovery_screen


DEFAULT_SPEC = Path("configs/research_experiments/cn_27_sharpe_1_discovery_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/cn_27_sharpe_1_discovery_v1/screen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_discovery_screen(args.spec, args.output_dir)
    print(json.dumps(decision, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
