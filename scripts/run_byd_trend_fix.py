#!/usr/bin/env python3
"""Run targeted trend expansion fix: relaxed entry conditions, no vol filter."""

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
from src.research.byd_trend_fix_v1 import (
    BASELINE,
    DIAGNOSTIC,
    PRIMARY,
    PRIMARY_FINANCING_RATE,
    ROBUSTNESS,
    RULES,
    STRESS_FINANCING_RATE,
    build_evaluation,
    governed_result,
    period_contribution,
    run_candidates,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("/tmp/byd_trend_fix")
    )
    return parser.parse_args()


def write_csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=True, float_format="%.12f", lineterminator="\n")


def main():
    args = parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    print(
        f"Overlap: {len(common)} sessions, {common.index.min().date()} "
        f"to {common.index.max().date()}"
    )

    r20, s20 = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    r40, _ = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )

    evaluation = build_evaluation(r20, r40)
    contributions = period_contribution(r20)
    governed = governed_result(evaluation, contributions)

    full = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["scenario"] == "primary")
    ].set_index("model")
    entry_sessions = int(s20["entry"].sum())

    write_csv(out / "evaluation.csv", evaluation)
    write_csv(out / "period_contribution.csv", contributions)
    write_csv(out / "state.csv", s20)
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        write_csv(out / "daily" / f"{name}_primary.csv", r20[name].daily)
        write_csv(out / "daily" / f"{name}_stress.csv", r40[name].daily)

    headline = {}
    for name in full.index:
        headline[name] = {
            "cagr": float(full.loc[name, "cagr"]),
            "total_return": float(full.loc[name, "total_return"]),
            "max_drawdown": float(full.loc[name, "max_drawdown"]),
            "calmar": float(full.loc[name, "calmar"]),
            "round_trips_per_year": float(
                full.loc[name, "round_trips_per_year"]
            ),
            "financed_sessions": float(full.loc[name, "financed_sessions"]),
        }
    summary = {
        "experiment": "trend_expansion_fix",
        "rules": RULES,
        "entry_signals": entry_sessions,
        "expansion_active_sessions": int(s20["expansion_active"].sum()),
        "decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline": headline,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
    )

    print(f"\nDecision: {governed.decision}")
    print(f"Expansion sessions: {s20['expansion_active'].sum()}")
    print(f"Entry signals: {entry_sessions}")
    print(full.to_markdown(floatfmt=".4f"))
    print(f"\nGates: {json.dumps(governed.gates, indent=2)}")

    return summary


if __name__ == "__main__":
    main()
