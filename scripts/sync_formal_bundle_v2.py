"""Project the accepted formal v1 catalog into Model Run Bundle v2.

This is the single formal publication projector. It derives the accepted model
set from the governed v1 catalog, requires exact parity with the supported
adapter registry, and rebuilds Bundle v2 deterministically without rerunning a
model or reopening model selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from scripts import migrate_formal_v1_to_bundle_v2 as migration
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, validate_catalog

FORMAL_MODEL_ADAPTERS: dict[str, tuple[str, str]] = {
    "qqqi_qqq_tqqq_v4_2": ("qqq_rotation", "rules_based_allocation"),
    "us_x1_1": ("us_ranker", "cross_sectional_ranker"),
    "cn_x1_1": ("cn_ranker", "cross_sectional_ranker"),
    "byd_v1_2_convex_momentum_budget_v1": (
        "byd_allocation",
        "rules_based_allocation",
    ),
}


class FormalBundleV2SyncError(ValueError):
    """Raised when formal v1 and Bundle v2 publication contracts diverge."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBundleV2SyncError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalBundleV2SyncError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_v1_models(source_root: Path) -> list[str]:
    catalog = _object(source_root / "catalog.json")
    if (
        catalog.get("schema_version") != "1.0.0"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalBundleV2SyncError("formal v1 catalog boundary is invalid")
    records = catalog.get("records")
    if not isinstance(records, list) or not records:
        raise FormalBundleV2SyncError("formal v1 catalog records are missing")

    model_ids: list[str] = []
    for row in records:
        if not isinstance(row, Mapping):
            raise FormalBundleV2SyncError("formal v1 catalog record is invalid")
        model_id = str(row.get("model_id") or "")
        if not model_id or model_id in model_ids:
            raise FormalBundleV2SyncError(
                f"duplicate or empty formal model id: {model_id!r}"
            )
        if row.get("publication_status") != "accepted_formal_baseline":
            raise FormalBundleV2SyncError(
                f"non-accepted record entered formal catalog: {model_id}"
            )
        package_path = source_root / str(row.get("path") or "")
        if not package_path.is_file() or _sha256(package_path) != row.get("sha256"):
            raise FormalBundleV2SyncError(
                f"formal v1 package digest mismatch: {model_id}"
            )
        package = _object(package_path)
        if (
            package.get("model_id") != model_id
            or package.get("publication_status") != "accepted_formal_baseline"
            or package.get("research_only") is not True
            or package.get("trade_ready") is not False
        ):
            raise FormalBundleV2SyncError(
                f"formal v1 package boundary mismatch: {model_id}"
            )
        model_ids.append(model_id)
    return model_ids


def _publish_freshness_policy(source_root: Path, output_root: Path) -> str:
    source = source_root / "freshness.json"
    policy = _object(source)
    if (
        policy.get("cutoff_policy") != "latest_completed_trading_session"
        or policy.get("research_only") is not True
        or policy.get("trade_ready") is not False
        or not isinstance(policy.get("markets"), dict)
        or not isinstance(policy.get("next_session_close_utc"), dict)
    ):
        raise FormalBundleV2SyncError("formal freshness policy is invalid")
    destination = output_root / "freshness.json"
    shutil.copyfile(source, destination)
    return _sha256(destination)


def sync(source_root: Path, output_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    accepted = accepted_v1_models(source_root)
    supported = list(FORMAL_MODEL_ADAPTERS)
    if accepted != supported:
        raise FormalBundleV2SyncError(
            "accepted formal catalog and Bundle v2 adapter registry diverge: "
            f"accepted={accepted}, supported={supported}"
        )

    prior_map = dict(migration.MODEL_MAP)
    try:
        migration.MODEL_MAP.clear()
        migration.MODEL_MAP.update(FORMAL_MODEL_ADAPTERS)
        migration_receipt = migration.migrate(source_root, output_root)
    finally:
        migration.MODEL_MAP.clear()
        migration.MODEL_MAP.update(prior_map)

    freshness_sha = _publish_freshness_policy(source_root, output_root)
    catalog_path = output_root / "catalog.json"
    catalog = _object(catalog_path)
    validate_catalog(catalog)
    projected = [str(row.get("model_version_id")) for row in catalog["records"]]
    if set(projected) != set(accepted) or len(projected) != len(accepted):
        raise FormalBundleV2SyncError(
            f"formal v1/v2 model-set parity failed: accepted={accepted}, projected={projected}"
        )

    receipt = {
        "schema_version": "2.0.0",
        "status": "all_accepted_formal_models_projected",
        "accepted_model_ids": accepted,
        "projected_model_ids": projected,
        "source_catalog_sha256": _sha256(source_root / "catalog.json"),
        "source_freshness_sha256": _sha256(source_root / "freshness.json"),
        "formal_bundle_v2_catalog_sha256": _sha256(catalog_path),
        "formal_bundle_v2_freshness_sha256": freshness_sha,
        "migration_receipt": migration_receipt,
        "model_selection_reopened": False,
        "historical_evidence_recomputed": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output_root / "formal-bundle-v2-sync-receipt.json").write_bytes(
        canonical_json_bytes(receipt)
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = sync(args.source_root, args.output_root)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
