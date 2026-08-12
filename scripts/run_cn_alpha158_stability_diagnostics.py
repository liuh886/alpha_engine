"""Run the governed CN Alpha158 cross-window stability diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.alpha158_stability_diagnostics import run_alpha158_stability_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_alpha158_stability_diagnostics(
        args.spec,
        args.bundle_root,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "experiment_id": report["experiment_id"],
                "status": report["status"],
                "classification_counts": report["classification_counts"],
                "cross_window_stable_factor_ids": report[
                    "cross_window_stable_factor_ids"
                ],
                "repair_2024_factor_ids": report["repair_2024_factor_ids"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
