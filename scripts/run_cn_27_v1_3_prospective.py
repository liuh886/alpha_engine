"""Run the frozen CN_27 V1.3 prospective validation gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn27_v1_3_prospective import run_prospective_validation


DEFAULT_CONTRACT = Path(
    "configs/research_experiments/cn_27_v1_3_prospective_validation_v1.yaml"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    result = run_prospective_validation(
        args.contract,
        args.source_manifest,
        output_root=args.output_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
