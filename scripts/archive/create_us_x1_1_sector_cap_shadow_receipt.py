"""Create one immutable pre-outcome US x1.1 sector-cap shadow receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.us_x1_1_sector_cap_shadow_receipt import create_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract-path",
        type=Path,
        default=Path(
            "configs/research_experiments/us_x1_1_sector_cap_shadow_v1.yaml"
        ),
    )
    parser.add_argument("--score-snapshot", type=Path, required=True)
    parser.add_argument("--provider-snapshot-identity", required=True)
    parser.add_argument("--source-data-cutoff", required=True)
    parser.add_argument("--receipt-created-at-utc", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/shadow/us_x1_1_sector_cap_v1/receipts"),
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=Path("artifacts/shadow/us_x1_1_sector_cap_v1/receipt_index.jsonl"),
    )
    parser.add_argument("--previous-baseline-holdings", type=Path)
    parser.add_argument("--previous-challenger-holdings", type=Path)
    args = parser.parse_args()

    result = create_receipt(
        contract_path=args.contract_path.resolve(),
        score_snapshot_path=args.score_snapshot.resolve(),
        provider_snapshot_identity=args.provider_snapshot_identity,
        source_data_cutoff=args.source_data_cutoff,
        receipt_created_at_utc=args.receipt_created_at_utc,
        repository_commit=args.repository_commit,
        workflow_run_id=args.workflow_run_id,
        output_root=args.output_root.resolve(),
        index_path=args.index_path.resolve(),
        previous_baseline_holdings=(
            args.previous_baseline_holdings.resolve()
            if args.previous_baseline_holdings
            else None
        ),
        previous_challenger_holdings=(
            args.previous_challenger_holdings.resolve()
            if args.previous_challenger_holdings
            else None
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
