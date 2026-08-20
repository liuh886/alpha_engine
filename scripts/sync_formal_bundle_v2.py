"""Promote the exact active preview catalog into the formal Bundle v2 catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.native_formal_promotion import promote_preview_bundle
from src.artifacts.us_x1_3_formal import promote_preview_bundle as promote_us_x1_3
from src.governance.active_strategy_catalog import (
    DEFAULT_CATALOG_PATH,
    ActiveStrategy,
    ActiveStrategyCatalogError,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)


class FormalBundleV2SyncError(ValueError):
    """Raised when active preview evidence and the formal catalog diverge."""


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


def _preview_manifests(
    preview_root: Path,
    strategies: tuple[ActiveStrategy, ...],
) -> dict[str, Path]:
    catalog = _object(preview_root / "catalog.json")
    validate_catalog(catalog)
    if (
        catalog.get("channel") != "preview"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalBundleV2SyncError("active publication input must be a preview Bundle v2 catalog")
    rows = catalog.get("records")
    if not isinstance(rows, list):
        raise FormalBundleV2SyncError("active preview catalog records are missing")

    result: dict[str, Path] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise FormalBundleV2SyncError("active preview catalog record is invalid")
        model_id = str(row.get("model_version_id") or "")
        if not model_id or model_id in result:
            raise FormalBundleV2SyncError(
                f"duplicate or empty active preview model id: {model_id!r}"
            )
        if row.get("publication_status") != "ci_validated_preview":
            raise FormalBundleV2SyncError(
                f"non-preview record entered active publication input: {model_id}"
            )
        manifest = preview_root / str(row.get("manifest_path") or "")
        if not manifest.is_file() or _sha256(manifest) != row.get("manifest_sha256"):
            raise FormalBundleV2SyncError(
                f"active preview manifest digest mismatch: {model_id}"
            )
        result[model_id] = manifest

    expected = {strategy.model_version_id for strategy in strategies}
    if set(result) != expected:
        raise FormalBundleV2SyncError(
            "active preview catalog must exactly match the Active Strategy Catalog: "
            f"expected={sorted(expected)}, observed={sorted(result)}"
        )
    return result


def _publish_freshness_policy(
    freshness_root: Path,
    output_root: Path,
    strategies: tuple[ActiveStrategy, ...],
) -> str:
    source = _object(freshness_root / "freshness.json")
    if (
        source.get("cutoff_policy") != "governed_benchmark_market_session"
        or source.get("research_only") is not True
        or source.get("trade_ready") is not False
        or not isinstance(source.get("markets"), dict)
        or not isinstance(source.get("next_session_close_utc"), dict)
    ):
        raise FormalBundleV2SyncError("formal freshness policy is invalid")
    rankers = [
        row.model_version_id for row in strategies if row.model_kind == "cross_sectional_ranker"
    ]
    policy = {
        **source,
        "required_models": [row.model_version_id for row in strategies],
        "date_range_end_required_models": rankers,
        "freshness_receipt_required_models": rankers,
    }
    destination = output_root / "freshness.json"
    destination.write_bytes(canonical_json_bytes(policy))
    return _sha256(destination)


def _preserve_inactive_formal_runs(
    source_root: Path,
    output_root: Path,
    *,
    active_model_ids: set[str],
) -> dict[str, str]:
    """Copy validated predecessor bundles outside the active catalog.

    The active catalog remains an exact four-model Interface. Historical model
    versions are a separate immutable audit closure consumed through
    ``load_retained_formal_run`` and must survive replacement of the active
    publication tree.
    """

    retained: dict[str, str] = {}
    for manifest in sorted(source_root.glob("*/*/*/manifest.json")):
        relative = manifest.relative_to(source_root)
        if len(relative.parts) != 4:
            raise FormalBundleV2SyncError(
                f"retained formal manifest has invalid layout: {relative.as_posix()}"
            )
        payload = _object(manifest)
        model_family_id = str(payload.get("model_family_id") or "")
        model_version_id = str(payload.get("model_version_id") or "")
        if model_version_id in active_model_ids:
            continue
        if (
            not model_family_id
            or not model_version_id
            or relative.parts[0] != model_family_id
            or relative.parts[1] != model_version_id
        ):
            raise FormalBundleV2SyncError(
                f"retained formal manifest identity mismatch: {relative.as_posix()}"
            )
        try:
            validate_formal_evidence_bundle(manifest.parent)
        except ValueError as exc:
            raise FormalBundleV2SyncError(
                f"invalid retained formal bundle: {relative.as_posix()}"
            ) from exc
        destination = output_root / relative.parent
        if destination.exists():
            raise FormalBundleV2SyncError(
                f"retained formal destination already exists: {relative.parent.as_posix()}"
            )
        shutil.copytree(manifest.parent, destination)
        validate_formal_evidence_bundle(destination)
        retained[relative.as_posix()] = _sha256(destination / "manifest.json")
    return retained


def sync(
    source_root: Path,
    output_root: Path,
    *,
    native_root: Path = Path("data/research/model_runs"),
    strategy_catalog: Path = DEFAULT_CATALOG_PATH,
    retained_root: Path | None = None,
) -> dict[str, Any]:
    """Promote exactly one persisted preview Bundle v2 for every active strategy.

    ``source_root`` contains the freshness policy. ``retained_root`` defaults
    to that same tree and may instead point at the accepted publication when a
    candidate is built in isolation. ``native_root`` is the exact active
    preview Bundle v2 catalog and is the sole input for active model evidence.
    """

    freshness_root = source_root.resolve()
    output_root = output_root.resolve()
    preview_root = native_root.resolve()
    strategy_catalog = strategy_catalog.resolve()
    retained_source = (retained_root or freshness_root).resolve()
    if retained_source == output_root:
        raise FormalBundleV2SyncError(
            "retained formal input and formal output must be separate directories"
        )
    try:
        active = load_active_strategy_catalog(strategy_catalog)
    except ActiveStrategyCatalogError as exc:
        raise FormalBundleV2SyncError(str(exc)) from exc

    preview_manifests = _preview_manifests(preview_root, active.strategies)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    manifests: list[Path] = []
    promoted: list[str] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        source_run = preview_manifests[model_id].parent
        if model_id == "us_x1_3":
            manifest = promote_us_x1_3(source_run, output_root)
        else:
            manifest = promote_preview_bundle(source_run, output_root, strategy)
        validate_formal_evidence_bundle(manifest.parent)
        manifests.append(manifest)
        promoted.append(model_id)

    retained_manifests = _preserve_inactive_formal_runs(
        retained_source,
        output_root,
        active_model_ids=set(active.active_model_version_ids),
    )

    update_catalog(manifests, catalog_path=output_root / "catalog.json", channel="formal")
    freshness_sha = _publish_freshness_policy(
        freshness_root,
        output_root,
        active.strategies,
    )
    catalog_path = output_root / "catalog.json"
    catalog = _object(catalog_path)
    try:
        assert_formal_catalog_matches_active_strategies(catalog, active)
    except ActiveStrategyCatalogError as exc:
        raise FormalBundleV2SyncError(str(exc)) from exc

    receipt = {
        "schema_version": "2.0.0",
        "status": "active_formal_bundle_v2_built",
        "publication_input": "active_preview_bundle_v2",
        "active_strategy_ids": [row.strategy_id for row in active.strategies],
        "active_model_version_ids": list(active.active_model_version_ids),
        "native_promoted_model_ids": promoted,
        "retained_inactive_model_version_ids": sorted(
            {
                Path(path).parts[1]
                for path in retained_manifests
            }
        ),
        "retained_formal_manifests": retained_manifests,
        "preview_catalog_sha256": _sha256(preview_root / "catalog.json"),
        "freshness_source_sha256": _sha256(freshness_root / "freshness.json"),
        "strategy_catalog_sha256": _sha256(strategy_catalog),
        "formal_bundle_v2_catalog_sha256": _sha256(catalog_path),
        "formal_bundle_v2_freshness_sha256": freshness_sha,
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
        default=Path("data/research/formal_model_runs"),
        help="Directory containing freshness.json; model evidence is never read here.",
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/formal-model-runs")
    )
    parser.add_argument(
        "--native-root",
        type=Path,
        default=Path("data/research/model_runs"),
        help="Exact active preview Bundle v2 catalog.",
    )
    parser.add_argument(
        "--retained-root",
        type=Path,
        help="Accepted formal root supplying validated inactive predecessor bundles.",
    )
    parser.add_argument("--strategy-catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.source_root.resolve() == args.output_root.resolve():
        raise FormalBundleV2SyncError(
            "freshness input and formal output must be separate directories"
        )
    receipt = sync(
        args.source_root,
        args.output_root,
        native_root=args.native_root,
        strategy_catalog=args.strategy_catalog,
        retained_root=args.retained_root,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
