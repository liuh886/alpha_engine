#!/usr/bin/env python3
"""Run the frozen BYD/515180 trend-guard experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_515180_trend_guard import (
    TrendGuardInputs,
    run_trend_guard_screen,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def main() -> None:
    args = parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    evaluation, periods, diagnostics, summary = run_trend_guard_screen(
        TrendGuardInputs(byd_dir=args.byd_dir, etf_dir=args.etf_dir)
    )
    write_csv(output / "evaluation.csv", evaluation)
    write_csv(output / "period_contribution.csv", periods)
    write_csv(output / "trend_diagnostics.csv", diagnostics)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full = evaluation.loc[
        evaluation["window"].eq("full_overlap")
        & evaluation["cost_bps"].eq(20.0)
    ].sort_values("calmar", ascending=False)
    report = [
        "# BYD / 515180 trend-guard experiment",
        "",
        f"- Decision: `{summary['governed_decision']}`",
        f"- Primary: `{summary['primary_candidate']}`",
        f"- Range: `{summary['overlap_start']}` to `{summary['cutoff']}`",
        "- BYD V1.0 risk budget: unchanged",
        "- Execution: prior-close decision, next common eligible open",
        "- Costs: 20 bps primary, 40 bps stress",
        "- Research only: `true`",
        "- Trade ready: `false`",
        "",
        "## Full-overlap 20 bps",
        "",
        full[
            [
                "model",
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "round_trips_per_year",
                "mean_etf_weight",
            ]
        ].to_markdown(index=False),
        "",
        "## Frozen gates",
        "",
        "```json",
        json.dumps(summary["gates"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    (output / "README.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
