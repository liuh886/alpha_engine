#!/usr/bin/env python3
"""Publish the governed Strategy Console operations read model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.formal_evidence_standard import validate_formal_catalog_evidence
from src.artifacts.strategy_operations import (
    build_operations_payload,
    validate_operations_payload,
    write_operations_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formal-catalog",
        type=Path,
        default=Path("data/research/formal_model_runs/catalog.json"),
    )
    parser.add_argument(
        "--ledger-root",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/strategy_operations/snapshots.json"),
    )
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()

    contract_models = validate_formal_catalog_evidence(args.formal_catalog)
    payload = build_operations_payload(
        formal_catalog=args.formal_catalog,
        ledger_root=args.ledger_root,
        generated_at=args.generated_at,
    )
    validate_operations_payload(payload)
    changed = write_operations_payload(args.output, payload)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "changed": changed,
                "formal_evidence_contract_models": contract_models,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
