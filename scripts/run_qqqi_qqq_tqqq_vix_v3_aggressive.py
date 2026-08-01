#!/usr/bin/env python3
"""Run the frozen 75% TQQQ challenger against the 50% VIX v2 baseline."""

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
from src.research.vix_aggressive_tqqq_experiment import run_aggressive_tqqq_comparison
from src.research.vix_rotation_experiment import VIX_SYMBOL


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
        "calmar",
        "turnover_units",
        "transaction_cost_paid",
        "average_tqqq_weight",
    )
    deltas: dict[str, float] = {}
    for field in fields:
        if field in challenger and field in baseline:
            deltas[f"{field}_delta"] = float(challenger[field] - baseline[field])
    return deltas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vix_v2.yaml"),
    )
    parser.add_argument(
        "--challenger-contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_vix_v3_aggressive.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_vix_v3_aggressive"),
    )
    parser.add_argument(
        "--strategy-run-dir",
        type=Path,
        default=Path("artifacts/strategy_runs"),
    )
    args = parser.parse_args()

    baseline_contract = yaml.safe_load(args.baseline_contract.read_text(encoding="utf-8"))
    challenger_contract = yaml.safe_load(args.challenger_contract.read_text(encoding="utf-8"))
    end_date = args.end_date or challenger_contract["data"].get("end_date")
    symbols = [*challenger_contract["boundaries"]["tradable_symbols"], VIX_SYMBOL]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=challenger_contract["data"]["start_date"],
        end=end_date,
    )
    metrics, results, prepared, diagnostics = run_aggressive_tqqq_comparison(
        bars,
        baseline_contract,
        challenger_contract,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    prepared.to_csv(output / "prepared_signal_frame.csv")
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
    (output / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    baseline = results["rotation_vix_v2_50"].metrics
    challenger = results["rotation_vix_v3_75"].metrics
    qqq = results["buy_hold_QQQ"].metrics
    no_vix = results["rotation_price_repair_v3_75"].metrics
    summary = {
        "experiment_id": challenger_contract["experiment_id"],
        "parent_experiment_id": challenger_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "common_price_sample_start": prepared.index.min().date().isoformat(),
        "common_price_sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": challenger["start_date"],
        "economic_return_end": challenger["end_date"],
        "comparison": metrics.reset_index().to_dict(orient="records"),
        "relative_to_vix_v2_50": _metric_delta(challenger, baseline),
        "relative_to_qqq": _metric_delta(challenger, qqq),
        "vix_incremental_vs_price_repair_75": _metric_delta(challenger, no_vix),
        "diagnostics": diagnostics,
        "interpretation_guardrails": [
            "The baseline and challenger use identical close decision and executed state traces.",
            "Any performance difference is therefore attributable to the 50% versus 75% TQQQ weight and associated turnover costs.",
            "Higher CAGR does not establish superiority if drawdown, Calmar or false-start loss deteriorates materially.",
            "QQQI inception limits the true common sample to 2024 onward.",
            "The challenger is not eligible for automatic promotion from this observed sample.",
        ],
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    output_files = sorted(path for path in output.iterdir() if path.is_file())
    manifest = {
        "schema_version": "1.0",
        "research_only": True,
        "trade_ready": False,
        "baseline_contract": str(args.baseline_contract),
        "baseline_contract_sha256": _sha256(args.baseline_contract),
        "challenger_contract": str(args.challenger_contract),
        "challenger_contract_sha256": _sha256(args.challenger_contract),
        "outputs": {path.name: _sha256(path) for path in output_files},
    }
    manifest_path = output / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = f"{created_at.replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}"
    record = {
        "schema_version": "1.0",
        "experiment_id": challenger_contract["experiment_id"],
        "parent_experiment_id": challenger_contract["parent_experiment_id"],
        "run_id": run_id,
        "created_at": created_at,
        "status": "completed",
        "decision": "unreviewed_research_challenger",
        "market": "us",
        "strategy_family": "qqqi_qqq_tqqq_vix_rotation",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.challenger_contract),
            "sha256": _sha256(args.challenger_contract),
            "baseline_path": str(args.baseline_contract),
            "baseline_sha256": _sha256(args.baseline_contract),
            "sole_executable_change": "portfolio.leveraged_tqqq_weight: 0.50 -> 0.75",
        },
        "data": {
            "provider": challenger_contract["data"]["provider"],
            "sample_start": summary["common_price_sample_start"],
            "sample_end": summary["common_price_sample_end"],
            "economic_return_start": summary["economic_return_start"],
            "economic_return_end": summary["economic_return_end"],
        },
        "metrics": dict(challenger),
        "comparisons": {
            "relative_to_vix_v2_50": summary["relative_to_vix_v2_50"],
            "relative_to_qqq": summary["relative_to_qqq"],
            "vix_incremental_vs_price_repair_75": summary[
                "vix_incremental_vs_price_repair_75"
            ],
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
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
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
