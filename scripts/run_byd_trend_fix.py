#!/usr/bin/env python3
"""Run targeted trend expansion fix: relaxed entry conditions, no vol filter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS, STRESS_COST_BPS,
    prepare_common_dataset,
)
from src.research.byd_trend_fix_v1 import (
    BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC,
    PRIMARY_FINANCING_RATE, STRESS_FINANCING_RATE,
    RULES,
    build_evaluation, governed_result, period_contribution,
    run_candidates,
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--byd-dir", type=Path, required=True)
    p.add_argument("--etf-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("/tmp/byd_trend_fix"))
    return p.parse_args()


def write_csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=True, float_format="%.12f", lineterminator="\n")


def main():
    args = parse_args()
    out = args.output_dir; out.mkdir(parents=True, exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    print(f"Overlap: {len(common)} sessions, {common.index.min().date()} to {common.index.max().date()}")

    r20, s20 = run_candidates(common, signals, cost_bps=PRIMARY_COST_BPS, annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, _ = run_candidates(common, signals, cost_bps=STRESS_COST_BPS, annual_financing_rate=STRESS_FINANCING_RATE)

    evaluation = build_evaluation(r20, r40)
    pc = period_contribution(r20)
    governed = governed_result(evaluation, pc)

    full = evaluation.loc[(evaluation["window"]=="full_overlap") & (evaluation["scenario"]=="primary")].set_index("model")
    entry_sessions = int(s20["entry"].sum())

    write_csv(out / "evaluation.csv", evaluation)
    write_csv(out / "period_contribution.csv", pc)
    write_csv(out / "state.csv", s20)
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        write_csv(out / "daily" / f"{n}_primary.csv", r20[n].daily)
        write_csv(out / "daily" / f"{n}_stress.csv", r40[n].daily)

    summary = {
        "experiment": "trend_expansion_fix",
        "rules": RULES,
        "entry_signals": entry_sessions,
        "expansion_active_sessions": int(s20["expansion_active"].sum()),
        "decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline": {n: {
            "cagr": float(full.loc[n,"cagr"]), "total_return": float(full.loc[n,"total_return"]),
            "max_drawdown": float(full.loc[n,"max_drawdown"]), "calmar": float(full.loc[n,"calmar"]),
            "round_trips_per_year": float(full.loc[n,"round_trips_per_year"]),
            "financed_sessions": float(full.loc[n,"financed_sessions"]),
        } for n in full.index},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str)+"\n")

    print(f"\nDecision: {governed.decision}")
    print(f"Expansion sessions: {s20['expansion_active'].sum()}")
    print(f"Entry signals: {entry_sessions}")
    print(full.to_markdown(floatfmt=".4f"))
    print(f"\nGates: {json.dumps(governed.gates, indent=2)}")

    return summary


if __name__ == "__main__":
    main()
