"""Run one exact CN ranker Stage-B portfolio replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.research.cn_ranker_exact_portfolio_replay import run_exact_cn_ranker_portfolio_replay
from src.research.cn_x1_2_breadth_scaled_development import (
    DEVELOPMENT_RUNNER_ID as SCALED_DEVELOPMENT_RUNNER_ID,
    run_breadth_scaled_development,
)
from src.research.cn_x1_2_breadth_veto_development import (
    DEVELOPMENT_RUNNER_ID,
    run_breadth_veto_development,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        help="Shared hash-bound score checkpoint root for the #954 route.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Explicitly resume validated #954 score checkpoints and run state.",
    )
    args = parser.parse_args()

    payload = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CN replay spec must be a YAML mapping")
    scaled_route = payload.get("development_runner") == SCALED_DEVELOPMENT_RUNNER_ID
    if (args.resume or args.checkpoint_dir is not None) and not scaled_route:
        raise ValueError("--resume/--checkpoint-dir are supported only by the #954 route")

    if payload.get("development_runner") == DEVELOPMENT_RUNNER_ID:
        receipt = run_breadth_veto_development(
            args.spec,
            output_dir=args.output_dir,
        )
    elif scaled_route:
        receipt = run_breadth_scaled_development(
            args.spec,
            output_dir=args.output_dir,
            checkpoint_dir=args.checkpoint_dir,
            resume=args.resume,
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
