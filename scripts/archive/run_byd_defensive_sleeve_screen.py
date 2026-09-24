#!/usr/bin/env python3
"""Run the frozen BYD defensive-sleeve convergence screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_defensive_sleeve_governance import govern_evaluation
from src.research.byd_defensive_sleeve_screen import ScreenInputs, run_screen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-515180-dir", type=Path, required=True)
    parser.add_argument("--etf-512890-dir", type=Path, required=True)
    parser.add_argument("--etf-511010-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def main() -> None:
    args = parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    evaluation, _, correlations, provisional_summary = run_screen(
        ScreenInputs(
            byd_dir=args.byd_dir,
            etf_dirs={
                "515180.SH": args.etf_515180_dir,
                "512890.SH": args.etf_512890_dir,
                "511010.SH": args.etf_511010_dir,
            },
        )
    )
    periods, summary = govern_evaluation(evaluation, provisional_summary)
    write_csv(output / "evaluation.csv", evaluation)
    write_csv(output / "period_contribution.csv", periods)
    write_csv(output / "correlation_diagnostics.csv", correlations)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full = evaluation.loc[
        (evaluation["window"] == "full_overlap")
        & (evaluation["cost_bps"] == 20.0)
    ].sort_values("calmar", ascending=False)
    report = [
        "# BYD defensive-sleeve convergence screen",
        "",
        f"- Governed decision: `{summary['governed_decision']}`",
        f"- Selected challenger: `{summary['selected_challenger']}`",
        f"- Common overlap: `{summary['overlap_start']}` to `{summary['cutoff']}`",
        f"- Common sessions: `{summary['common_sessions']}`",
        f"- Common eligible opens: `{summary['common_eligible_opens']}`",
        f"- Blocked candidates: `{json.dumps(summary['blocked_candidates'], ensure_ascii=False, sort_keys=True)}`",
        "- Execution: prior-close V1.0 target, next all-assets common eligible open",
        "- Costs: 20 bps primary, 40 bps stress",
        "- Period contribution: relative terminal wealth versus cash",
        "- Historical freshness: `false`",
        "- Research only: `true`",
        "",
        "## Full-overlap 20 bps ranking",
        "",
        full[
            [
                "candidate",
                "cagr",
                "total_return",
                "max_drawdown",
                "calmar",
                "round_trips_per_year",
            ]
        ].to_markdown(index=False),
        "",
        "## Period-relative contribution",
        "",
        periods[
            [
                "candidate",
                "window",
                "incremental_total_return",
                "positive_contribution_share",
            ]
        ].to_markdown(index=False),
        "",
        "## Frozen gates",
        "",
        "```json",
        json.dumps(summary["gate_matrix"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    (output / "README.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
