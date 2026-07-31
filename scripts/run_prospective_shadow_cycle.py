"""Run one governed prospective shadow decision cycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decision_support.prospective_shadow_cycle import run_prospective_shadow_cycle

DEFAULT_CUTOVER = Path("configs/operations/prospective_shadow_cutover_v1.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--registry-db", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--cutover-contract", type=Path, default=DEFAULT_CUTOVER)
    parser.add_argument("--factor-scores", type=Path, default=None)
    args = parser.parse_args()

    manifest = run_prospective_shadow_cycle(
        market=args.market,
        as_of_date=args.as_of_date,
        prices_csv=args.prices_csv,
        spec_path=args.spec,
        registry_db=args.registry_db,
        ledger_dir=args.ledger_dir,
        workspace_dir=args.workspace_dir,
        cutover_contract=args.cutover_contract,
        factor_scores_path=args.factor_scores,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
