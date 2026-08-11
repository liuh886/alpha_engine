"""Publish the active formal model set into Model Run Bundle v2.

Legacy accepted v1 packages are projected without recomputation. Native Bundle v2
models enter the same formal catalog only through an explicit promotion adapter.
Every active formal model is published under one production evidence contract.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from src.artifacts import formal_bundle_v2_projector as projector
from src.artifacts.formal_evidence_standard import (
    FORMAL_EVIDENCE_CONTRACT_ID,
    validate_formal_catalog_evidence,
)
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.performance_semantics import build_performance_semantics
from src.artifacts.us_x1_2_formal import (
    MODEL_ID as US_X1_2,
    SUPERSEDED_FORMAL_MODEL as US_X1_1,
    promote_preview_bundle,
)

FORMAL_MODEL_ADAPTERS: dict[str, tuple[str, str]] = {
    "qqqi_qqq_tqqq_v4_3": ("qqq_rotation", "rules_based_allocation"),
    US_X1_1: ("us_ranker", "cross_sectional_ranker"),
    "cn_x1_1": ("cn_ranker", "cross_sectional_ranker"),
    "byd_v1_3_recovery_event_low_vol_confirmation_v1": (
        "byd_allocation",
        "rules_based_allocation",
    ),
}

NATIVE_FORMAL_PROMOTIONS: dict[str, str] = {US_X1_2: US_X1_1}

# Exact declarations already executed by the retained implementations. They are
# bound into the small formal summary envelope; retained performance/portfolio
# evidence bytes are not rewritten just to carry metadata.
LEGACY_PRODUCTION_SEMANTICS: dict[str, dict[str, Any]] = {
    "qqqi_qqq_tqqq_v4_3": {
        "session_unit": "trading_session",
        "holding_sessions": 1,
        "execution_delay_sessions": 1,
        "holding_end_offset_sessions": 2,
        "performance_date_field": "date",
        "price_basis": "canonical_adjusted_open",
        "turnover_formula": "sum(abs(target_weight - previous_weight)); initial_entry=sum(abs(target_weight))",
        "net_return_formula": "gross_return - transaction_cost",
    },
    "cn_x1_1": {
        "session_unit": "provider_session",
        "signal_time": "provider_close_t",
        "execution_time": "provider_close_t_plus_1",
        "return_measurement": "provider_close_t_plus_1_to_provider_close_t_plus_11",
        "price_basis": "governed_provider_close",
        "turnover_formula": "0.5 * (sum(abs(target_weight - previous_weight)) + abs(target_cash - previous_cash))",
        "net_return_formula": "gross_return - transaction_cost",
    },
    "byd_v1_3_recovery_event_low_vol_confirmation_v1": {
        "session_unit": "common_market_session",
        "holding_sessions": 1,
        "holding_end_offset_sessions": "next_common_eligible_open_execution_then_next_common_session_open",
        "performance_date_field": "date",
        "return_measurement": "canonical_adjusted_open_to_next_canonical_adjusted_open",
        "price_basis": "independently_validated_canonical_adjusted_open",
        "turnover_formula": "sum(abs(target_weight - previous_weight)) across BYD, 515180.SH, and CASH",
        "net_return_formula": "gross_return - transaction_cost - financing_cost",
    },
}


class FormalBundleV2SyncError(ValueError):
    """Raised when formal source and Bundle v2 publication contracts diverge."""


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
            raise FormalBundleV2SyncError(f"duplicate or empty formal model id: {model_id!r}")
        if row.get("publication_status") != "accepted_formal_baseline":
            raise FormalBundleV2SyncError(f"non-accepted record entered formal catalog: {model_id}")
        package_path = source_root / str(row.get("path") or "")
        if not package_path.is_file() or _sha256(package_path) != row.get("sha256"):
            raise FormalBundleV2SyncError(f"formal v1 package digest mismatch: {model_id}")
        package = _object(package_path)
        if (
            package.get("model_id") != model_id
            or package.get("publication_status") != "accepted_formal_baseline"
            or package.get("research_only") is not True
            or package.get("trade_ready") is not False
        ):
            raise FormalBundleV2SyncError(f"formal v1 package boundary mismatch: {model_id}")
        model_ids.append(model_id)
    return model_ids


def active_formal_models(accepted_v1: list[str]) -> list[str]:
    superseded = set(NATIVE_FORMAL_PROMOTIONS.values())
    active = [model_id for model_id in accepted_v1 if model_id not in superseded]
    active.extend(NATIVE_FORMAL_PROMOTIONS)
    return active


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
            raise FormalBundleV2SyncError(
                f"performance section is unavailable for MTM projection: {source_path}"
            )
        payload = dict(section.payload)
        report = payload.get("report")
        if not isinstance(report, list):
            raise FormalBundleV2SyncError(f"performance report is invalid: {source_path}")
        payload["report"] = [*report, dict(row)]
        payload["source_fields"] = ["report", "provisional_mtm.performance_row"]
        payload["provisional_mtm_projected"] = True
        sections.append(replace(section, payload=payload))
        projected = True
    if not projected:
        raise FormalBundleV2SyncError(
            f"performance section was not found for MTM projection: {source_path}"
        )
    return replace(plan, sections=tuple(sections))


def _production_portfolio_contract(source_path: Path) -> dict[str, Any]:
    package = _object(source_path)
    model_id = str(package.get("model_id") or "")
    declarations = LEGACY_PRODUCTION_SEMANTICS.get(model_id)
    if declarations is None:
        raise FormalBundleV2SyncError(f"production semantics are not declared: {model_id}")
    source_contract = package.get("portfolio_contract")
    if not isinstance(source_contract, Mapping):
        raise FormalBundleV2SyncError(f"formal portfolio contract is missing: {model_id}")
    contract = dict(source_contract)
    for key, value in declarations.items():
        if key in contract and contract[key] != value:
            raise FormalBundleV2SyncError(
                f"formal production semantic conflicts with retained source: {model_id}/{key}"
            )
        contract[key] = value
    return contract


def _with_evidence_contract(plan, source_path: Path):
    contract = _production_portfolio_contract(source_path)
    semantics = build_performance_semantics(
        contract,
        trace_frequency=plan.comparability_key.get("trace_frequency"),
    )
    sections = []
    bound = False
    for section in plan.sections:
        if section.section_id != "summary":
            sections.append(section)
            continue
        if not isinstance(section.payload, Mapping):
            raise FormalBundleV2SyncError("formal summary section is unavailable")
        payload = dict(section.payload)
        payload["evidence_contract"] = FORMAL_EVIDENCE_CONTRACT_ID
        payload["performance_semantics"] = semantics
        payload["portfolio_contract"] = contract
        sections.append(replace(section, payload=payload))
        bound = True
    if not bound:
        raise FormalBundleV2SyncError("formal summary section was not found")
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


def _publish_native_formals(native_root: Path, output_root: Path) -> list[str]:
    promoted: list[str] = []
    for model_id, superseded in NATIVE_FORMAL_PROMOTIONS.items():
        source_manifest = _native_preview_manifest(native_root, model_id)
        manifest_path = promote_preview_bundle(source_manifest.parent, output_root)
        superseded_root = output_root / "us_ranker" / superseded
        if superseded_root.exists():
            shutil.rmtree(superseded_root)
        if not manifest_path.is_file():
            raise FormalBundleV2SyncError(f"native formal publication failed: {model_id}")
        promoted.append(model_id)

    manifests = sorted(output_root.rglob("manifest.json"))
    update_catalog(manifests, catalog_path=output_root / "catalog.json", channel="formal")
    return promoted


def sync(
    source_root: Path,
    output_root: Path,
    native_root: Path = Path("data/research/model_runs"),
) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    native_root = native_root.resolve()
    accepted = accepted_v1_models(source_root)
    supported = list(FORMAL_MODEL_ADAPTERS)
    if accepted != supported:
        raise FormalBundleV2SyncError(
            "accepted formal v1 catalog and projector registry diverge: "
            f"accepted={accepted}, supported={supported}"
        )

    mtm_models = [
        model_id
        for model_id in accepted
        if _object(source_root / f"{model_id}.json").get("provisional_mtm") is not None
    ]

    prior_map = dict(projector.MODEL_MAP)
    prior_build_plan = projector.build_plan
    try:
        projector.MODEL_MAP.clear()
        projector.MODEL_MAP.update(FORMAL_MODEL_ADAPTERS)

        def build_plan_with_mtm(source_path: Path):
            plan = _with_provisional_mtm(prior_build_plan(source_path), source_path)
            return _with_evidence_contract(plan, source_path)

        projector.build_plan = build_plan_with_mtm
        migration_receipt = projector.project_formal_bundle_v2(source_root, output_root)
    finally:
        projector.build_plan = prior_build_plan
        projector.MODEL_MAP.clear()
        projector.MODEL_MAP.update(prior_map)

    if mtm_models:
        migration_receipt["status"] = "formal_v1_projected_with_current_mtm"
        migration_receipt["provisional_mtm_models"] = mtm_models
        (output_root / "migration-receipt.json").write_bytes(canonical_json_bytes(migration_receipt))

    promoted = _publish_native_formals(native_root, output_root)
    freshness_sha = _publish_freshness_policy(source_root, output_root)
    catalog_path = output_root / "catalog.json"
    catalog = _object(catalog_path)
    validate_catalog(catalog)
    projected = [str(row.get("model_version_id")) for row in catalog["records"]]
    active = active_formal_models(accepted)
    if set(projected) != set(active) or len(projected) != len(active):
        raise FormalBundleV2SyncError(
            f"active formal model-set parity failed: active={active}, projected={projected}"
        )

    contract_models = validate_formal_catalog_evidence(catalog_path)
    if set(contract_models) != set(active) or len(contract_models) != len(active):
        raise FormalBundleV2SyncError(
            "formal evidence contract coverage failed: "
            f"active={active}, contract_models={contract_models}"
        )

    receipt = {
        "schema_version": "2.0.0",
        "status": "all_active_formal_models_projected",
        "evidence_contract": FORMAL_EVIDENCE_CONTRACT_ID,
        "evidence_contract_model_ids": contract_models,
        "accepted_v1_model_ids": accepted,
        "native_formal_model_ids": promoted,
        "superseded_formal_model_ids": list(NATIVE_FORMAL_PROMOTIONS.values()),
        "active_formal_model_ids": active,
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
    parser.add_argument("--source-root", type=Path, default=Path("data/research/formal_backtests"))
    parser.add_argument("--output-root", type=Path, default=Path("data/research/formal_model_runs"))
    parser.add_argument("--native-root", type=Path, default=Path("data/research/model_runs"))
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = sync(args.source_root, args.output_root, args.native_root)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
