#!/usr/bin/env python3
"""Run churn and dwell-time diagnostics for the frozen v4.1 attack layer."""

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
from src.research.vxn_attack_layer_long_history import run_attack_layer_comparison
from src.research.vxn_churn_diagnostics import (
    reentry_cycles,
    round_trip_summary,
    state_dwell_table,
    summarize_churn,
    transition_cost_by_reason,
    vxn_only_exit_events,
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
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqq_tqqq_vxn_v4_1_churn_diagnostics.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqq_tqqq_vxn_v4_1_churn_diagnostics"),
    )
    parser.add_argument(
        "--strategy-run-dir", type=Path, default=Path("artifacts/strategy_runs")
    )
    args = parser.parse_args()

    diagnostic_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    base_contract_path = Path(diagnostic_contract["base_contract"])
    base_contract = yaml.safe_load(base_contract_path.read_text(encoding="utf-8"))
    boundaries = base_contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=base_contract["data"]["start_date"],
        end=args.end_date or base_contract["data"].get("end_date"),
    )
    metrics, results, prepared, _, base_tables = run_attack_layer_comparison(
        bars, base_contract
    )
    baseline = results["attack_vix_v3_75"]
    overlay = results["attack_vxn_v4_1_75"]

    dwell = pd.concat(
        [state_dwell_table(baseline), state_dwell_table(overlay)],
        ignore_index=True,
    )
    thresholds = diagnostic_contract["diagnostics"][
        "round_trip_thresholds_sessions"
    ]
    round_trips = round_trip_summary(dwell, thresholds)
    cycles = reentry_cycles(dwell, overlay.daily.index)
    transition_costs = pd.concat(
        [transition_cost_by_reason(baseline), transition_cost_by_reason(overlay)],
        ignore_index=True,
    )
    exit_events = vxn_only_exit_events(
        prepared,
        baseline,
        overlay,
        diagnostic_contract["diagnostics"]["event_horizons"],
    )
    quick_window = int(diagnostic_contract["diagnostics"]["quick_reentry_sessions"])
    summary = summarize_churn(
        baseline,
        overlay,
        dwell,
        cycles,
        exit_events,
        quick_reentry_sessions=quick_window,
    )
    summary.update(
        {
            "experiment_id": diagnostic_contract["experiment_id"],
            "parent_experiment_id": diagnostic_contract["parent_experiment_id"],
            "research_only": True,
            "trade_ready": False,
            "diagnostic_only": True,
            "strategy_rule_changed": False,
            "sample_start": prepared.index.min().date().isoformat(),
            "sample_end": prepared.index.max().date().isoformat(),
            "quick_reentry_sessions": quick_window,
            "blocked_entry_count": int(len(base_tables["blocked_vxn_entries"])),
        }
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    dwell.to_csv(output / "state_dwell.csv", index=False)
    round_trips.to_csv(output / "round_trip_summary.csv", index=False)
    cycles.to_csv(output / "reentry_cycles.csv", index=False)
    transition_costs.to_csv(output / "transition_cost_by_reason.csv", index=False)
    exit_events.to_csv(output / "vxn_only_exit_events.csv", index=False)
    base_tables["blocked_vxn_entries"].to_csv(
        output / "blocked_vxn_entries.csv", index=False
    )
    (output / "summary.json").write_text(
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
        "research_only": True,
        "trade_ready": False,
        "diagnostic_only": True,
        "strategy_rule_changed": False,
        "contract": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "base_contract": str(base_contract_path),
        "base_contract_sha256": _sha256(base_contract_path),
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
        "experiment_id": diagnostic_contract["experiment_id"],
        "parent_experiment_id": diagnostic_contract["parent_experiment_id"],
        "run_id": run_id,
        "created_at": created.isoformat(),
        "status": "completed",
        "decision": "diagnostics_only_no_rule_change",
        "market": "us",
        "strategy_family": "qqq_tqqq_attack_layer_risk_budget",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.contract),
            "sha256": _sha256(args.contract),
            "base_contract_path": str(base_contract_path),
            "base_contract_sha256": _sha256(base_contract_path),
            "diagnostic_only": True,
            "strategy_rule_changed": False,
        },
        "data": {
            "provider": base_contract["data"]["provider"],
            "sample_start": summary["sample_start"],
            "sample_end": summary["sample_end"],
        },
        "metrics": {key: dict(result.metrics) for key, result in results.items()},
        "diagnostics": summary,
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
