#!/usr/bin/env python3
"""Run state-cycle attribution and tail-risk diagnostics for v4.2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_baseline_diagnostics import (
    compare_tail_risk,
    state_one_lifecycle_attribution,
    tail_risk_metrics,
)
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

V4_1 = "rotation_vxn_leverage_v4_1_75"
V4_2 = "rotation_vxn_bridge_v4_2_50_50"


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_v4_2_baseline_diagnostics"),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    boundaries = contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=contract["data"]["start_date"],
        end=args.end_date or contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    metrics, results, _, diagnostics = run_bridge_allocation_comparison(bars, contract)
    episodes, lifecycle_summary = state_one_lifecycle_attribution(
        results[V4_1], results[V4_2]
    )
    tail_table = compare_tail_risk(
        {"v4_1_historical": results[V4_1], "v4_2_current_baseline": results[V4_2]}
    )
    state_tail = {
        "v4_1_historical": tail_risk_metrics(results[V4_1])["state_tail"],
        "v4_2_current_baseline": tail_risk_metrics(results[V4_2])["state_tail"],
    }

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "headline_metrics.csv")
    episodes.to_csv(output / "state_1_lifecycle_episodes.csv", index=False)
    lifecycle_summary.to_csv(output / "state_1_lifecycle_summary.csv", index=False)
    tail_table.to_csv(output / "tail_risk_comparison.csv")
    summary = {
        "schema_version": "1.0",
        "experiment_id": "qqqi_qqq_tqqq_v4_2_baseline_diagnostics",
        "baseline": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "historical_comparator": "qqqi_qqq_tqqq_vxn_leverage_v4_1",
        "research_only": True,
        "trade_ready": False,
        "cost_bps_per_turnover_unit": float(
            contract["portfolio"]["transaction_cost_bps_per_turnover_unit"]
        ),
        "data_identity": identity,
        "state_1_episode_count": int(len(episodes)),
        "state_1_lifecycle_summary": lifecycle_summary.to_dict(orient="records"),
        "tail_risk": tail_table.reset_index().to_dict(orient="records"),
        "state_tail": state_tail,
        "inherited_bridge_diagnostics": diagnostics,
    }
    (output / "diagnostic_summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
