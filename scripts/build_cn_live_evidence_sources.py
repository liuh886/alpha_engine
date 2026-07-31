#!/usr/bin/env python3
"""Build BaoStock–Tushare source-bound A-share provider evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn_live_evidence_pipeline import build_cn_live_evidence_sources

DEFAULT_CONTRACT = Path("configs/providers/cn_small_pool_v1_provider_contract.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/cn_small_pool_live_provider")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-06-30")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = build_cn_live_evidence_sources(
        contract_path=args.contract,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision.get("decision") == "cn_provider_contract_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
