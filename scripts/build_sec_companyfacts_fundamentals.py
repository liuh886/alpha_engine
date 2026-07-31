#!/usr/bin/env python3
"""Build SEC Company Facts fundamentals for the frozen US pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.sec_companyfacts_fundamentals import (
    build_sec_companyfacts_fundamentals,
)

DEFAULT_CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/sec_companyfacts_fundamentals_v1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = build_sec_companyfacts_fundamentals(
        contract_path=args.contract,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision.get("factor_ready_count", 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
