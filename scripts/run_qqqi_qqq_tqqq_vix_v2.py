#!/usr/bin/env python3
"""Run the frozen VIX-aware QQQI / QQQ / partial-TQQQ experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_rotation_experiment import (
    chronological_split_metrics,
    fetch_adjusted_daily_bars,
)
from src.research.vix_rotation_experiment import (
    VIX_SYMBOL,
    config_from_contract,
    vix_regime_asset_metrics,
    vix_repair_event_study,
    vix_signal_audit,
)
from src.research.vix_rotation_runtime import (
    run_vix_runtime_comparison,
    state_reachability,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric_delta(challenger: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "cagr_delta": float(challenger["cagr"] - baseline["cagr"]),
        "max_drawdown_delta": float(
            challenger["max_drawdown"] - baseline["max_drawdown"]
        ),
        "sharpe_delta": float(challenger["sharpe"] - baseline["sharpe"]),
        "calmar_delta": float(challenger["calmar"] - baseline["calmar"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vix_v2.yaml"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_vix_v2"),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    config = config_from_contract(contract)
    end_date = args.end_date or contract["data"].get("end_date")
    symbols = [*contract["boundaries"]["tradable_symbols"], VIX_SYMBOL]
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=contract["data"]["start_date"],
        end=end_date,
    )
    metrics, results, prepared = run_vix_runtime_comparison(bars, config)
    regime = vix_regime_asset_metrics(prepared)
    event = vix_repair_event_study(
        prepared,
        horizons=contract["validation"]["event_horizons"],
        cluster_gap_sessions=contract["validation"]["vix_event_cluster_gap_sessions"],
    )
    audit = vix_signal_audit(prepared, config)
    reachability = {
        key: state_reachability(results[key])
        for key in ("rotation_price_repair_v2", "rotation_vix_v2")
    }
    split_frames: list[pd.DataFrame] = []
    for key in ("rotation_price_repair_v2", "rotation_vix_v2"):
        split = chronological_split_metrics(
            results[key],
            train_fraction=contract["validation"]["chronological_train_fraction"],
        ).reset_index()
        split.insert(0, "strategy", key)
        split_frames.append(split)
    chronological = pd.concat(split_frames, ignore_index=True)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "strategy_metrics.csv")
    regime.to_csv(output / "vix_regime_asset_metrics.csv")
    event.to_csv(output / "vix_repair_events.csv", index=False)
    chronological.to_csv(output / "chronological_split.csv", index=False)
    prepared.to_csv(output / "prepared_signal_frame.csv")
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
    (output / "vix_signal_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    (output / "state_reachability.json").write_text(
        json.dumps(
            reachability,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    comparison_keys = [
        "buy_hold_QQQ",
        "rotation_price_v1",
        "rotation_price_repair_v2",
        "rotation_vix_v2",
    ]
    comparison = metrics.loc[comparison_keys]
    v2 = results["rotation_vix_v2"].metrics
    qqq = results["buy_hold_QQQ"].metrics
    price_v1 = results["rotation_price_v1"].metrics
    price_repair = results["rotation_price_repair_v2"].metrics
    summary = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "common_price_sample_start": prepared.index.min().date().isoformat(),
        "common_price_sample_end": prepared.index.max().date().isoformat(),
        "economic_return_start": v2["start_date"],
        "economic_return_end": v2["end_date"],
        "comparison": comparison.reset_index().to_dict(orient="records"),
        "vix_signal_audit": audit,
        "state_reachability": reachability,
        "relative_to_qqq": _metric_delta(v2, qqq),
        "relative_to_price_v1": _metric_delta(v2, price_v1),
        "vix_incremental_vs_matched_price_repair": _metric_delta(v2, price_repair),
        "limitations": [
            "VIX measures 30-day expected S&P 500 volatility, not QQQ direction.",
            "Spot VIX is used only as a signal and is never treated as a tradable asset.",
            "QQQI inception limits the true common three-asset sample to 2024 onward.",
            "This contract is frozen before observing v2 performance and must not be tuned in-place.",
            "VIX attribution must use the matched price-repair ablation, not the old price-only v1.",
            "A reached leveraged state is necessary but not sufficient for trade readiness.",
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
    (output / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
