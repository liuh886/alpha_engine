#!/usr/bin/env python3
"""Run the frozen BYD v1.2 extreme-defense experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    prepare_common_dataset,
)
from src.research.byd_v1_2_extreme_defense import (
    BASELINE,
    CASH_DIAGNOSTIC,
    PRIMARY,
    ROBUSTNESS,
    RULES,
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
    results_20, reproduced_state = run_candidates(
        common, signals, cost_bps=PRIMARY_COST_BPS
    )
    results_40, _ = run_candidates(common, signals, cost_bps=STRESS_COST_BPS)
    if not state.equals(reproduced_state):
        raise RuntimeError("extreme-defense state is not deterministic")

    evaluation = build_evaluation(results_20, results_40)
    contributions = period_contribution(results_20)
    episodes = episode_attribution(
        results_20[PRIMARY], results_20[BASELINE], state
    )
    governed = governed_result(evaluation, contributions)

    write_csv(output / "evaluation.csv", evaluation)
    write_csv(output / "period_contribution.csv", contributions)
    write_csv(output / "episode_attribution.csv", episodes)
    write_csv(output / "state_ledger.csv", state)
    for name, decision in decisions.items():
        write_csv(output / "decisions" / f"{name}.csv", decision)
        write_csv(output / "daily" / f"{name}_20bps.csv", results_20[name].daily)
        write_csv(output / "daily" / f"{name}_40bps.csv", results_40[name].daily)
        write_csv(
            output / "trades" / f"{name}_20bps.csv",
            results_20[name].trades.set_index("date"),
        )

    active_sessions = int(state["extreme_defense_active"].sum())
    entry_count = int(state["entry"].sum())
    full20 = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["cost_bps"] == PRIMARY_COST_BPS)
    ].set_index("model")
    summary = {
        "schema_version": "byd_v1_2_extreme_defense_evidence_v1",
        "issue": 560,
        "baseline": BASELINE,
        "primary_candidate": PRIMARY,
        "robustness_candidate": ROBUSTNESS,
        "cash_diagnostic": CASH_DIAGNOSTIC,
        "rules": RULES,
        "overlap_first_date": common.index.min().strftime("%Y-%m-%d"),
        "overlap_last_date": common.index.max().strftime("%Y-%m-%d"),
        "overlap_sessions": int(len(common)),
        "common_eligible_opens": int(common["common_open_eligible"].sum()),
        "extreme_entry_signals": entry_count,
        "extreme_active_sessions": active_sessions,
        "completed_extreme_episodes": int(len(episodes)),
        "governed_decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline_20bps": {
            name: {
                "cagr": float(full20.loc[name, "cagr"]),
                "total_return": float(full20.loc[name, "total_return"]),
                "max_drawdown": float(full20.loc[name, "max_drawdown"]),
                "calmar": float(full20.loc[name, "calmar"]),
                "round_trips_per_year": float(
                    full20.loc[name, "round_trips_per_year"]
                ),
            }
            for name in (BASELINE, PRIMARY, ROBUSTNESS, CASH_DIAGNOSTIC)
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
        "# BYD v1.2 extreme-defense research",
        "",
        f"- Governed decision: `{governed.decision}`",
        f"- Overlap: `{summary['overlap_first_date']}` to `{summary['overlap_last_date']}`",
        f"- Extreme entry signals: `{entry_count}`",
        f"- Extreme active sessions: `{active_sessions}`",
        f"- Completed extreme episodes: `{len(episodes)}`",
        "- Costs: 20 bps primary, 40 bps stress",
        "- Historical freshness: `false`",
        "",
        "## Full-overlap 20 bps",
        "",
        full20[
            [
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "round_trips_per_year",
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
