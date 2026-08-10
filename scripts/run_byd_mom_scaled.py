#!/usr/bin/env python3
"""Run momentum-scaled expansion (minimal change)."""

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
from src.research.byd_mom_scaled import (
    BASELINE,
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
        "--output-dir", type=Path, default=Path("D:/tmp/byd_mom_scaled")
    )
    return parser.parse_args()


def main():
    args = parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "daily").mkdir(exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
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
    for name in (BASELINE, PRIMARY, ROBUSTNESS):
        r20[name].daily.to_csv(
            out / "daily" / f"{name}_20bps.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )
        r40[name].daily.to_csv(
            out / "daily" / f"{name}_40bps.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )
    evaluation.to_csv(
        out / "evaluation.csv",
        index=True,
        float_format="%.12f",
        lineterminator="\n",
    )
    headline_metrics = [
        "cagr",
        "total_return",
        "max_drawdown",
        "calmar",
        "round_trips_per_year",
    ]
    summary = {
        "decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "entry_sessions": int(s20["entry"].sum()),
        "active_sessions": int(s20["expansion_active"].sum()),
        "headline": {
            name: {
                metric: float(full.loc[name, metric])
                for metric in headline_metrics
            }
            for name in full.index
        },
        "rules": RULES,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(f"Decision: {governed.decision}")
    print(
        f"Entry sessions: {s20['entry'].sum()}, "
        f"Active: {s20['expansion_active'].sum()}"
    )
    print(full.to_string(float_format=".4f"))
    print(f"\nGates: {json.dumps(governed.gates, indent=2)}")


if __name__ == "__main__":
    main()
