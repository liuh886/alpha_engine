#!/usr/bin/env python3
"""Run the post-diagnostic v4.2 risk-confirmation ablation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_risk_confirmation_experiment import (
    confirmation_research_gate,
    run_confirmation_comparison,
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
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_risk_confirmation_v4_3_research.yaml"
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
            "qqqi_qqq_tqqq_v4_2_risk_confirmation_v4_3_research"
        ),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
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
        start=baseline_contract["data"]["start_date"],
        end=args.end_date or baseline_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    _, results, _, inherited = run_bridge_allocation_comparison(
        bars, baseline_contract
    )
    baseline = results[V4_2]
    metrics, segments, events, scenarios = run_confirmation_comparison(
        baseline,
        baseline_contract,
        train_fraction=float(
            contract["validation"]["chronological_train_fraction"]
        ),
    )
    gate = confirmation_research_gate(
        metrics,
        segments,
        events,
        contract,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    metrics.to_csv(output / "confirmation_metrics.csv")
    segments.to_csv(output / "confirmation_chronological_segments.csv", index=False)
    events.to_csv(output / "confirmation_difference_events.csv", index=False)

    event_summary_rows: list[dict[str, Any]] = []
    for scenario, group in events.groupby("scenario"):
        positive = group["net_return_delta"].clip(lower=0.0)
        positive_sum = float(positive.sum())
        event_summary_rows.append(
            {
                "scenario": scenario,
                "events": int(len(group)),
                "positive_event_rate": float(
                    group["net_return_delta"].gt(0.0).mean()
                ),
                "mean_net_return_delta": float(
                    group["net_return_delta"].mean()
                ),
                "total_arithmetic_net_return_delta": float(
                    group["net_return_delta"].sum()
                ),
                "top_positive_event_share": (
                    float(positive.max() / positive_sum)
                    if positive_sum > 1e-12
                    else 0.0
                ),
                "total_turnover_saved": float(
                    group["turnover_saved"].sum()
                ),
            }
        )
    event_summary = pd.DataFrame(event_summary_rows)
    event_summary.to_csv(output / "confirmation_event_summary.csv", index=False)

    summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "post_result_hypothesis": True,
        "baseline_unchanged": True,
        "data_identity": identity,
        "economic_sample": {
            "start_date": baseline.daily.index.min().date().isoformat(),
            "end_date": baseline.daily.index.max().date().isoformat(),
            "observations": int(len(baseline.daily)),
        },
        "metrics": metrics.reset_index().to_dict(orient="records"),
        "chronological_segments": segments.to_dict(orient="records"),
        "event_summary": event_summary.to_dict(orient="records"),
        "research_gate": gate,
        "scenario_state_counts": {
            key: {
                str(state): int(
                    result.daily["position_state"].eq(state).sum()
                )
                for state in (0, 1, 2)
            }
            for key, result in scenarios.items()
        },
        "inherited_bridge_diagnostics": inherited,
    }
    (output / "confirmation_summary.json").write_text(
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
