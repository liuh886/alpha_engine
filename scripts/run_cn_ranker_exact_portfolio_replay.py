"""Run one exact CN ranker Stage-B portfolio replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn_ranker_exact_portfolio_replay import run_exact_cn_ranker_portfolio_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = run_exact_cn_ranker_portfolio_replay(
        args.spec,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
