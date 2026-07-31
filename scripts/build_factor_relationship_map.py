#!/usr/bin/env python3
"""Build factor correlations, overlaps, and redundancy clusters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.factor_relationship_map import build_factor_relationship_map

DEFAULT_CONTRACT = Path("configs/factor_knowledge/relationship_map_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/factor_knowledge/relationship_map")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--registry-db", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = build_factor_relationship_map(
        contract_path=args.contract,
        input_manifest_path=args.input_manifest,
        registry_db=args.registry_db,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
