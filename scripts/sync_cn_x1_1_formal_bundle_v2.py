"""Project the accepted CN x1.1 v1 package into the active formal Bundle v2 catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.migrate_formal_v1_to_bundle_v2 import MODEL_MAP, build_plan
from src.artifacts.model_run_bundle_v2 import (
    canonical_json_bytes,
    validate_catalog,
    validate_manifest,
)
from src.artifacts.model_run_exporter import export_model_run


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def sync(
    *,
    v1_root: Path,
    existing_v2_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    source_catalog_path = v1_root / "catalog.json"
    source_package_path = v1_root / "cn_x1_1.json"
    existing_catalog_path = existing_v2_root / "catalog.json"
    source_catalog = object_json(source_catalog_path)
    source_package = object_json(source_package_path)
    if source_package.get("model_id") != "cn_x1_1":
        raise ValueError("accepted v1 source is not CN x1.1")
    if source_package.get("publication_status") != "accepted_formal_baseline":
        raise ValueError("CN x1.1 v1 source is not the accepted formal baseline")
    if source_package.get("research_only") is not True:
        raise ValueError("CN x1.1 v1 source must remain research-only")
    if source_package.get("trade_ready") is not False:
        raise ValueError("CN x1.1 v1 source must remain non-trade-ready")

    MODEL_MAP["cn_x1_1"] = ("cn_ranker", "cross_sectional_ranker")
    plan = build_plan(
        source_package_path,
        catalog_sha256=sha256(source_catalog_path),
    )
    manifest_path = export_model_run(plan, output_root=output_root)
    manifest = object_json(manifest_path)
    validate_manifest(manifest)

    existing_catalog = object_json(existing_catalog_path)
    validate_catalog(existing_catalog)
    preserved = [
        row
        for row in existing_catalog["records"]
        if row.get("model_family_id") != "cn_ranker"
    ]
    preserved_ids = {row.get("model_version_id") for row in preserved}
    if preserved_ids != {"qqqi_qqq_tqqq_v4_2", "us_x1_1"}:
        raise ValueError(f"unexpected preserved formal v2 models: {preserved_ids}")

    record = {
        "bundle_id": manifest["bundle_id"],
        "evidence_cutoff": manifest["evidence_cutoff"],
        "manifest_path": manifest_path.relative_to(output_root).as_posix(),
        "manifest_sha256": sha256(manifest_path),
        "model_family_id": manifest["model_family_id"],
        "model_kind": manifest["model_kind"],
        "model_version_id": manifest["model_version_id"],
        "publication_status": manifest["publication_status"],
        "run_id": manifest["run_id"],
    }
    catalog = {
        "schema_version": "2.0.0",
        "channel": "formal",
        "generated_at": str(source_package.get("generated_at") or ""),
        "research_only": True,
        "trade_ready": False,
        "records": sorted(
            [*preserved, record],
            key=lambda row: (
                str(row["model_family_id"]),
                str(row["model_version_id"]),
                str(row["run_id"]),
            ),
        ),
    }
    validate_catalog(catalog)
    catalog_path = output_root / "catalog.json"
    catalog_path.write_bytes(canonical_json_bytes(catalog))

    receipt = {
        "schema_version": "2.0.0",
        "status": "cn_x1_1_formal_bundle_v2_synced",
        "source_v1_catalog_sha256": sha256(source_catalog_path),
        "source_cn_x1_1_sha256": sha256(source_package_path),
        "prior_cn_bundle": next(
            row
            for row in existing_catalog["records"]
            if row.get("model_family_id") == "cn_ranker"
        ),
        "new_cn_bundle": record,
        "preserved_model_versions": sorted(str(value) for value in preserved_ids),
        "formal_catalog_sha256": sha256(catalog_path),
        "model_selection_reopened": False,
        "historical_evidence_recomputed": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output_root / "cn-x1-1-v2-sync-receipt.json").write_bytes(
        canonical_json_bytes(receipt)
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v1-root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--existing-v2-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = sync(
        v1_root=args.v1_root.resolve(),
        existing_v2_root=args.existing_v2_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
