#!/usr/bin/env python3
"""Materialize QQQ Rotation v4.3 as the active formal baseline."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.artifacts.formal_refresh import load_object, sha256, write_object
from src.artifacts.qqq_v4_3_formal import DISPLAY_NAME, JOINT_STRATEGY, MODEL_ID, build_formal_package
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison

OLD_MODEL_ID = "qqqi_qqq_tqqq_v4_2"
OLD_PACKAGE = "qqqi_qqq_tqqq_v4_2.json"
NEW_PACKAGE = "qqqi_qqq_tqqq_v4_3.json"


def _replace_catalog(output_root: Path, package_sha: str, generated_at: str) -> None:
    path = output_root / "catalog.json"
    catalog = load_object(path)
    records = catalog.get("records")
    if not isinstance(records, list):
        raise ValueError("formal catalog records are invalid")
    replaced = False
    new_records: list[dict[str, object]] = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("formal catalog record is invalid")
        if row.get("model_id") == OLD_MODEL_ID:
            new_records.append(
                {
                    "display_name": DISPLAY_NAME,
                    "display_order": int(row.get("display_order", 1)),
                    "model_id": MODEL_ID,
                    "path": NEW_PACKAGE,
                    "publication_status": "accepted_formal_baseline",
                    "sha256": package_sha,
                }
            )
            replaced = True
        else:
            new_records.append(dict(row))
    if not replaced:
        raise ValueError("active QQQ v4.2 catalog record was not found")
    if any(row.get("model_id") == OLD_MODEL_ID for row in new_records):
        raise ValueError("active QQQ v4.2 identity survived promotion")
    catalog["records"] = new_records
    catalog["published_at"] = generated_at
    write_object(path, catalog)


def promote(
    *,
    current_root: Path,
    output_root: Path,
    bridge_contract_path: Path,
    end_date: str,
    evidence_cutoff: str,
    generated_at: str,
    bundle_dir: Path | None,
) -> dict[str, object]:
    if output_root.exists():
        shutil.rmtree(output_root)
    shutil.copytree(current_root, output_root)

    bridge_contract = yaml.safe_load(bridge_contract_path.read_text(encoding="utf-8"))
    symbols = ["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"]
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=symbols,
        start=bridge_contract["data"]["start_date"],
        end=end_date,
        bundle_dir=bundle_dir,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=end_date)
    _, results, diagnostics = run_v4_33_comparison(
        bars,
        bridge_contract,
        fear_greed,
        cash_symbol="SGOV",
    )
    result = results[JOINT_STRATEGY]
    evidence = {
        "promotion_issue": 643,
        "research_source_experiment": "qqqi_qqq_tqqq_v4_33_ma200_ma20_vix_release",
        "research_result_report": "docs/research/qqqi_qqq_tqqq_v4_33_ma200_ma20_vix_release_result_2026-08-08.md",
        "fresh_evidence_workflow_run": 31204072434,
        "fresh_evidence_artifact_id": 9004000740,
        "fresh_evidence_artifact_digest": "sha256:7a94663c302268ab3c6fa970b41b2f306103de3dc46b714ab98c1017965601e0",
        "baseline_contract_path": bridge_contract_path.as_posix(),
        "baseline_contract_sha256": sha256(bridge_contract_path),
        "data_identity": data_identity,
        "coverage": coverage.to_dict("records"),
        "retrospective_diagnostics": diagnostics,
        "original_retrospective_gate": "v4_33_final_release_promising_gate_failed",
        "promotion_basis": "owner_selected_drawdown_calmar_risk_budget_tradeoff",
        "model_selection_reopened": False,
    }
    freshness = {
        "status": "current",
        "required_cutoff": evidence_cutoff,
        "latest_completed_session": evidence_cutoff,
        "latest_realized_holding_end": result.daily.index.max().date().isoformat(),
        "model_selection_reopened": False,
        "data_bundle_id": data_identity.get("bundle_id"),
        "research_only": True,
        "trade_ready": False,
    }
    package = build_formal_package(
        result,
        bars,
        generated_at=generated_at,
        evidence_cutoff=evidence_cutoff,
        backtest_id=f"{MODEL_ID}-promotion-through-{evidence_cutoff.replace('-', '_')}",
        evidence=evidence,
        freshness=freshness,
    )
    package_path = output_root / NEW_PACKAGE
    write_object(package_path, package)
    old_path = output_root / OLD_PACKAGE
    if old_path.exists():
        old_path.unlink()
    package_sha = sha256(package_path)
    _replace_catalog(output_root, package_sha, generated_at)

    receipt = {
        "schema_version": "1.0.0",
        "status": "qqq_v4_3_formal_promotion_materialized",
        "superseded_active_model_id": OLD_MODEL_ID,
        "promoted_model_id": MODEL_ID,
        "package_path": package_path.as_posix(),
        "package_sha256": package_sha,
        "catalog_sha256": sha256(output_root / "catalog.json"),
        "evidence_cutoff": evidence_cutoff,
        "economic_end": result.daily.index.max().date().isoformat(),
        "metrics": dict(result.metrics),
        "original_retrospective_gate_passed": False,
        "promotion_basis": "explicit_owner_risk_budget_decision",
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_object(output_root / "v4_3_promotion_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-root", type=Path, default=Path("data/research/formal_backtests"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--bridge-contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
    )
    parser.add_argument("--end-date", default="2026-08-06")
    parser.add_argument("--evidence-cutoff", default="2026-08-06")
    parser.add_argument("--generated-at")
    parser.add_argument("--etf-data-bundle", type=Path)
    args = parser.parse_args()
    generated_at = args.generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    receipt = promote(
        current_root=args.current_root,
        output_root=args.output_root,
        bridge_contract_path=args.bridge_contract,
        end_date=args.end_date,
        evidence_cutoff=args.evidence_cutoff,
        generated_at=generated_at,
        bundle_dir=args.etf_data_bundle,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
