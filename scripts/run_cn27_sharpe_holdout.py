#!/usr/bin/env python3
"""Open the CN_27 Sharpe discovery locked test exactly once after sealed selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn27_sharpe_holdout import run_locked_holdout


DEFAULT_SPEC = Path("configs/research_experiments/cn_27_sharpe_1_discovery_v1.yaml")
DEFAULT_SCREEN = Path("artifacts/evidence/cn_27_sharpe_1_discovery_v1/screen")
DEFAULT_OUTPUT = Path("artifacts/evidence/cn_27_sharpe_1_discovery_v1/holdout")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--screen-dir", type=Path, default=DEFAULT_SCREEN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_locked_holdout(args.spec, args.screen_dir, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
