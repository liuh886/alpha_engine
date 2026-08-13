#!/usr/bin/env python3
"""Build the exact active preview Bundle v2 catalog from governed evidence inputs."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from src.artifacts.formal_preview_builder import build_preview_bundle
from src.artifacts.formal_refresh import load_object, sha256
from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog


def _copy_native_model(native_root: Path, output_root: Path, model_id: str) -> None:
    catalog = load_object(native_root / "catalog.json")
    validate_catalog(catalog)
    rows = [
        row
        for row in catalog.get("records", [])
        if isinstance(row, Mapping) and row.get("model_version_id") == model_id
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one native preview for {model_id}")
    row = rows[0]
    manifest = native_root / str(row["manifest_path"])
    if not manifest.is_file() or sha256(manifest) != row.get("manifest_sha256"):
        raise ValueError(f"native preview digest mismatch: {model_id}")
    family = str(row["model_family_id"])
    source = native_root / family / model_id
    target = output_root / family / model_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def build_active_previews(
    *,
    governed_root: Path,
    native_root: Path,
    output_root: Path,
) -> dict[str, object]:
    active = load_active_strategy_catalog()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    for strategy in active.strategies:
        source = governed_root / f"{strategy.model_version_id}.json"
        if source.is_file():
            build_preview_bundle(source, strategy, output_root=output_root)
        else:
            _copy_native_model(native_root, output_root, strategy.model_version_id)

    manifests = sorted(output_root.rglob("manifest.json"))
    catalog = update_catalog(
        manifests,
        catalog_path=output_root / "catalog.json",
        channel="preview",
    )
    observed = {
        str(row.get("model_version_id") or "")
        for row in catalog.get("records", [])
        if isinstance(row, Mapping)
    }
    expected = set(active.active_model_version_ids)
    if observed != expected or len(catalog.get("records", [])) != len(expected):
        raise ValueError(
            "active preview catalog mismatch: "
            f"expected={sorted(expected)}, observed={sorted(observed)}"
        )
    return {
        "schema_version": "2.0.0",
        "status": "active_preview_bundle_v2_ready",
        "active_model_version_ids": list(active.active_model_version_ids),
        "catalog_sha256": sha256(output_root / "catalog.json"),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--governed-root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--native-root",
        type=Path,
        default=Path("data/research/model_runs"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_active_previews(
        governed_root=args.governed_root,
        native_root=args.native_root,
        output_root=args.output_root,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
