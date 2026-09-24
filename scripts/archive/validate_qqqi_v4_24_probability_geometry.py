from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_adjacent_path_utility_v4_24_research.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_xgb_adjacent_path_utility_v4_24_research"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    scores = pd.read_csv(args.output_dir / "oof_edge_scores.csv")
    minimum = int(contract["model"]["minimum_unique_test_probabilities"])
    edges = [str(item["edge"]) for item in contract["states"]["edges"]]
    rows: list[dict[str, object]] = []
    for fold, table in scores.groupby("fold"):
        for edge in edges:
            unique = int(table[f"prob_{edge}"].nunique(dropna=True))
            rows.append(
                {
                    "fold": fold,
                    "edge": edge,
                    "unique_probabilities": unique,
                    "minimum_required": minimum,
                    "passed": unique >= minimum,
                }
            )
    audit = pd.DataFrame(rows)
    audit.to_csv(args.output_dir / "probability_geometry_audit.csv", index=False)
    passed = bool(audit["passed"].all())
    print(
        json.dumps(
            {
                "passed": passed,
                "minimum_unique_test_probabilities": minimum,
                "cells": rows,
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
