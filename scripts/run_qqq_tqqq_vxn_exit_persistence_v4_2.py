#!/usr/bin/env python3
"""Run the single two-close VXN exit-persistence experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.strategy_experiment_journal import write_strategy_run_record
from src.research.vxn_exit_persistence_experiment import (
    run_vxn_exit_persistence_comparison,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric_delta(
    challenger: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, float]:
    fields = (
        "total_return",
        "cagr",
        "annual_volatility",
        "max_drawdown",
        "sharpe",
        "sortino",
        "calmar",
        "switch_count",
        "turnover_units",
        "transaction_cost_paid",
        "pct_time_partial_tqqq",
        "average_tqqq_weight",
    )
    return {
        f"{field}_delta": float(challenger[field] - baseline[field])
        for field in fields
        if field in challenger and field in baseline
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqq_tqqq_vxn_exit_persistence_v4_2.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqq_tqqq_vxn_exit_persistence_v4_2"
        ),
    )
    parser.add_argument(
        "--strategy-run-dir", type=Path, default=Path("artifacts/strategy_runs")
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    base_contract_path = Path(contract["base_contract"])
    base_contract = yaml.safe_load(base_contract_path.read_text(encoding="utf-8"))
    contract["resolved_base_contract"] = base_contract
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
    metrics, results, prepared, diagnostics, tables = (
        run_vxn_exit_persistence_comparison(bars, contract)
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    prepared.to_csv(output / "prepared_signal_frame.csv")
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
    for name, table in tables.items():
        table.to_csv(output / f"{name}.csv", index=False)

    baseline = results["attack_vxn_v4_1_75"].metrics
    challenger = results["attack_vxn_exit_persistence_v4_2_75"].metrics
    summary = {
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "post_result_hypothesis": True,
        "research_only": True,
        "trade_ready": False,
        "sample_start": prepared.index.min().date().isoformat(),
        "sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": baseline["start_date"],
        "economic_return_end": baseline["end_date"],
        "comparison": metrics.reset_index().to_dict(orient="records"),
        "relative_to_v4_1_immediate_exit": _metric_delta(challenger, baseline),
        "diagnostics": diagnostics,
        "interpretation_guardrails": [
            "The only change is one versus two consecutive VXN-stress closes for an existing-leverage VXN-only exit.",
            "New-entry VXN vetoes, VIX exits, price exits and 75% TQQQ weight are frozen.",
            "No alternative persistence length or cooldown is tested.",
            "Lower turnover is insufficient if risk-adjusted performance deteriorates.",
        ],
    }
    summary_path = output / "summary.json"
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
        "research_only": True,
        "trade_ready": False,
        "post_result_hypothesis": True,
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
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "run_id": run_id,
        "created_at": created.isoformat(),
        "status": "completed",
        "decision": "single_rule_challenger_requires_review",
        "market": "us",
        "strategy_family": "qqq_tqqq_attack_layer_risk_budget",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.contract),
            "sha256": _sha256(args.contract),
            "base_contract_path": str(base_contract_path),
            "base_contract_sha256": _sha256(base_contract_path),
            "only_allowed_change": diagnostics["only_allowed_change"],
            "baseline_value": 1,
            "challenger_value": 2,
        },
        "data": {
            "provider": base_contract["data"]["provider"],
            "sample_start": summary["sample_start"],
            "sample_end": summary["sample_end"],
            "economic_return_start": summary["economic_return_start"],
            "economic_return_end": summary["economic_return_end"],
        },
        "metrics": {key: dict(result.metrics) for key, result in results.items()},
        "comparisons": {
            "relative_to_v4_1_immediate_exit": summary[
                "relative_to_v4_1_immediate_exit"
            ]
        },
        "diagnostics": diagnostics,
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
