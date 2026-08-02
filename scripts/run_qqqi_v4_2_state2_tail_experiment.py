#!/usr/bin/env python3
"""Run the frozen v4.2 state-2 tail and execution-robustness experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_state2_tail_experiment import (
    execution_robustness_comparison,
    state_two_episode_attribution,
    state_two_research_gate,
)
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

V4_2 = "rotation_vxn_bridge_v4_2_50_50"


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic-contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_state2_tail_diagnostics.yaml"
        ),
    )
    parser.add_argument(
        "--baseline-contract",
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
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_state2_tail_diagnostics"
        ),
    )
    args = parser.parse_args()

    diagnostic_contract = yaml.safe_load(
        args.diagnostic_contract.read_text(encoding="utf-8")
    )
    baseline_contract = yaml.safe_load(
        args.baseline_contract.read_text(encoding="utf-8")
    )
    boundaries = baseline_contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=diagnostic_contract["data"]["start_date"],
        end=args.end_date or diagnostic_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    metrics, results, _, inherited = run_bridge_allocation_comparison(
        bars, baseline_contract
    )
    baseline = results[V4_2]

    episode_contract = diagnostic_contract["episode_analysis"]
    abrupt = episode_contract["abrupt_episode_if"]
    episodes, episode_summary, tail_days = state_two_episode_attribution(
        baseline,
        top_n=int(episode_contract["top_tail_days"]),
        abrupt_overnight_share=float(
            abrupt["overnight_loss_share_gte"]
        ),
        abrupt_worst_day_share=float(
            abrupt["worst_day_share_of_mae_gte"]
        ),
    )
    execution_table, execution_results = execution_robustness_comparison(
        baseline, baseline_contract
    )
    gate = state_two_research_gate(
        episode_summary,
        tail_days,
        execution_table,
        diagnostic_contract,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "baseline_headline_metrics.csv")
    episodes.to_csv(output / "state_2_episodes.csv", index=False)
    episode_summary.to_csv(output / "state_2_episode_summary.csv", index=False)
    tail_days.to_csv(output / "state_2_top_tail_days.csv", index=False)
    execution_table.to_csv(output / "execution_robustness.csv")

    scenario_state_counts = {
        key: {
            str(state): int(
                result.daily["position_state"].eq(state).sum()
            )
            for state in (0, 1, 2)
        }
        for key, result in execution_results.items()
    }
    summary = {
        "schema_version": "1.0",
        "experiment_id": diagnostic_contract["experiment_id"],
        "parent_experiment_id": diagnostic_contract[
            "parent_experiment_id"
        ],
        "research_only": True,
        "trade_ready": False,
        "baseline_unchanged": True,
        "official_cost_bps_per_turnover_unit": float(
            baseline_contract["portfolio"][
                "transaction_cost_bps_per_turnover_unit"
            ]
        ),
        "data_identity": identity,
        "economic_sample": {
            "start_date": baseline.daily.index.min().date().isoformat(),
            "end_date": baseline.daily.index.max().date().isoformat(),
            "observations": int(len(baseline.daily)),
        },
        "state_2": {
            "episode_count": int(len(episodes)),
            "session_count": int(
                baseline.daily["position_state"].eq(2).sum()
            ),
            "episode_summary": (
                episode_summary.iloc[0].to_dict()
                if not episode_summary.empty
                else {}
            ),
            "top_tail_days": tail_days.to_dict(orient="records"),
        },
        "execution_robustness": execution_table.reset_index().to_dict(
            orient="records"
        ),
        "scenario_state_counts": scenario_state_counts,
        "research_gate": gate,
        "inherited_bridge_diagnostics": inherited,
    }
    (output / "state_2_tail_summary.json").write_text(
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
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
