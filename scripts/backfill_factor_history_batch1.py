"""Populate FactorRegistry v2 with the first canonical historical factor batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.factor_history_backfill import backfill_history_batch
from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

DEFAULT_INVENTORY = Path("configs/factor_knowledge/historical_factor_cards_v1.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import historical factor cards as non-authoritative evidence. "
            "No performance is rerun and no reserved evidence is opened."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    registry = FactorKnowledgeRegistry(args.db)
    result = backfill_history_batch(registry, args.inventory)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
