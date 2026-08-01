#!/usr/bin/env python3
"""Run frozen market-breadth and VXN challengers against VIX v3."""

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

from src.research.breadth_vxn_rotation_experiment import run_breadth_vxn_comparison
from src.research.etf_rotation_experiment import (
    chronological_split_metrics,
    fetch_adjusted_daily_bars,
)
from src.research.strategy_experiment_journal import write_strategy_run_record


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
        "switch_count",
        "turnover_units",
        "transaction_cost_paid",
        "pct_time_partial_tqqq",
        "average_tqqq_weight",
    )
    output: dict[str, float] = {}
    for field in fields:
        if field in challenger and field in baseline:
            output[f"{field}_delta"] = float(challenger[field] - baseline[field])
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_breadth_vxn_v4.yaml"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_breadth_vxn_v4"),
    )
    parser.add_argument(
        "--strategy-run-dir",
        type=Path,
        default=Path("artifacts/strategy_runs"),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    end_date = args.end_date or contract["data"].get("end_date")
    boundaries = contract["boundaries"]
    symbols = list(
        dict.fromkeys(
            [
                *boundaries["tradable_symbols"],
                boundaries["vix_symbol"],
                boundaries["vxn_symbol"],
                boundaries["breadth_symbol"],
            ]
        )
    )
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=contract["data"]["start_date"],
        end=end_date,
    )
    metrics, results, prepared, diagnostics = run_breadth_vxn_comparison(bars, contract)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    prepared.to_csv(output / "prepared_signal_frame.csv")
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)

    split_frames: list[pd.DataFrame] = []
    train_fraction = float(contract["validation"]["chronological_train_fraction"])
    for key, result in results.items():
        split = chronological_split_metrics(
            result,
            train_fraction=train_fraction,
        ).reset_index()
        split.insert(0, "strategy", key)
        split_frames.append(split)
    chronological = pd.concat(split_frames, ignore_index=True)
    chronological.to_csv(output / "chronological_split.csv", index=False)

    (output / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    baseline = results["rotation_vix_v3_75"].metrics
    challenger_keys = (
        "rotation_breadth_v4_75",
        "rotation_vxn_only_v4_75",
        "rotation_vix_vxn_confirm_v4_75",
    )
    summary = {
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "common_price_sample_start": prepared.index.min().date().isoformat(),
        "common_price_sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": baseline["start_date"],
        "economic_return_end": baseline["end_date"],
        "comparison": metrics.reset_index().to_dict(orient="records"),
        "relative_to_vix_v3_75": {
            key: _metric_delta(results[key].metrics, baseline) for key in challenger_keys
        },
        "diagnostics": diagnostics,
        "interpretation_guardrails": [
            "Breadth and VXN are evaluated as separate information additions before any combined promotion claim.",
            "QQQE/QQQ is a breadth proxy, not a direct constituent-count breadth series.",
            "VXN is Nasdaq-100 expected volatility and is not assumed to be a directional forecast.",
            "Thresholds and lookbacks are frozen and may not be tuned from this observed result.",
            "QQQI inception limits the true common sample to 2024 onward.",
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
        "decision": "unreviewed_factor_validation",
        "market": "us",
        "strategy_family": "qqqi_qqq_tqqq_recovery_risk_budget",
        "research_only": True,
        "trade_ready": False,
        "contract": {
            "path": str(args.contract),
            "sha256": _sha256(args.contract),
            "breadth_proxy": "QQQE/QQQ",
            "vxn_symbol": boundaries["vxn_symbol"],
        },
        "data": {
            "provider": contract["data"]["provider"],
            "sample_start": summary["common_price_sample_start"],
            "sample_end": summary["common_price_sample_end"],
            "economic_return_start": summary["economic_return_start"],
            "economic_return_end": summary["economic_return_end"],
        },
        "metrics": {
            key: dict(result.metrics) for key, result in results.items()
        },
        "comparisons": summary["relative_to_vix_v3_75"],
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
