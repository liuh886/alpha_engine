"""One-command US low-turnover diagnostic decision pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.decision_support.multifactor_shadow_adapter import (
    build_multifactor_shadow_artifacts,
)
from src.decision_support.prospective_shadow_cycle import load_cutover_contract
from src.decision_support.shadow_decision_desk import build_shadow_decision_ticket
from src.research.factor_history_backfill import backfill_history_batch
from src.research.factor_knowledge_registry import FactorKnowledgeRegistry
from src.research.factor_relationship_inputs import build_factor_relationship_inputs
from src.research.factor_relationship_map import build_factor_relationship_map
from src.research.fundamental_acceleration import run_fundamental_acceleration
from src.research.hierarchical_pool_rotation import run_hierarchical_pool_rotation
from src.research.low_turnover_multifactor_pipeline import (
    run_low_turnover_multifactor_pipeline,
)
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    build_sec_companyfacts_fundamentals,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _load_pipeline_contract(path: str | Path) -> tuple[dict[str, Any], Path, Path]:
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("decision pipeline contract must be a YAML mapping")
    if payload.get("status") != "frozen_diagnostic_pipeline":
        raise ValueError("decision pipeline contract is not frozen")
    truth = payload.get("truth_boundary", {})
    required = {
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "independent_validation_completed": False,
        "automatic_order_routing": False,
    }
    if truth != required:
        raise ValueError("decision pipeline truth boundary is invalid")
    root = resolved.parents[2]
    return payload, resolved, root


def _validate_cutover(
    contract: Mapping[str, Any],
    root: Path,
    *,
    as_of: date,
) -> tuple[dict[str, Any], Path]:
    cutover_path = _resolve(root, str(contract["as_of_cutover_contract"]))
    cutover = load_cutover_contract(cutover_path)
    effective = date.fromisoformat(str(cutover["effective_as_of_date"]))
    if as_of < effective:
        raise ValueError(f"as-of date precedes prospective cutover: {effective}")
    market = cutover.get("markets", {}).get("us", {})
    if market.get("enabled") is not True:
        raise ValueError("US prospective shadow market is disabled")
    return cutover, cutover_path


def _validate_prices(path: Path, *, as_of: date) -> None:
    frame = pd.read_csv(path, usecols=["date"])
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any() or dates.empty:
        raise ValueError("prices contain invalid or empty dates")
    latest = dates.max().date()
    if latest != as_of:
        raise ValueError(
            f"prices must end exactly on as-of date: latest={latest}, as_of={as_of}"
        )
    if (dates.dt.date > as_of).any():
        raise ValueError("prices contain future rows beyond the as-of date")


def _filter_fundamentals_as_of(
    source_path: Path,
    output_path: Path,
    *,
    as_of: date,
) -> dict[str, Any]:
    frame = pd.read_csv(source_path, dtype={"symbol": "string", "accession_id": "string"})
    if "filed_date" not in frame:
        raise ValueError("SEC fundamentals are missing filed_date")
    filed = pd.to_datetime(frame["filed_date"], errors="coerce")
    if filed.isna().any():
        raise ValueError("SEC fundamentals contain invalid filed dates")
    filtered = frame[filed.dt.date <= as_of].copy()
    if filtered.empty:
        raise ValueError("no SEC fundamentals are available by the as-of date")
    filtered.to_csv(output_path, index=False)
    return {
        "source_row_count": len(frame),
        "as_of_row_count": len(filtered),
        "removed_future_filing_count": len(frame) - len(filtered),
        "as_of_date": as_of.isoformat(),
        "sha256": _sha256_file(output_path),
    }


def _pool_baskets(pool_path: Path) -> dict[str, str]:
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict):
        raise ValueError("pool must be a YAML mapping")
    return {
        str(symbol).upper(): str(basket)
        for basket, meta in pool.get("baskets", {}).items()
        for symbol in meta.get("symbols", [])
    }


def _validate_sec_coverage(
    coverage_path: Path,
    *,
    pipeline: Mapping[str, Any],
    pool_path: Path,
) -> dict[str, Any]:
    coverage = _load_json(coverage_path)
    rows = coverage.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("SEC coverage report contains no symbol rows")
    basket_by_symbol = _pool_baskets(pool_path)
    ready = {
        str(row["symbol"]).upper()
        for row in rows
        if isinstance(row, dict) and row.get("factor_ready") is True
    }
    ratio = len(ready) / len(basket_by_symbol)
    gate = pipeline["source_coverage_gate"]
    minimum_ratio = float(gate["minimum_factor_ready_ratio"])
    if ratio < minimum_ratio:
        raise ValueError(
            f"SEC factor-ready coverage {ratio:.3f} is below {minimum_ratio:.3f}"
        )
    minimum_per_basket = int(gate["minimum_factor_ready_symbols_per_basket"])
    basket_counts: dict[str, int] = {}
    for symbol, basket in basket_by_symbol.items():
        if symbol in ready:
            basket_counts[basket] = basket_counts.get(basket, 0) + 1
    missing_baskets = sorted(
        basket
        for basket in set(basket_by_symbol.values())
        if basket_counts.get(basket, 0) < minimum_per_basket
    )
    if missing_baskets:
        raise ValueError(
            "SEC coverage is below the per-basket floor: " + ", ".join(missing_baskets)
        )
    return {
        "factor_ready_count": len(ready),
        "candidate_count": len(basket_by_symbol),
        "factor_ready_ratio": ratio,
        "factor_ready_by_basket": dict(sorted(basket_counts.items())),
    }


def _stage_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"stage manifest is missing: {path}")
    payload = _load_json(path)
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "identity": payload.get("manifest_identity_sha256")
        or payload.get("source_manifest_identity_sha256"),
    }


def run_us_low_turnover_decision_pipeline(
    *,
    pipeline_contract_path: str | Path,
    as_of_date: str,
    prices_csv: str | Path,
    registry_db: str | Path,
    workspace_dir: str | Path,
    ledger_dir: str | Path,
    sec_client: SecClientProtocol | None = None,
) -> dict[str, Any]:
    """Run the complete source-to-ticket diagnostic workflow."""

    pipeline, resolved_pipeline, root = _load_pipeline_contract(pipeline_contract_path)
    as_of = date.fromisoformat(as_of_date)
    cutover, cutover_path = _validate_cutover(pipeline, root, as_of=as_of)
    prices_path = Path(prices_csv).resolve()
    registry_path = Path(registry_db).resolve()
    workspace = Path(workspace_dir).resolve()
    ledger = Path(ledger_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    _validate_prices(prices_path, as_of=as_of)
    stages: list[dict[str, Any]] = []

    paths = {
        key: _resolve(root, str(pipeline[key]))
        for key in (
            "pool_spec",
            "rotation_spec",
            "fundamental_source_contract",
            "fundamental_factor_contract",
            "relationship_contract",
            "multifactor_contract",
            "historical_factor_inventory",
        )
    }
    directories = {
        name: workspace / name
        for name in pipeline["outputs"]["workspace_subdirectories"]
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)

    try:
        registry = FactorKnowledgeRegistry(registry_path)
        migration = registry.migrate_legacy_registry()
        history = backfill_history_batch(registry, paths["historical_factor_inventory"])
        stages.append(
            {
                "stage": "factor_registry",
                "status": "completed",
                "legacy_migration": migration,
                "historical_card_count": history["card_count"],
            }
        )

        sec_decision = build_sec_companyfacts_fundamentals(
            contract_path=paths["fundamental_source_contract"],
            output_dir=directories["sec_source"],
            client=sec_client,
        )
        if sec_decision.get("source_run_completed") is not True:
            raise ValueError(
                f"SEC source did not complete: {sec_decision.get('reason', sec_decision.get('decision'))}"
            )
        coverage = _validate_sec_coverage(
            directories["sec_source"] / "coverage_report.json",
            pipeline=pipeline,
            pool_path=paths["pool_spec"],
        )
        filtered_fundamentals = directories["sec_source"] / "fundamentals_as_of.csv"
        filtering = _filter_fundamentals_as_of(
            directories["sec_source"] / "fundamentals.csv",
            filtered_fundamentals,
            as_of=as_of,
        )
        stages.append(
            {
                "stage": "sec_source",
                "status": "completed",
                "decision": sec_decision["decision"],
                "coverage": coverage,
                "as_of_filter": filtering,
            }
        )

        fundamental_decision = run_fundamental_acceleration(
            contract_path=paths["fundamental_factor_contract"],
            fundamentals_csv=filtered_fundamentals,
            prices_csv=prices_path,
            output_dir=directories["fundamental_factor"],
            registry_db=registry_path,
        )
        stages.append(
            {
                "stage": "fundamental_factor",
                "status": "completed",
                "decision": fundamental_decision["decision"],
            }
        )

        hierarchical_decision = run_hierarchical_pool_rotation(
            spec_path=paths["rotation_spec"],
            prices_csv=prices_path,
            output_dir=directories["hierarchical_rotation"],
            authoritative_mode=False,
        )
        stages.append(
            {
                "stage": "hierarchical_basket_context",
                "status": "completed",
                "decision": hierarchical_decision["decision"],
            }
        )

        multifactor_contract = yaml.safe_load(
            paths["multifactor_contract"].read_text(encoding="utf-8")
        )
        relationship_end = str(multifactor_contract["windows"]["falsification_end"])
        relationship_inputs = build_factor_relationship_inputs(
            pipeline_contract_path=resolved_pipeline,
            multifactor_contract_path=paths["multifactor_contract"],
            fundamental_scores_path=(
                directories["fundamental_factor"] / "factor_scores.json"
            ),
            basket_scores_path=(
                directories["hierarchical_rotation"] / "basket_score_history.json"
            ),
            prices_csv=prices_path,
            output_dir=directories["relationship_inputs"],
            relationship_end_date=relationship_end,
        )
        stages.append(
            {
                "stage": "relationship_inputs",
                "status": "completed",
                "decision": relationship_inputs["decision"],
                "end_date": relationship_inputs["end_date"],
            }
        )

        relationship_decision = build_factor_relationship_map(
            contract_path=paths["relationship_contract"],
            input_manifest_path=(
                directories["relationship_inputs"] / "input_manifest.json"
            ),
            registry_db=registry_path,
            output_dir=directories["relationship_map"],
        )
        stages.append(
            {
                "stage": "relationship_map",
                "status": "completed",
                "decision": relationship_decision["decision"],
                "redundancy_cluster_count": relationship_decision[
                    "redundancy_cluster_count"
                ],
            }
        )

        multifactor_decision = run_low_turnover_multifactor_pipeline(
            contract_path=paths["multifactor_contract"],
            fundamental_scores_path=(
                directories["fundamental_factor"] / "factor_scores.json"
            ),
            basket_scores_path=(
                directories["hierarchical_rotation"] / "basket_score_history.json"
            ),
            relationship_map_path=(
                directories["relationship_map"] / "factor_relationships.json"
            ),
            prices_csv=prices_path,
            registry_db=registry_path,
            output_dir=directories["multifactor"],
        )
        if multifactor_decision["decision"] == (
            "multifactor_candidate_failed_turnover_contract"
        ):
            raise ValueError("multifactor candidate failed its turnover contract")
        stages.append(
            {
                "stage": "multifactor",
                "status": "completed",
                "decision": multifactor_decision["decision"],
                "turnover": multifactor_decision["turnover_diagnostics"],
            }
        )

        adapter_decision = build_multifactor_shadow_artifacts(
            hierarchical_dir=directories["hierarchical_rotation"],
            multifactor_dir=directories["multifactor"],
            output_dir=directories["shadow_overlay"],
            benchmark="QQQ",
        )
        stages.append(
            {
                "stage": "shadow_overlay",
                "status": "completed",
                "decision": adapter_decision["decision"],
                "hierarchical_positions_used": False,
            }
        )

        ticket = build_shadow_decision_ticket(
            rotation_dir=directories["shadow_overlay"],
            registry_db=registry_path,
            ledger_dir=ledger,
            market="us",
            as_of_date=as_of.isoformat(),
            factor_scores_path=(
                directories["multifactor"] / "multifactor_scores.json"
            ),
            annual_turnover_budget=float(
                multifactor_contract["portfolio"]["annual_turnover_ceiling"]
            ),
        )
        stages.append(
            {
                "stage": "shadow_ticket",
                "status": "completed",
                "ticket_identity_sha256": ticket["ticket_identity_sha256"],
                "warning_count": len(ticket["warnings"]),
            }
        )

        manifests = {
            "sec_source": _stage_manifest(
                directories["sec_source"] / "evidence_manifest.json"
            ),
            "fundamental_factor": _stage_manifest(
                directories["fundamental_factor"] / "evidence_manifest.json"
            ),
            "hierarchical_rotation": _stage_manifest(
                directories["hierarchical_rotation"] / "evidence_manifest.json"
            ),
            "relationship_inputs": _stage_manifest(
                directories["relationship_inputs"] / "input_manifest.json"
            ),
            "relationship_map": _stage_manifest(
                directories["relationship_map"] / "evidence_manifest.json"
            ),
            "multifactor": _stage_manifest(
                directories["multifactor"] / "evidence_manifest.json"
            ),
            "shadow_overlay": _stage_manifest(
                directories["shadow_overlay"] / "evidence_manifest.json"
            ),
        }
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "pipeline_id": pipeline["pipeline_id"],
            "status": "completed_diagnostic_pipeline",
            "market": "us",
            "as_of_date": as_of.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "diagnostic_only": True,
            "trade_ready": False,
            "performance_evaluated": False,
            "independent_validation_completed": False,
            "automatic_order_routing": False,
            "inputs": {
                "pipeline_contract_sha256": _sha256_file(resolved_pipeline),
                "cutover_contract_sha256": _sha256_file(cutover_path),
                "cutover_contract_id": cutover["contract_id"],
                "prices_sha256": _sha256_file(prices_path),
                "registry_db_sha256": _sha256_file(registry_path),
            },
            "stage_manifests": manifests,
            "ticket": {
                "path": str(ledger / "us" / f"{as_of.isoformat()}.json"),
                "ticket_identity_sha256": ticket["ticket_identity_sha256"],
                "file_sha256": _sha256_file(
                    ledger / "us" / f"{as_of.isoformat()}.json"
                ),
            },
            "stages": stages,
        }
        manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
        _write_json(workspace / str(pipeline["outputs"]["top_level_manifest"]), manifest)
        decision = {
            "schema_version": "1.0",
            "decision": "us_low_turnover_diagnostic_ticket_ready",
            "pipeline_id": pipeline["pipeline_id"],
            "market": "us",
            "as_of_date": as_of.isoformat(),
            "research_only": True,
            "diagnostic_only": True,
            "trade_ready": False,
            "performance_evaluated": False,
            "ticket_identity_sha256": ticket["ticket_identity_sha256"],
            "pipeline_manifest_identity_sha256": manifest[
                "manifest_identity_sha256"
            ],
            "warnings": ticket["warnings"],
        }
        _write_json(workspace / "pipeline_decision.json", decision)
        return decision
    except Exception as exc:
        blocked = {
            "schema_version": "1.0",
            "decision": "us_low_turnover_decision_pipeline_blocked",
            "pipeline_id": pipeline["pipeline_id"],
            "market": "us",
            "as_of_date": as_of.isoformat(),
            "research_only": True,
            "diagnostic_only": True,
            "trade_ready": False,
            "performance_evaluated": False,
            "automatic_order_routing": False,
            "failure_type": type(exc).__name__,
            "reason": str(exc),
            "stages": stages,
        }
        _write_json(workspace / "pipeline_decision.json", blocked)
        return blocked
