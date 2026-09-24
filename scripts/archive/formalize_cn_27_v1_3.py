"""Create CN_27 V1.3 only from a fully passed prospective evidence package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn27_v1_3_formalize import formalize_v1_3


DEFAULT_CONTRACT = Path(
    "configs/research_experiments/cn_27_v1_3_formalization_v1.yaml"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = formalize_v1_3(
        args.contract,
        args.evidence_manifest,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
