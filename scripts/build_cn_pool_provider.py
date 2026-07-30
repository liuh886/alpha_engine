from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.research.cn_pool_provider import build_cn_pool_provider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a manifest-bound provider artifact for cn_small_pool_v1."
    )
    parser.add_argument(
        "--contract",
        default="configs/providers/cn_small_pool_v1_provider_contract.yaml",
    )
    parser.add_argument("--bars-csv", required=True)
    parser.add_argument("--status-csv", required=True)
    parser.add_argument("--calendar-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = build_cn_pool_provider(
        contract_path=args.contract,
        bars_csv=args.bars_csv,
        status_csv=args.status_csv,
        calendar_csv=args.calendar_csv,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
