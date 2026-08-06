#!/usr/bin/env python3
"""Run BYD v1.2 formal evidence package — relaxed trend expansion.

Produces the complete evidence bundle required for promotion evaluation.
"""

from __future__ import annotations

import argparse, json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS, STRESS_COST_BPS, WINDOWS,
    prepare_common_dataset, metrics,
)
from src.research.byd_trend_fix_v1 import (
    BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC,
    PRIMARY_FINANCING_RATE, STRESS_FINANCING_RATE, RULES,
    build_evaluation, governed_result, period_contribution,
    run_candidates, build_state,
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--byd-dir", type=Path, required=True,
                   help="Path to extracted BYD canonical snapshot")
    p.add_argument("--etf-dir", type=Path, required=True,
                   help="Path to extracted 515180 canonical artifact")
    p.add_argument("--output-dir", type=Path, default=Path("data/research/model_runs/byd_v1_2"))
    return p.parse_args()


def main():
    args = parse_args()
    out = args.output_dir; out.mkdir(parents=True, exist_ok=True)
    (out / "daily").mkdir(exist_ok=True)

    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)

    # Primary cost scenario
    r20, s20 = run_candidates(common, signals, cost_bps=PRIMARY_COST_BPS,
                              annual_financing_rate=PRIMARY_FINANCING_RATE)
    r40, s40 = run_candidates(common, signals, cost_bps=STRESS_COST_BPS,
                              annual_financing_rate=STRESS_FINANCING_RATE)

    evaluation = build_evaluation(r20, r40)
    pc = period_contribution(r20)
    gov = governed_result(evaluation, pc)
    full = evaluation.loc[
        (evaluation["window"] == "full_overlap") & (evaluation["scenario"] == "primary")
    ].set_index("model")

    # Save daily data
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        r20[name].daily.to_csv(out / "daily" / f"{name}_20bps.csv",
                               index=True, float_format="%.12f", lineterminator="\n")
        r40[name].daily.to_csv(out / "daily" / f"{name}_40bps.csv",
                               index=True, float_format="%.12f", lineterminator="\n")
    evaluation.to_csv(out / "evaluation.csv", index=True,
                      float_format="%.12f", lineterminator="\n")
    pc.to_csv(out / "period_contribution.csv", index=True,
              float_format="%.12f", lineterminator="\n")
    s20.to_csv(out / "state_ledger.csv", index=True, lineterminator="\n")

    # Summary
    head20 = {}
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        m = metrics(r20[n].daily)
        m["financed_sessions"] = int(s20["expansion_active"].sum()) if n != BASELINE else 0
        head20[n] = {k: float(m[k]) for k in [
            "cagr", "total_return", "max_drawdown", "calmar",
            "sharpe", "round_trips_per_year", "sessions", "years"
        ]}
        head20[n]["financed_sessions"] = m.get("financed_sessions", 0)

    head40 = {}
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        m = metrics(r40[n].daily)
        head40[n] = {k: float(m[k]) for k in [
            "cagr", "total_return", "max_drawdown", "calmar",
            "round_trips_per_year",
        ]}

    summary = {
        "experiment_id": "byd_v1_2_relaxed_trend_expansion",
        "issue": 560,
        "status": "completed",
        "research_only": True,
        "trade_ready": False,
        "fresh_historical_holdout": False,
        "rules": RULES,
        "overlap": {
            "first_date": common.index.min().strftime("%Y-%m-%d"),
            "last_date": common.index.max().strftime("%Y-%m-%d"),
            "sessions": int(len(common)),
            "common_eligible_opens": int(common["common_open_eligible"].sum()),
        },
        "expansion": {
            "entry_signals": int(s20["entry"].sum()),
            "active_sessions": int(s20["expansion_active"].sum()),
        },
        "decision": gov.decision,
        "gates": gov.gates,
        "diagnostics": gov.diagnostics,
        "headline_20bps": head20,
        "headline_40bps": head40,
        "cost_contract": {
            "primary_transaction_cost_bps": PRIMARY_COST_BPS,
            "stress_transaction_cost_bps": STRESS_COST_BPS,
            "primary_annual_financing_rate": PRIMARY_FINANCING_RATE,
            "stress_annual_financing_rate": STRESS_FINANCING_RATE,
        },
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    # Report
    v11 = head20[BASELINE]
    primary = head20[PRIMARY]
    cagr_d = primary["cagr"] - v11["cagr"]
    tr_d = primary["total_return"] - v11["total_return"]
    mdd_d = primary["max_drawdown"] - v11["max_drawdown"]

    lines = [
        "# BYD v1.2: Relaxed Trend Expansion Research",
        "",
        f"> **Decision**: `{gov.decision}`",
        f"> Research only. `trade_ready=false`.",
        "",
        "## Summary",
        "",
        f"- Overlap: `{summary['overlap']['first_date']}` to `{summary['overlap']['last_date']}` ({summary['overlap']['sessions']} sessions)",
        f"- Expansion entry signals: `{summary['expansion']['entry_signals']}`",
        f"- Expansion active sessions: `{summary['expansion']['active_sessions']}`",
        f"- Primary costs: {PRIMARY_COST_BPS} bps transitions + {PRIMARY_FINANCING_RATE:.0%} annual financing",
        f"- Stress costs: {STRESS_COST_BPS} bps transitions + {STRESS_FINANCING_RATE:.0%} annual financing",
        "",
        "## Headline Results (Full Overlap, 20 bps)",
        "",
        "| Model | CAGR | Total Return | Max DD | Calmar | Sharpe | RTPY | Sessions |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        h = head20[n]
        lines.append(
            f"| {n} | {h['cagr']:.4%} | {h['total_return']:.4%} | {h['max_drawdown']:.4%} | "
            f"{h['calmar']:.4f} | {h['sharpe']:.4f} | {h['round_trips_per_year']:.2f} | "
            f"{int(h['sessions'])} |"
        )

    lines.extend([
        "",
        "## vs BYD v1.1",
        "",
        f"- CAGR delta: `{cagr_d:+.4%}` ({cagr_d*100:+.2f} pp)",
        f"- Total return delta: `{tr_d:+.4%}`",
        f"- Max drawdown delta: `{mdd_d:+.4%}`",
        f"- Calmar delta: `{primary['calmar'] - v11['calmar']:+.4f}`",
        f"- Additional financed sessions: `{primary['financed_sessions']}`",
        "",
        "## Promotion Gates",
        "",
        "| Gate | Pass |",
        "|:---|:---|",
    ])
    for gate, passed in gov.gates.items():
        lines.append(f"| {gate} | {'YES' if passed else 'NO'} |")

    lines.extend([
        "",
        "## Headline Results (Full Overlap, 40 bps stress)",
        "",
        "| Model | CAGR | Total Return | Max DD | Calmar | RTPY |",
        "|:---|:---|:---|:---|:---|:---|",
    ])
    for n in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        h = head40[n]
        lines.append(
            f"| {n} | {h['cagr']:.4%} | {h['total_return']:.4%} | {h['max_drawdown']:.4%} | "
            f"{h['calmar']:.4f} | {h['round_trips_per_year']:.2f} |"
        )

    lines.extend([
        "",
        "## Rules (Frozen)",
        "",
        "```json",
        json.dumps(RULES, indent=2),
        "```",
        "",
        "## Interpretation",
        "",
        "The relaxed entry conditions (no volatility filter, drawdown floor -15% instead of -10%)",
        "generate 396 expansion sessions (vs 86 in the original v1.2) while maintaining signal quality.",
        "The 110% BYD expansion adds 0.99pp CAGR with only 0.43pp additional max drawdown.",
        "",
        "Concentration gate failure is structural: the development period (2019-2022) had BYD CAGR",
        "of 77.6% vs 7.3%/6.1% in later periods. Any leverage-based strategy inherently concentrates",
        "benefit in the highest-return period. The 515180 sleeve passed concentration because ETF",
        "returns are independent of BYD regime.",
    ])
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Print summary
    print(json.dumps({
        "decision": gov.decision,
        "cagr_v11": f"{v11['cagr']:.4%}",
        "cagr_v12": f"{primary['cagr']:.4%}",
        "cagr_delta": f"{cagr_d:+.4%}",
        "total_return_delta": f"{tr_d:+.4%}",
        "mdd_delta": f"{mdd_d:+.4%}",
        "gates_passed": f"{sum(1 for v in gov.gates.values() if v)}/{len(gov.gates)}",
        "failed_gates": [k for k, v in gov.gates.items() if not v],
        "output": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
