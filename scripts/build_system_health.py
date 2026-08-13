"""Materialize the backend-owned multi-watermark system health read model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.system_health import (
    build_system_health,
    validate_system_health,
    write_system_health,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--operations",
        type=Path,
        default=Path("data/research/strategy_operations/snapshots.json"),
    )
    parser.add_argument(
        "--formal-catalog",
        type=Path,
        default=Path("data/research/formal_model_runs/catalog.json"),
    )
    parser.add_argument(
        "--formal-freshness",
        type=Path,
        default=Path("data/research/formal_model_runs/freshness.json"),
    )
    parser.add_argument(
        "--model-data-readiness",
        type=Path,
        default=Path("data/research/model_data_bundle_v1/model-data-readiness.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/strategy_operations/system-health.json"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    operations_path = root / args.operations
    operations = json.loads(operations_path.read_text(encoding="utf-8"))
    if not isinstance(operations, dict):
        raise ValueError("Strategy Operations root must be an object")
    payload = build_system_health(
        repository_root=root,
        formal_catalog=root / args.formal_catalog,
        formal_freshness=root / args.formal_freshness,
        operations=operations,
        model_data_readiness=root / args.model_data_readiness,
        generated_at=args.generated_at,
    )
    validate_system_health(payload)
    changed = write_system_health(root / args.output, payload)
    print(
        json.dumps(
            {
                "path": args.output.as_posix(),
                "changed": changed,
                "state": payload["state"],
                "market_count": len(payload["markets"]),
                "strategy_count": len(payload["strategies"]),
                "research_only": True,
                "trade_ready": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
