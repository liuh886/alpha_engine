"""Finalize one research run into the canonical PromotionDecision artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.promotion_decision import finalize_promotion_decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--subject-id", default=None)
    args = parser.parse_args()
    print(
        json.dumps(
            finalize_promotion_decision(
                args.run_dir,
                subject_id=args.subject_id,
            ),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
