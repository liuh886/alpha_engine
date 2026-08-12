"""Build the active formal Strategy Catalog into Model Run Bundle v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from src.artifacts.formal_bundle_v2_builder import FormalBundleV2BuildError, build_plan
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, validate_catalog
from src.artifacts.model_run_exporter import export_model_run, update_catalog
from src.artifacts.us_x1_3_formal import promote_preview_bundle as promote_us_x1_3
from src.governance.active_strategy_catalog import (
    DEFAULT_CATALOG_PATH,
    ActiveStrategy,
    ActiveStrategyCatalogError,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)

NATIVE_PROMOTERS: dict[str, Callable[[Path, Path], Path]] = {
    "us_x1_3": promote_us_x1_3,
}


class FormalBundleV2SyncError(ValueError):
    """Raised when active strategy identity and formal evidence diverge."""


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


def _source_rows(source_root: Path) -> dict[str, Mapping[str, Any]]:
    catalog = _object(source_root / "catalog.json")
    if (
        catalog.get("schema_version") != "1.0.0"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalBundleV2SyncError("formal source catalog boundary is invalid")
    rows = catalog.get("records")
    if not isinstance(rows, list) or not rows:
        raise FormalBundleV2SyncError("formal source catalog records are missing")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise FormalBundleV2SyncError("formal source catalog record is invalid")
        model_id = str(row.get("model_id") or "")
        if not model_id or model_id in result:
            raise FormalBundleV2SyncError(f"duplicate or empty formal source model id: {model_id!r}")
        if row.get("publication_status") != "accepted_formal_baseline":
            raise FormalBundleV2SyncError(f"non-accepted record entered formal source catalog: {model_id}")
        path = source_root / str(row.get("path") or "")
        if not path.is_file() or _sha256(path) != row.get("sha256"):
            raise FormalBundleV2SyncError(f"formal source package digest mismatch: {model_id}")
        result[model_id] = row
    return result


def _with_provisional_mtm(plan, source_path: Path):
    package = _object(source_path)
    provisional = package.get("provisional_mtm")
    if provisional is None:
        return plan
    if not isinstance(provisional, Mapping):
        raise FormalBundleV2SyncError(f"provisional_mtm must be an object: {source_path}")
    row = provisional.get("performance_row")
    as_of = str(provisional.get("as_of") or "")
    if (
        provisional.get("schema_version") != "ranker_provisional_mtm_v1"
        or provisional.get("research_only") is not True
        or provisional.get("trade_ready") is not False
        or not isinstance(row, Mapping)
        or row.get("provisional_mtm") is not True
        or row.get("settlement_status") != "provisional_mtm"
        or str(row.get("holding_end_date") or "") != as_of
        or as_of != plan.evidence_cutoff
    ):
        raise FormalBundleV2SyncError(f"invalid provisional MTM contract: {source_path}")

    sections = []
    projected = False
    for section in plan.sections:
        if section.section_id != "performance":
            sections.append(section)
            continue
        if not isinstance(section.payload, Mapping):
            raise FormalBundleV2SyncError(f"performance section unavailable for MTM: {source_path}")
        payload = dict(section.payload)
        report = payload.get("report")
        if not isinstance(report, list):
            raise FormalBundleV2SyncError(f"performance report invalid: {source_path}")
        payload["report"] = [*report, dict(row)]
        payload["source_fields"] = ["report", "provisional_mtm.performance_row"]
        payload["provisional_mtm_projected"] = True
        sections.append(replace(section, payload=payload))
        projected = True
    if not projected:
        raise FormalBundleV2SyncError(f"performance section missing for MTM: {source_path}")
    return replace(plan, sections=tuple(sections))


def _native_preview_manifest(native_root: Path, model_id: str) -> Path:
    catalog = _object(native_root / "catalog.json")
    validate_catalog(catalog)
    if catalog.get("channel") != "preview":
        raise FormalBundleV2SyncError("native formal source must be a preview catalog")
    records = [
        row
        for row in catalog["records"]
        if isinstance(row, Mapping) and row.get("model_version_id") == model_id
    ]
    if len(records) != 1:
        raise FormalBundleV2SyncError(f"native formal source identity is ambiguous: {model_id}")
    record = records[0]
    manifest_path = native_root / str(record["manifest_path"])
    if not manifest_path.is_file() or _sha256(manifest_path) != record["manifest_sha256"]:
        raise FormalBundleV2SyncError(f"native formal source manifest digest mismatch: {model_id}")
    return manifest_path


def _publish_freshness_policy(
    source_root: Path,
    output_root: Path,
    strategies: tuple[ActiveStrategy, ...],
) -> str:
    source = _object(source_root / "freshness.json")
    if (
        source.get("cutoff_policy") != "latest_completed_trading_session"
        or source.get("research_only") is not True
        or source.get("trade_ready") is not False
        or not isinstance(source.get("markets"), dict)
        or not isinstance(source.get("next_session_close_utc"), dict)
    ):
        raise FormalBundleV2SyncError("formal freshness policy is invalid")
    rankers = [row.model_version_id for row in strategies if row.model_kind == "cross_sectional_ranker"]
    policy = {
        **source,
        "required_models": [row.model_version_id for row in strategies],
        "date_range_end_required_models": rankers,
        "freshness_receipt_required_models": rankers,
    }
    destination = output_root / "freshness.json"
    destination.write_bytes(canonical_json_bytes(policy))
    return _sha256(destination)


def sync(
    source_root: Path,
    output_root: Path,
    *,
    native_root: Path = Path("data/research/model_runs"),
    strategy_catalog: Path = DEFAULT_CATALOG_PATH,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    native_root = native_root.resolve()
    strategy_catalog = strategy_catalog.resolve()
    try:
        active = load_active_strategy_catalog(strategy_catalog)
    except ActiveStrategyCatalogError as exc:
        raise FormalBundleV2SyncError(str(exc)) from exc
    source_rows = _source_rows(source_root)
    active_ids = set(active.active_model_version_ids)
    source_ids = set(source_rows)
    native_ids = set(NATIVE_PROMOTERS)
    if source_ids | native_ids != active_ids or source_ids & native_ids:
        raise FormalBundleV2SyncError(
            "active strategy sources must be exactly partitioned between governed formal sources and native Bundle v2 promotions: "
            f"active={sorted(active_ids)}, source={sorted(source_ids)}, native={sorted(native_ids)}"
        )

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    manifests: list[Path] = []
    source_built: list[str] = []
    native_promoted: list[str] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        if model_id in source_rows:
            source_path = source_root / str(source_rows[model_id].get("path") or "")
            try:
                plan = build_plan(source_path, strategy)
            except FormalBundleV2BuildError as exc:
                raise FormalBundleV2SyncError(str(exc)) from exc
            manifests.append(export_model_run(_with_provisional_mtm(plan, source_path), output_root=output_root))
            source_built.append(model_id)
            continue
        promoter = NATIVE_PROMOTERS[model_id]
        source_manifest = _native_preview_manifest(native_root, model_id)
        manifests.append(promoter(source_manifest.parent, output_root))
        native_promoted.append(model_id)

    update_catalog(manifests, catalog_path=output_root / "catalog.json", channel="formal")
    freshness_sha = _publish_freshness_policy(source_root, output_root, active.strategies)
    catalog_path = output_root / "catalog.json"
    catalog = _object(catalog_path)
    try:
        assert_formal_catalog_matches_active_strategies(catalog, active)
    except ActiveStrategyCatalogError as exc:
        raise FormalBundleV2SyncError(str(exc)) from exc

    receipt = {
        "schema_version": "2.0.0",
        "status": "active_formal_bundle_v2_built",
        "active_strategy_ids": [row.strategy_id for row in active.strategies],
        "active_model_version_ids": list(active.active_model_version_ids),
        "source_built_model_ids": source_built,
        "native_promoted_model_ids": native_promoted,
        "source_catalog_sha256": _sha256(source_root / "catalog.json"),
        "source_freshness_sha256": _sha256(source_root / "freshness.json"),
        "strategy_catalog_sha256": _sha256(strategy_catalog),
        "formal_bundle_v2_catalog_sha256": _sha256(catalog_path),
        "formal_bundle_v2_freshness_sha256": freshness_sha,
        "model_selection_reopened": False,
        "historical_evidence_recomputed": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output_root / "formal-bundle-v2-sync-receipt.json").write_bytes(canonical_json_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("data/research/formal_backtests"))
    parser.add_argument("--output-root", type=Path, default=Path("data/research/formal_model_runs"))
    parser.add_argument("--native-root", type=Path, default=Path("data/research/model_runs"))
    parser.add_argument("--strategy-catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = sync(
        args.source_root,
        args.output_root,
        native_root=args.native_root,
        strategy_catalog=args.strategy_catalog,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
