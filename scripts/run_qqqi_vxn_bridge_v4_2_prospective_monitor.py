#!/usr/bin/env python3
"""Run side-by-side prospective monitoring for frozen v4.1 and bridge v4.2."""

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

from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.strategy_experiment_journal import write_strategy_run_record
from src.research.vix_rotation_experiment import config_from_contract
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
)
from src.research.vxn_prospective_monitor import (
    latest_monitor_snapshot,
    monitoring_status,
    prospective_return_metrics,
)

BASELINE = "rotation_vxn_leverage_v4_1_75"
BRIDGE = "rotation_vxn_bridge_v4_2_50_50"


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prospective_allocation_differences(
    baseline: pd.DataFrame,
    bridge: pd.DataFrame,
    start_date: str,
) -> pd.DataFrame:
    start = pd.Timestamp(start_date).tz_localize(None).normalize()
    index = baseline.index.intersection(bridge.index)
    index = index[index >= start]
    columns = [
        "position_state",
        "position_label",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "gross_return",
        "turnover_units",
        "transaction_cost",
        "net_return",
    ]
    if len(index) == 0:
        return pd.DataFrame(
            columns=[
                "date",
                "position_state",
                "position_label",
                "baseline_weight_QQQI",
                "baseline_weight_QQQ",
                "baseline_weight_TQQQ",
                "bridge_weight_QQQI",
                "bridge_weight_QQQ",
                "bridge_weight_TQQQ",
                "baseline_gross_return",
                "bridge_gross_return",
                "gross_return_delta",
                "baseline_turnover_units",
                "bridge_turnover_units",
                "turnover_units_delta",
                "baseline_transaction_cost",
                "bridge_transaction_cost",
                "transaction_cost_delta",
                "baseline_net_return",
                "bridge_net_return",
                "net_return_delta",
            ]
        )
    left = baseline.loc[index, columns].copy()
    right = bridge.loc[index, columns].copy()
    if not left["position_state"].equals(right["position_state"]):
        raise AssertionError("prospective candidate state traces diverged")
    out = pd.DataFrame(index=index)
    out["position_state"] = left["position_state"]
    out["position_label"] = left["position_label"]
    for asset in ("QQQI", "QQQ", "TQQQ"):
        out[f"baseline_weight_{asset}"] = left[f"weight_{asset}"]
        out[f"bridge_weight_{asset}"] = right[f"weight_{asset}"]
    for field in ("gross_return", "turnover_units", "transaction_cost", "net_return"):
        out[f"baseline_{field}"] = left[field]
        out[f"bridge_{field}"] = right[field]
        out[f"{field}_delta"] = right[field] - left[field]
    return out.reset_index(names="date")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monitor-contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_vxn_bridge_v4_2_prospective_monitor.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_vxn_bridge_v4_2_prospective_monitor"
        ),
    )
    parser.add_argument(
        "--strategy-run-dir",
        type=Path,
        default=Path("artifacts/strategy_runs"),
    )
    args = parser.parse_args()

    monitor_contract = yaml.safe_load(
        args.monitor_contract.read_text(encoding="utf-8")
    )
    bridge_contract_path = Path(monitor_contract["bridge_contract"])
    bridge_contract = yaml.safe_load(
        bridge_contract_path.read_text(encoding="utf-8")
    )
    monitoring_start = str(monitor_contract["monitoring_start_date"])

    boundaries = bridge_contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=bridge_contract["data"]["start_date"],
        end=args.end_date or bridge_contract["data"].get("end_date"),
    )
    full_metrics, results, prepared, retrospective_diagnostics = (
        run_bridge_allocation_comparison(bars, bridge_contract)
    )
    config = config_from_contract(bridge_contract)
    decisions = generate_vxn_leverage_veto_states(prepared, config)

    tracked_keys = list(monitor_contract["monitoring"]["benchmark_strategies"])
    prospective_metrics = {
        key: prospective_return_metrics(results[key], monitoring_start)
        for key in tracked_keys
    }
    allocation_differences = _prospective_allocation_differences(
        results[BASELINE].daily,
        results[BRIDGE].daily,
        monitoring_start,
    )
    baseline_snapshot = latest_monitor_snapshot(
        prepared,
        results[BASELINE],
        decisions,
    )
    bridge_snapshot = latest_monitor_snapshot(
        prepared,
        results[BRIDGE],
        decisions,
    )
    overall_status = monitoring_status(prospective_metrics)

    state_one = allocation_differences.loc[
        allocation_differences["position_state"].eq(1)
    ]
    difference_summary = {
        "prospective_rows": int(len(allocation_differences)),
        "prospective_state_1_rows": int(len(state_one)),
        "gross_return_delta_sum": float(
            allocation_differences["gross_return_delta"].sum()
        ),
        "turnover_delta_sum": float(
            allocation_differences["turnover_units_delta"].sum()
        ),
        "cost_delta_sum": float(
            allocation_differences["transaction_cost_delta"].sum()
        ),
        "net_return_delta_sum": float(
            allocation_differences["net_return_delta"].sum()
        ),
    }

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    full_metrics.to_csv(output / "full_history_metrics_context.csv")
    pd.DataFrame(prospective_metrics.values()).to_csv(
        output / "prospective_metrics.csv", index=False
    )
    allocation_differences.to_csv(
        output / "prospective_allocation_differences.csv", index=False
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
            results[BRIDGE].daily.index.max().date().isoformat()
            if not results[BRIDGE].daily.empty
            else None
        ),
        "prospective_metrics": prospective_metrics,
        "prospective_difference_summary": difference_summary,
        "baseline_latest_snapshot": baseline_snapshot,
        "bridge_latest_snapshot": bridge_snapshot,
        "retrospective_context_only": {
            "full_history_metrics": full_metrics.reset_index().to_dict(
                orient="records"
            ),
            "diagnostics": retrospective_diagnostics,
        },
        "guardrails": [
            "Only returns dated on or after 2026-08-01 are prospective.",
            "v4.1 and bridge v4.2 state decisions remain identical.",
            "No bridge weight or signal parameter may change in this monitor.",
            "Full-history recomputation is context only.",
            "The workflow cannot promote either candidate.",
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
        "schema_version": "1.0",
        "prospective_monitoring": True,
        "monitoring_start_date": monitoring_start,
        "research_only": True,
        "trade_ready": False,
        "monitor_contract": str(args.monitor_contract),
        "monitor_contract_sha256": _sha256(args.monitor_contract),
        "bridge_contract": str(bridge_contract_path),
        "bridge_contract_sha256": _sha256(bridge_contract_path),
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
        "schema_version": "1.0",
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
            "bridge_contract_path": str(bridge_contract_path),
            "bridge_contract_sha256": _sha256(bridge_contract_path),
            "monitoring_start_date": monitoring_start,
            "no_parameter_change": True,
        },
        "data": {
            "provider": bridge_contract["data"]["provider"],
            "latest_data_date": summary["latest_data_date"],
            "latest_economic_return_date": summary[
                "latest_economic_return_date"
            ],
        },
        "metrics": prospective_metrics,
        "diagnostics": {
            "prospective_difference_summary": difference_summary,
            "baseline_latest_snapshot": baseline_snapshot,
            "bridge_latest_snapshot": bridge_snapshot,
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
