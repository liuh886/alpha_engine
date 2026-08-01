"""Inventory maintained and historical factor assets without inferring formulas."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

KNOWN_ASSETS = (
    {
        "path": "docs/research/factor_history_inventory_seed_2026-07-31.yaml",
        "asset_type": "legacy_factor_history_seed",
        "expected_claim": "legacy 261-factor scan and named historical families",
    },
    {
        "path": "artifacts/factor_registry.db",
        "asset_type": "legacy_factor_registry_database",
        "expected_claim": "historical registry rows when locally available",
    },
    {
        "path": "src/common/inference_features.py",
        "asset_type": "runtime_feature_helper",
        "expected_claim": "legacy inference feature declarations",
    },
    {
        "path": "configs/cn_workflow.yaml",
        "asset_type": "legacy_workflow_config",
        "expected_claim": "historical CN Alpha158 handler/config usage",
    },
    {
        "path": "configs/us_workflow.yaml",
        "asset_type": "legacy_workflow_config",
        "expected_claim": "historical US Alpha158 handler/config usage",
    },
    {
        "path": "scripts/pipeline_cn_best.py",
        "asset_type": "legacy_training_script",
        "expected_claim": "historical Alpha158 training path",
    },
    {
        "path": "scripts/train_optimal.py",
        "asset_type": "legacy_training_script",
        "expected_claim": "historical model training feature path",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(root: Path) -> dict[str, Any]:
    normalized_root = root.resolve()
    rows: list[dict[str, Any]] = []
    for asset in KNOWN_ASSETS:
        path = normalized_root / str(asset["path"])
        row = dict(asset)
        row["exists"] = path.is_file()
        row["sha256"] = _sha256(path) if path.is_file() else None
        row["formula_recovery_status"] = (
            "requires_content_classification"
            if path.is_file()
            else "not_present_in_checkout"
        )
        rows.append(row)

    return {
        "schema_version": "1.0",
        "inventory_id": "factor_asset_inventory_v1",
        "alpha158_intended_public_set": True,
        "alpha161_alias_allowed": False,
        "legacy261_claim_preserved": True,
        "asset_count": len(rows),
        "present_asset_count": sum(1 for row in rows if row["exists"]),
        "assets": rows,
        "research_only": True,
        "trade_ready": False,
        "interpretation": (
            "Presence of an old config, output column or metric does not prove that "
            "a complete reusable formula is available. Each present asset must be "
            "classified before migration."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/factor_catalog/existing_asset_inventory.json"),
    )
    args = parser.parse_args()

    payload = audit(args.root)
    output = args.output
    if not output.is_absolute():
        output = args.root.resolve() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
