"""Run one exact CN ranker portfolio replay or final certification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.research.cn_cal_deeper_portfolio_mapping_replay import (
    run_cal_deeper_portfolio_mapping_replay,
)
from src.research.cn_rank_blend_portfolio_replay import run_cn_rank_blend_portfolio_replay
from src.research.cn_ranker_exact_portfolio_replay import run_exact_cn_ranker_portfolio_replay
from src.research.cn_x1_2_certification import run_cn_x1_2_certification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CN replay spec must be a YAML mapping")
    if payload.get("certification") is not None:
        receipt = run_cn_x1_2_certification(
            args.spec,
            output_dir=args.output_dir,
        )
    elif payload.get("rank_blend_diagnostic") is not None:
        receipt = run_cn_rank_blend_portfolio_replay(
            args.spec,
            output_dir=args.output_dir,
        )
    elif payload.get("portfolio_mapping_diagnostic") is not None:
        receipt = run_cal_deeper_portfolio_mapping_replay(
            args.spec,
            output_dir=args.output_dir,
        )
    else:
        receipt = run_exact_cn_ranker_portfolio_replay(
            args.spec,
            output_dir=args.output_dir,
        )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
