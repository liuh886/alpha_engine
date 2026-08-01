#!/usr/bin/env python3
"""Run frozen long-history structural validation of the v4.1 attack layer."""

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
from src.research.vxn_attack_layer_long_history import run_attack_layer_comparison


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric_delta(challenger: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float]:
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
            "configs/research_paradigms/qqq_tqqq_vxn_attack_v4_1_long_history.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqq_tqqq_vxn_attack_v4_1_long_history"
        ),
    )
    parser.add_argument(
        "--strategy-run-dir", type=Path, default=Path("artifacts/strategy_runs")
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    boundaries = contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=contract["data"]["start_date"],
        end=args.end_date or contract["data"].get("end_date"),
    )
    metrics, results, prepared, diagnostics, tables = run_attack_layer_comparison(
        bars, contract
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

    baseline = results["attack_vix_v3_75"].metrics
    challenger = results["attack_vxn_v4_1_75"].metrics
    summary = {
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "historical_structural_validation": True,
        "post_result_hypothesis": True,
        "research_only": True,
        "trade_ready": False,
        "qqqi_excluded": True,
        "common_price_sample_start": prepared.index.min().date().isoformat(),
        "common_price_sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": baseline["start_date"],
        "economic_return_end": baseline["end_date"],
        "comparison": metrics.reset_index().to_dict(orient="records"),
        "relative_to_vix_v3_attack_layer": _metric_delta(challenger, baseline),
        "diagnostics": diagnostics,
        "interpretation_guardrails": [
            "QQQI is excluded; source states 0 and 1 both map to QQQ.",
            "The frozen v4.1 signal rules and 75% TQQQ weight are unchanged.",
            "This is retrospective structural validation, not independent prospective evidence.",
            "No signal threshold or leverage weight may be selected from this run.",
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
        "historical_structural_validation": True,
        "post_result_hypothesis": True,
        "contract": str(args.contract),
        "contract_sha256": _sha256(args.contract),
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
        "decision": "structural_validation_requires_review",
        "market": "us",
        "strategy_family": "qqq_tqqq_attack_layer_risk_budget",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.contract),
            "sha256": _sha256(args.contract),
            "post_result_hypothesis": True,
            "historical_structural_validation": True,
            "qqqi_excluded": True,
        },
        "data": {
            "provider": contract["data"]["provider"],
            "sample_start": summary["common_price_sample_start"],
            "sample_end": summary["common_price_sample_end"],
            "economic_return_start": summary["economic_return_start"],
            "economic_return_end": summary["economic_return_end"],
        },
        "metrics": {key: dict(result.metrics) for key, result in results.items()},
        "comparisons": {
            "relative_to_vix_v3_attack_layer": summary[
                "relative_to_vix_v3_attack_layer"
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
