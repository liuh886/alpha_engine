#!/usr/bin/env python3
"""Run prospective monitoring for the unchanged v4.1 VXN leverage veto."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.strategy_experiment_journal import write_strategy_run_record
from src.research.vix_rotation_experiment import (
    config_from_contract,
    generate_vix_decision_states,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
    run_vxn_leverage_overlay_comparison,
)
from src.research.vxn_prospective_monitor import (
    latest_monitor_snapshot,
    monitoring_status,
    prospective_return_metrics,
    prospective_state_differences,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monitor-contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_vxn_v4_1_prospective_monitor.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--etf-data-bundle",
        type=Path,
        default=None,
        help="Governed QQQ/QQQI/TQQQ bundle; VIX/VXN remain direct references.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqqi_qqq_tqqq_vxn_v4_1_prospective_monitor"
        ),
    )
    parser.add_argument(
        "--strategy-run-dir", type=Path, default=Path("artifacts/strategy_runs")
    )
    args = parser.parse_args()

    monitor_contract = yaml.safe_load(
        args.monitor_contract.read_text(encoding="utf-8")
    )
    base_contract_path = Path(monitor_contract["base_contract"])
    base_contract = yaml.safe_load(base_contract_path.read_text(encoding="utf-8"))
    monitoring_start = str(monitor_contract["monitoring_start_date"])

    boundaries = base_contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=base_contract["data"]["start_date"],
        end=args.end_date or base_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    full_metrics, results, prepared, retrospective_diagnostics = (
        run_vxn_leverage_overlay_comparison(bars, base_contract)
    )
    config = config_from_contract(base_contract)
    baseline_decisions = generate_vix_decision_states(prepared, config)
    overlay_decisions = generate_vxn_leverage_veto_states(prepared, config)

    tracked_keys = list(monitor_contract["monitoring"]["benchmark_strategies"])
    prospective_metrics = {
        key: prospective_return_metrics(results[key], monitoring_start)
        for key in tracked_keys
    }
    event_horizons = [
        int(value) for value in monitor_contract["monitoring"]["event_horizons"]
    ]
    state_differences = prospective_state_differences(
        prepared,
        baseline_decisions,
        overlay_decisions,
        start_date=monitoring_start,
        horizons=event_horizons,
    )
    snapshot = latest_monitor_snapshot(
        prepared,
        results["rotation_vxn_leverage_v4_1_75"],
        overlay_decisions,
    )
    overall_status = monitoring_status(prospective_metrics)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    full_metrics.to_csv(output / "full_history_metrics_context.csv")
    pd.DataFrame(prospective_metrics.values()).to_csv(
        output / "prospective_metrics.csv", index=False
    )
    state_differences.to_csv(
        output / "prospective_vxn_state_differences.csv", index=False
    )
    for key in tracked_keys:
        daily = results[key].daily
        daily.loc[daily.index >= pd.Timestamp(monitoring_start)].to_csv(
            output / f"prospective_daily_{key}.csv"
        )

    summary = {
        "experiment_id": monitor_contract["experiment_id"],
        "parent_experiment_id": monitor_contract["parent_experiment_id"],
        "prospective_monitoring": True,
        "monitoring_start_date": monitoring_start,
        "status": overall_status,
        "research_only": True,
        "trade_ready": False,
        "latest_data_date": prepared.index.max().date().isoformat(),
        "latest_economic_return_date": (
            results["rotation_vxn_leverage_v4_1_75"].daily.index.max().date().isoformat()
            if not results["rotation_vxn_leverage_v4_1_75"].daily.empty
            else None
        ),
        "data_identity": data_identity,
        "prospective_metrics": prospective_metrics,
        "prospective_vxn_state_difference_count": int(len(state_differences)),
        "latest_snapshot": snapshot,
        "retrospective_context_only": {
            "full_history_metrics": full_metrics.reset_index().to_dict(
                orient="records"
            ),
            "diagnostics": retrospective_diagnostics,
        },
        "guardrails": [
            "Only returns dated on or after 2026-08-01 are labelled prospective.",
            "The v4.1 contract is unchanged and no rejected factor is active.",
            "Full-history recomputation is context only, not new prospective evidence.",
            "QQQ, QQQI and TQQQ use the declared governed bundle when supplied.",
            "This workflow cannot mark the strategy trade ready or promote it.",
        ],
    }
    summary_path = output / "prospective_summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    output_files = sorted(path for path in output.iterdir() if path.is_file())
    manifest = {
        "schema_version": "1.1",
        "prospective_monitoring": True,
        "monitoring_start_date": monitoring_start,
        "research_only": True,
        "trade_ready": False,
        "monitor_contract": str(args.monitor_contract),
        "monitor_contract_sha256": _sha256(args.monitor_contract),
        "base_contract": str(base_contract_path),
        "base_contract_sha256": _sha256(base_contract_path),
        "data_identity": data_identity,
        "outputs": {path.name: _sha256(path) for path in output_files},
    }
    manifest_path = output / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    created = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = f"{created.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    record = {
        "schema_version": "1.1",
        "experiment_id": monitor_contract["experiment_id"],
        "parent_experiment_id": monitor_contract["parent_experiment_id"],
        "run_id": run_id,
        "created_at": created.isoformat(),
        "status": overall_status,
        "decision": "prospective_monitoring_no_automatic_promotion",
        "market": "us",
        "strategy_family": "qqqi_qqq_tqqq_recovery_risk_budget",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.monitor_contract),
            "sha256": _sha256(args.monitor_contract),
            "base_contract_path": str(base_contract_path),
            "base_contract_sha256": _sha256(base_contract_path),
            "monitoring_start_date": monitoring_start,
            "no_parameter_change": True,
        },
        "data": {
            **data_identity,
            "latest_data_date": summary["latest_data_date"],
            "latest_economic_return_date": summary["latest_economic_return_date"],
        },
        "metrics": prospective_metrics,
        "diagnostics": {
            "prospective_vxn_state_difference_count": int(len(state_differences)),
            "latest_snapshot": snapshot,
        },
        "evidence": {
            "output_dir": str(output),
            "manifest_sha256": _sha256(manifest_path),
        },
        "git": {
            "sha": os.getenv("GITHUB_SHA"),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        },
    }
    journal_path = write_strategy_run_record(record, root=args.strategy_run_dir)
    (output / "run_record.json").write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {**summary, "strategy_run_record": str(journal_path)},
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
