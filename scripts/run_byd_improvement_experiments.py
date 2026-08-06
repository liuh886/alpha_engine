#!/usr/bin/env python3
"""Run comprehensive BYD model improvement experiments.

Tests three novel approaches + one targeted fix:
1. Adaptive multi-tier expansion (relaxed entry, tiered by momentum strength)
2. Volatility-targeted position sizing (continuous, risk-managed)
3. Multi-signal blend (V1 base + drawdown anti-cyclical + cross-asset RS)
4. Trend expansion fix (relaxed entry, no vol filter)

Compares all against the current BYD v1.1 baseline.
"""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS, STRESS_COST_BPS,
    prepare_common_dataset,
)
from src.research.byd_adaptive_expansion import (
    PRIMARY_FINANCING_RATE, STRESS_FINANCING_RATE,
)
from src.research.byd_adaptive_expansion import governed_result as ae_gov
from src.research.byd_adaptive_expansion import build_evaluation as ae_eval
from src.research.byd_adaptive_expansion import period_contribution as ae_pc
from src.research.byd_adaptive_expansion import run_candidates as ae_run
from src.research.byd_adaptive_expansion import episode_attribution as ae_episodes

from src.research.byd_vol_target import governed_result as vt_gov
from src.research.byd_vol_target import build_evaluation as vt_eval
from src.research.byd_vol_target import period_contribution as vt_pc
from src.research.byd_vol_target import run_candidates as vt_run

from src.research.byd_multi_signal_blend import governed_result as bl_gov
from src.research.byd_multi_signal_blend import build_evaluation as bl_eval
from src.research.byd_multi_signal_blend import period_contribution as bl_pc
from src.research.byd_multi_signal_blend import run_candidates as bl_run

from src.research.byd_trend_fix_v1 import governed_result as tf_gov
from src.research.byd_trend_fix_v1 import build_evaluation as tf_eval
from src.research.byd_trend_fix_v1 import period_contribution as tf_pc
from src.research.byd_trend_fix_v1 import run_candidates as tf_run

BASELINE = "byd_v1_1"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--byd-dir", type=Path, required=True)
    p.add_argument("--etf-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("D:/tmp/byd_experiments"))
    return p.parse_args()


def run_expansion(name, common, signals, output):
    """Run financed expansion experiment (adaptive + trend_fix)."""
    r20, s20 = ae_run(common, signals, cost_bps=PRIMARY_COST_BPS, annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, _ = ae_run(common, signals, cost_bps=STRESS_COST_BPS, annual_financing_rate=STRESS_FINANCING_RATE)
    evaluation = ae_eval(r20, r40)
    pc = ae_pc(r20)
    primary_key = [k for k in r20 if k != BASELINE][0]
    episodes = ae_episodes(r20[primary_key], r20[BASELINE], s20)
    governed = ae_gov(evaluation, pc, episodes)
    return _save(name, output, evaluation, pc, governed, r20, r40, s20)


def run_trend_fix(name, common, signals, output):
    """Run trend fix experiment."""
    r20, s20 = tf_run(common, signals, cost_bps=PRIMARY_COST_BPS, annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, _ = tf_run(common, signals, cost_bps=STRESS_COST_BPS, annual_financing_rate=STRESS_FINANCING_RATE)
    evaluation = tf_eval(r20, r40)
    pc = tf_pc(r20)
    governed = tf_gov(evaluation, pc)
    return _save(name, output, evaluation, pc, governed, r20, r40, s20)


def run_simple(name, common, signals, output, run_fn, eval_fn, pc_fn, gov_fn):
    """Run simple (non-financed) experiment."""
    r20, _ = run_fn(common, signals, cost_bps=PRIMARY_COST_BPS)
    r40, _ = run_fn(common, signals, cost_bps=STRESS_COST_BPS)
    evaluation = eval_fn(r20, r40)
    pc = pc_fn(r20)
    governed = gov_fn(evaluation, pc)
    return _save(name, output, evaluation, pc, governed, r20, r40)


def _save(name, output, evaluation, pc, governed, r20, r40, extra=None):
    sub = output / name; sub.mkdir(parents=True, exist_ok=True)
    (sub / "daily").mkdir(parents=True, exist_ok=True)
    evaluation.to_csv(sub / "evaluation.csv", index=True, float_format="%.12f", lineterminator="\n")
    pc.to_csv(sub / "period_contribution.csv", index=True, float_format="%.12f", lineterminator="\n")
    for n, r in r20.items():
        r.daily.to_csv(sub / "daily" / f"{n}_20bps.csv", index=True, float_format="%.12f", lineterminator="\n")
        r40[n].daily.to_csv(sub / "daily" / f"{n}_40bps.csv", index=True, float_format="%.12f", lineterminator="\n")
    if extra is not None:
        extra.to_csv(sub / "state_ledger.csv", index=True, lineterminator="\n")

    full = evaluation.loc[(evaluation["window"] == "full_overlap")].copy()
    if "scenario" in full.columns:
        full = full.loc[full["scenario"] == "primary"]
    if "cost_bps" in full.columns:
        full = full.loc[full["cost_bps"] == PRIMARY_COST_BPS]
    full = full.set_index("model")

    summary = {
        "experiment": name,
        "decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline": {
            n: {k: float(full.loc[n, k]) for k in ["cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"] if k in full.columns}
            for n in full.index
        },
    }
    (sub / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    return summary, full


def main():
    args = parse_args()
    output = args.output_dir
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    print(f"Data: {len(common)} sessions, {common.index.min().date()} to {common.index.max().date()}")

    all_hl = {}

    # Experiment 1: Adaptive multi-tier expansion
    s, f = run_expansion("adaptive_expansion", common, signals, output)
    for n in f.index:
        all_hl[f"ae_{n}"] = {k: float(f.loc[n, k]) for k in ["cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"]}

    # Experiment 2: Volatility-targeted
    s, f = run_simple("vol_target", common, signals, output, vt_run, vt_eval, vt_pc, vt_gov)
    for n in f.index:
        all_hl[f"vt_{n}"] = {k: float(f.loc[n, k]) for k in ["cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"]}

    # Experiment 3: Multi-signal blend
    s, f = run_simple("multi_signal_blend", common, signals, output, bl_run, bl_eval, bl_pc, bl_gov)
    for n in f.index:
        all_hl[f"bl_{n}"] = {k: float(f.loc[n, k]) for k in ["cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"]}

    # Experiment 4: Trend fix
    s, f = run_trend_fix("trend_fix", common, signals, output)
    for n in f.index:
        all_hl[f"tf_{n}"] = {k: float(f.loc[n, k]) for k in ["cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"]}

    # Master comparison
    comp = pd.DataFrame(all_hl).T
    comp.to_csv(output / "master_comparison.csv", index=True, float_format="%.12f", lineterminator="\n")

    print("\n" + "=" * 80)
    print("MASTER COMPARISON — Full Overlap, 20 bps primary cost")
    print("=" * 80)
    print(comp.to_string(float_format=".4f"))

    baseline_row = [r for r in comp.index if BASELINE in r]
    if baseline_row:
        bl_cagr = comp.loc[baseline_row[0], "cagr"]
        challengers = comp.loc[~comp.index.isin(baseline_row)]
        if len(challengers) > 0:
            best_idx = challengers["cagr"].idxmax()
            print(f"\nBaseline CAGR: {bl_cagr:.4f}")
            print(f"Best: {best_idx} CAGR: {challengers.loc[best_idx, 'cagr']:.4f} "
                  f"(delta: {challengers.loc[best_idx, 'cagr'] - bl_cagr:+.4f})")


if __name__ == "__main__":
    main()
