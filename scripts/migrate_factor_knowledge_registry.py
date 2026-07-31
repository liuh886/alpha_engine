"""Migrate legacy factor records into the evidence-complete v2 ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.factor_knowledge_registry import FactorKnowledgeRegistry


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create additive FactorRegistry v2 tables and migrate legacy rows "
            "as legacy_unverified without deleting source records."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite registry path; defaults to artifacts/factor_registry.db",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON completeness report output path",
    )
    args = parser.parse_args()

    registry = FactorKnowledgeRegistry(db_path=args.db)
    migrated = registry.migrate_legacy_registry()
    report = registry.evidence_completeness_report()
    payload = {"migration": migrated, "completeness": report}

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
