#!/usr/bin/env python3
"""Run the governed BYD/515180 allocation experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    build_decisions,
    complementarity_diagnostics,
    evaluation_table,
    governed_decisions,
    prepare_common_dataset,
    run_allocation,
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

    common, signals, event_ledger = prepare_common_dataset(args.byd_dir, args.etf_dir)
    decisions = build_decisions(common, signals)
    results_20 = {
        name: run_allocation(name, common, decision, cost_bps=PRIMARY_COST_BPS)
        for name, decision in decisions.items()
    }
    results_40 = {
        name: run_allocation(name, common, decision, cost_bps=STRESS_COST_BPS)
        for name, decision in decisions.items()
    }

    evaluation = pd.concat(
        [
            evaluation_table(results_20, PRIMARY_COST_BPS),
            evaluation_table(results_40, STRESS_COST_BPS),
        ],
        ignore_index=True,
    )
    correlations, conditional = complementarity_diagnostics(common, signals)
    governed, concentration_tables = governed_decisions(results_20, results_40)

    write_csv(output / "evaluation.csv", evaluation)
    write_csv(output / "correlation_diagnostics.csv", correlations)
    write_csv(output / "conditional_complementarity.csv", conditional)
    write_csv(output / "recovery_event_ledger.csv", event_ledger)
    write_csv(
        output / "etf_total_return_reconciliation.csv",
        common[
            [
                "etf_open_return",
                "etf_raw_plus_cash_return",
                "etf_total_return_reconciliation_error",
                "etf_dividend_next",
            ]
        ],
    )
    write_csv(output / "signals.csv", signals)
    for name, decision in decisions.items():
        write_csv(output / "decisions" / f"{name}.csv", decision)
        write_csv(output / "daily" / f"{name}_20bps.csv", results_20[name].daily)
        write_csv(output / "daily" / f"{name}_40bps.csv", results_40[name].daily)
        write_csv(output / "trades" / f"{name}_20bps.csv", results_20[name].trades.set_index("date"))
    for name, table in concentration_tables.items():
        write_csv(output / "concentration" / f"{name}.csv", table)

    summary = {
        "schema_version": "byd_515180_allocation_evidence_v1",
        "overlap_first_date": common.index.min().strftime("%Y-%m-%d"),
        "overlap_last_date": common.index.max().strftime("%Y-%m-%d"),
        "overlap_sessions": int(len(common)),
        "common_eligible_opens": int(common["common_open_eligible"].sum()),
        "governed_decisions": governed,
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["cost_bps"] == PRIMARY_COST_BPS)
    ].sort_values("calmar", ascending=False)
    report = [
        "# BYD / 515180 core-dividend allocation",
        "",
        f"- Overlap: `{summary['overlap_first_date']}` to `{summary['overlap_last_date']}`",
        f"- Sessions: `{summary['overlap_sessions']}`",
        f"- Common eligible opens: `{summary['common_eligible_opens']}`",
        "- Execution: close decision, next common independently confirmed eligible open",
        "- Costs: 20 bps primary, 40 bps stress",
        "- Historical freshness: `false`",
        "",
        "## Full-overlap 20 bps ranking",
        "",
        full[["model", "cagr", "total_return", "max_drawdown", "calmar", "round_trips_per_year"]].to_markdown(index=False),
        "",
        "## Governed decisions",
        "",
        "```json",
        json.dumps(governed, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    (output / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
