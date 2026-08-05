#!/usr/bin/env python3
"""Run the frozen BYD v1.2 capped trend-expansion experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import prepare_common_dataset
from src.research.byd_v1_2_trend_expansion import (
    BASELINE,
    CANDIDATES,
    DIAGNOSTIC,
    PRIMARY,
    PRIMARY_COST_BPS,
    PRIMARY_FINANCING_RATE,
    ROBUSTNESS,
    RULES,
    STRESS_COST_BPS,
    STRESS_FINANCING_RATE,
    build_decisions,
    build_evaluation,
    episode_attribution,
    governed_result,
    period_contribution,
    run_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=True, float_format="%.12f", lineterminator="\n")


def main() -> None:
    args = parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    decisions, state = build_decisions(common, signals)
    results_primary, reproduced_state = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    results_stress, _ = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    if not state.equals(reproduced_state):
        raise RuntimeError("trend-expansion state is not deterministic")

    evaluation = build_evaluation(results_primary, results_stress)
    contributions = period_contribution(results_primary)
    episodes = episode_attribution(
        results_primary[PRIMARY], results_primary[BASELINE], state
    )
    governed = governed_result(evaluation, contributions, episodes)

    write_csv(output / "evaluation.csv", evaluation)
    write_csv(output / "period_contribution.csv", contributions)
    write_csv(output / "episode_attribution.csv", episodes)
    write_csv(output / "state_ledger.csv", state)
    for name, decision in decisions.items():
        write_csv(output / "decisions" / f"{name}.csv", decision)
        write_csv(
            output / "daily" / f"{name}_primary.csv",
            results_primary[name].daily,
        )
        write_csv(
            output / "daily" / f"{name}_stress.csv",
            results_stress[name].daily,
        )
        write_csv(
            output / "trades" / f"{name}_primary.csv",
            results_primary[name].trades.set_index("date"),
        )

    full = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["scenario"] == "primary")
    ].set_index("model")
    full_stress = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["scenario"] == "stress")
    ].set_index("model")
    summary = {
        "schema_version": "byd_v1_2_trend_expansion_evidence_v1",
        "issue": 560,
        "baseline": BASELINE,
        "primary_candidate": PRIMARY,
        "robustness_candidate": ROBUSTNESS,
        "diagnostic_candidate": DIAGNOSTIC,
        "rules": RULES,
        "cost_contract": {
            "primary_transaction_cost_bps": PRIMARY_COST_BPS,
            "stress_transaction_cost_bps": STRESS_COST_BPS,
            "primary_annual_financing_rate": PRIMARY_FINANCING_RATE,
            "stress_annual_financing_rate": STRESS_FINANCING_RATE,
        },
        "overlap_first_date": common.index.min().strftime("%Y-%m-%d"),
        "overlap_last_date": common.index.max().strftime("%Y-%m-%d"),
        "overlap_sessions": int(len(common)),
        "common_eligible_opens": int(common["common_open_eligible"].sum()),
        "expansion_entry_signals": int(state["entry"].sum()),
        "expansion_active_sessions": int(
            state["trend_expansion_active"].sum()
        ),
        "completed_expansion_episodes": int(len(episodes)),
        "governed_decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline_primary": {
            name: {
                "cagr": float(full.loc[name, "cagr"]),
                "total_return": float(full.loc[name, "total_return"]),
                "max_drawdown": float(full.loc[name, "max_drawdown"]),
                "calmar": float(full.loc[name, "calmar"]),
                "round_trips_per_year": float(
                    full.loc[name, "round_trips_per_year"]
                ),
                "financing_cost_paid": float(
                    full.loc[name, "financing_cost_paid"]
                ),
            }
            for name in CANDIDATES
        },
        "headline_stress_total_return": {
            name: float(full_stress.loc[name, "total_return"])
            for name in CANDIDATES
        },
        "fresh_historical_holdout": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = [
        "# BYD v1.2 capped trend-expansion research",
        "",
        f"- Governed decision: `{governed.decision}`",
        f"- Overlap: `{summary['overlap_first_date']}` to `{summary['overlap_last_date']}`",
        f"- Expansion entry signals: `{summary['expansion_entry_signals']}`",
        f"- Expansion active sessions: `{summary['expansion_active_sessions']}`",
        f"- Completed expansion episodes: `{len(episodes)}`",
        "- Primary costs: 20 bps transitions + 6% annual financing",
        "- Stress costs: 40 bps transitions + 10% annual financing",
        "- Historical freshness: `false`",
        "",
        "## Full-overlap primary scenario",
        "",
        full[
            [
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "round_trips_per_year",
                "financing_cost_paid",
            ]
        ].to_markdown(),
        "",
        "## Frozen gates",
        "",
        "```json",
        json.dumps(governed.gates, indent=2, sort_keys=True),
        "```",
        "",
        "## Diagnostics",
        "",
        "```json",
        json.dumps(governed.diagnostics, indent=2, sort_keys=True),
        "```",
    ]
    (output / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
