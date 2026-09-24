#!/usr/bin/env python3
"""Run momentum-scaled expansion (minimal change)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from src.research.byd_515180_allocation import PRIMARY_COST_BPS, STRESS_COST_BPS, prepare_common_dataset
from src.research.byd_mom_scaled import (
    BASELINE, PRIMARY, ROBUSTNESS, PRIMARY_FINANCING_RATE, STRESS_FINANCING_RATE, RULES,
    build_evaluation, governed_result, period_contribution, run_candidates,
)

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--byd-dir", type=Path, required=True)
    p.add_argument("--etf-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("D:/tmp/byd_mom_scaled"))
    return p.parse_args()

def main():
    args = parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out/"daily").mkdir(exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    r20, s20 = run_candidates(common, signals, cost_bps=PRIMARY_COST_BPS, annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, _ = run_candidates(common, signals, cost_bps=STRESS_COST_BPS, annual_financing_rate=STRESS_FINANCING_RATE)
    evaluation = build_evaluation(r20, r40)
    pc = period_contribution(r20)
    gov = governed_result(evaluation, pc)
    full = evaluation.loc[(evaluation["window"]=="full_overlap")&(evaluation["scenario"]=="primary")].set_index("model")
    for n in (BASELINE, PRIMARY, ROBUSTNESS):
        r20[n].daily.to_csv(out/"daily"/f"{n}_20bps.csv", index=True, float_format="%.12f", lineterminator="\n")
        r40[n].daily.to_csv(out/"daily"/f"{n}_40bps.csv", index=True, float_format="%.12f", lineterminator="\n")
    evaluation.to_csv(out/"evaluation.csv", index=True, float_format="%.12f", lineterminator="\n")
    summary = {
        "decision": gov.decision, "gates": gov.gates, "diagnostics": gov.diagnostics,
        "entry_sessions": int(s20["entry"].sum()), "active_sessions": int(s20["expansion_active"].sum()),
        "headline": {n: {k: float(full.loc[n,k]) for k in ["cagr","total_return","max_drawdown","calmar","round_trips_per_year"]} for n in full.index},
        "rules": RULES,
    }
    (out/"summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str)+"\n")
    print(f"Decision: {gov.decision}")
    print(f"Entry sessions: {s20['entry'].sum()}, Active: {s20['expansion_active'].sum()}")
    print(full.to_string(float_format=".4f"))
    print(f"\nGates: {json.dumps(gov.gates, indent=2)}")

if __name__ == "__main__":
    main()
