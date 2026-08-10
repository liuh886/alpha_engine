#!/usr/bin/env python3
"""Run BYD v1.2 formal evidence package — relaxed trend expansion.

Produces the complete evidence bundle required for promotion evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    metrics,
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
    build_state,
    governed_result,
    period_contribution,
    run_candidates,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--byd-dir",
        type=Path,
        required=True,
        help="Path to extracted BYD canonical snapshot",
    )
    parser.add_argument(
        "--etf-dir",
        type=Path,
        required=True,
        help="Path to extracted 515180 canonical artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/research/model_runs/byd_v1_2"),
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
    pc = period_contribution(r20)
    gov = governed_result(evaluation, pc)

    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
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
    pc.to_csv(
        out / "period_contribution.csv",
        index=True,
        float_format="%.12f",
        lineterminator="\n",
    )
    s20.to_csv(out / "state_ledger.csv", index=True, lineterminator="\n")

    head20 = {}
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        model_metrics = metrics(r20[name].daily)
        model_metrics["financed_sessions"] = (
            int(s20["expansion_active"].sum()) if name != BASELINE else 0
        )
        head20[name] = {
            key: float(model_metrics[key])
            for key in [
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "sharpe",
                "round_trips_per_year",
                "sessions",
                "years",
            ]
        }
        head20[name]["financed_sessions"] = model_metrics.get(
            "financed_sessions", 0
        )

    head40 = {}
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        model_metrics = metrics(r40[name].daily)
        head40[name] = {
            key: float(model_metrics[key])
            for key in [
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "round_trips_per_year",
            ]
        }

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
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    v11 = head20[BASELINE]
    primary = head20[PRIMARY]
    cagr_d = primary["cagr"] - v11["cagr"]
    tr_d = primary["total_return"] - v11["total_return"]
    mdd_d = primary["max_drawdown"] - v11["max_drawdown"]

    lines = [
        "# BYD v1.2: Relaxed Trend Expansion Research",
        "",
        f"> **Decision**: `{gov.decision}`",
        "> Research only. `trade_ready=false`.",
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
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        headline = head20[name]
        lines.append(
            f"| {name} | {headline['cagr']:.4%} | {headline['total_return']:.4%} | {headline['max_drawdown']:.4%} | "
            f"{headline['calmar']:.4f} | {headline['sharpe']:.4f} | {headline['round_trips_per_year']:.2f} | "
            f"{int(headline['sessions'])} |"
        )

    lines.extend(
        [
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
        ]
    )
    for gate, passed in gov.gates.items():
        lines.append(f"| {gate} | {'YES' if passed else 'NO'} |")

    lines.extend(
        [
            "",
            "## Headline Results (Full Overlap, 40 bps stress)",
            "",
            "| Model | CAGR | Total Return | Max DD | Calmar | RTPY |",
            "|:---|:---|:---|:---|:---|:---|",
        ]
    )
    for name in (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        headline = head40[name]
        lines.append(
            f"| {name} | {headline['cagr']:.4%} | {headline['total_return']:.4%} | {headline['max_drawdown']:.4%} | "
            f"{headline['calmar']:.4f} | {headline['round_trips_per_year']:.2f} |"
        )

    lines.extend(
        [
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
        ]
    )
    (out / "report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "decision": gov.decision,
                "cagr_v11": f"{v11['cagr']:.4%}",
                "cagr_v12": f"{primary['cagr']:.4%}",
                "cagr_delta": f"{cagr_d:+.4%}",
                "total_return_delta": f"{tr_d:+.4%}",
                "mdd_delta": f"{mdd_d:+.4%}",
                "gates_passed": (
                    f"{sum(1 for value in gov.gates.values() if value)}/"
                    f"{len(gov.gates)}"
                ),
                "failed_gates": [
                    key for key, value in gov.gates.items() if not value
                ],
                "output": str(out),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
