#!/usr/bin/env python3
"""Run the frozen BYD SMA25/70 breakout ATR verification contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.byd_sma_atr_claim import (
    CANDIDATES,
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    annual_return_table,
    build_all,
    candidate_development_table,
    evaluation_table,
    governed_decision,
    period_relative_concentration,
    run_candidate,
    run_same_close_diagnostic,
    select_candidate,
    tactical_episode_table,
    window_metrics,
)
from src.research.byd_v1_2_recovery_state import (
    EVALUATION_WINDOWS,
    build_v1_0_decision_position,
    load_canonical_snapshot,
    run_buy_and_hold,
    run_strategy,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy()
    if isinstance(output.index, pd.DatetimeIndex):
        output = output.reset_index(names="date")
    output.to_csv(path, index=False, float_format="%.12f", lineterminator="\n")


def _pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def _metric_lines(title: str, block: dict[str, float]) -> list[str]:
    return [
        f"### {title}",
        "",
        f"- Total return: `{_pct(block['total_return'])}`",
        f"- CAGR: `{_pct(block['cagr'])}`",
        f"- Maximum drawdown: `{_pct(block['max_drawdown'])}`",
        f"- Calmar: `{block['calmar']:.4f}`",
        f"- Exposure: `{_pct(block['exposure'])}`",
        f"- Round trips/year: `{block['round_trips_per_year']:.3f}`",
        "",
    ]


def _report(
    summary: dict[str, Any],
    development: pd.DataFrame,
    diagnostic: dict[str, float],
) -> str:
    decision = summary["decision"]
    selected = summary["selected_candidate"]
    lines = [
        "# BYD SMA25/70 breakout ATR claim verification",
        "",
        "> Governed retrospective evidence on the immutable BYD canonical v1 snapshot.",
        "",
        "## Decision",
        "",
        f"`{decision}`",
        "",
        f"Selected frozen candidate: `{selected}`.",
        "",
        "The same-close claimant result is diagnostic only. The governed decision uses close signals executed at the next independently confirmed eligible open.",
        "",
        "## Claimant same-close diagnostic",
        "",
        f"- CAGR: `{_pct(diagnostic['cagr'])}`",
        f"- Total return: `{_pct(diagnostic['total_return'])}`",
        f"- Maximum drawdown: `{_pct(diagnostic['max_drawdown'])}`",
        f"- Calmar: `{diagnostic['calmar']:.4f}`",
        "",
        "## Frozen development ranking",
        "",
        "| Candidate | Core | ATR | Confirm | CAGR | MDD | Calmar | Gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for row in development.itertuples(index=False):
        lines.append(
            "| "
            f"{row.candidate} | {row.core_position:.2f} | {row.atr_multiple:.1f} | "
            f"{row.exit_confirmation_days} | {_pct(row.cagr)} | "
            f"{_pct(row.max_drawdown)} | {row.calmar:.4f} | "
            f"{'pass' if row.development_selection_gate else 'fail'} |"
        )
    lines.append("")
    lines.extend(
        _metric_lines(
            "Selected candidate — full history, 20 bps",
            summary["selected_full_history_20bps"],
        )
    )
    lines.extend(
        _metric_lines(
            "Canonical V1.0 — full history, 20 bps",
            summary["canonical_v1_full_history_20bps"],
        )
    )
    lines.extend(
        _metric_lines(
            "Buy and hold — full history, 20 bps",
            summary["buy_hold_full_history_20bps"],
        )
    )
    lines.extend(
        [
            "## Fixed validation, 2023–2024",
            "",
            f"- Selected total return: `{_pct(summary['selected_fixed_validation_20bps']['total_return'])}`",
            f"- V1.0 total return: `{_pct(summary['canonical_v1_fixed_validation_20bps']['total_return'])}`",
            f"- Buy-and-hold total return: `{_pct(summary['buy_hold_fixed_validation_20bps']['total_return'])}`",
            f"- Selected MDD: `{_pct(summary['selected_fixed_validation_20bps']['max_drawdown'])}`",
            "",
            "## Retrospective 2025+",
            "",
            f"- Selected total return: `{_pct(summary['selected_retrospective_2025_plus_20bps']['total_return'])}`",
            f"- V1.0 total return: `{_pct(summary['canonical_v1_retrospective_2025_plus_20bps']['total_return'])}`",
            "",
            "## Frozen gates",
            "",
        ]
    )
    for gate, passed in summary["gates"].items():
        lines.append(f"- `{gate}`: **{'pass' if passed else 'fail'}**")
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- `research_only=true`",
            "- `trade_ready=false`",
            "- fresh historical holdout: `false`",
            "- no post-result threshold, ATR, breakout-window, cost, or candidate changes",
            "- any successor requires a new pre-registered issue and prospective evidence",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = _parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    canonical = load_canonical_snapshot(args.snapshot_dir)
    dataset, schedules = build_all(canonical.adjusted, canonical.sessions)

    results_20 = {
        name: run_candidate(dataset, schedule, cost_bps=PRIMARY_COST_BPS)
        for name, schedule in schedules.items()
    }
    results_40 = {
        name: run_candidate(dataset, schedule, cost_bps=STRESS_COST_BPS)
        for name, schedule in schedules.items()
    }

    v1_decision = build_v1_0_decision_position(dataset)
    v1_20 = run_strategy(
        dataset,
        v1_decision,
        name="canonical_v1_0",
        cost_bps_per_turnover_unit=PRIMARY_COST_BPS,
        initial_position=0.75,
    )
    v1_40 = run_strategy(
        dataset,
        v1_decision,
        name="canonical_v1_0",
        cost_bps_per_turnover_unit=STRESS_COST_BPS,
        initial_position=0.75,
    )
    buy_hold_20 = run_buy_and_hold(
        dataset,
        cost_bps_per_turnover_unit=PRIMARY_COST_BPS,
    )
    buy_hold_40 = run_buy_and_hold(
        dataset,
        cost_bps_per_turnover_unit=STRESS_COST_BPS,
    )

    development = candidate_development_table(results_20, v1_20)
    selected_name, selection_gate_pass = select_candidate(development)
    selected_spec = next(spec for spec in CANDIDATES if spec.name == selected_name)
    selected = results_20[selected_name]

    same_close = run_same_close_diagnostic(
        dataset,
        schedules["claimant_flat_atr32"],
        cost_bps=PRIMARY_COST_BPS,
    )
    full_start, full_end = EVALUATION_WINDOWS["full_history"]
    same_close_metrics = window_metrics(
        same_close,
        start=full_start,
        end=full_end,
    )

    episodes = tactical_episode_table(
        dataset,
        selected,
        selected_spec,
        cost_bps=PRIMARY_COST_BPS,
    )
    period_table, largest_period_share = period_relative_concentration(
        selected,
        v1_20,
    )
    decision = governed_decision(
        selected_name,
        selection_gate_pass,
        results_20,
        results_40,
        v1_20,
        v1_40,
        buy_hold_20,
        episodes,
        largest_period_share,
    )
    decision.update(
        {
            "issue": 521,
            "canonical_snapshot_sha256": "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179",
            "canonical_adjusted_sha256": canonical.manifest["adjusted_sha256"],
            "canonical_manifest_sha256": canonical.manifest["manifest_sha256"],
            "canonical_cutoff": canonical.manifest["cutoff"],
            "claimant_same_close_diagnostic": same_close_metrics,
            "candidate_count": len(CANDIDATES),
            "primary_cost_bps": PRIMARY_COST_BPS,
            "stress_cost_bps": STRESS_COST_BPS,
        }
    )

    selected_daily = selected.daily.join(
        schedules[selected_name].daily,
        how="left",
        rsuffix="_signal",
    )
    selected_daily["wealth"] = (
        1.0 + selected_daily["net_return"].fillna(0.0)
    ).cumprod()

    evaluation_20 = evaluation_table(
        {
            **results_20,
            "canonical_v1_0": v1_20,
            "buy_hold": buy_hold_20,
            "claimant_same_close_diagnostic": same_close,
        },
        cost_bps=PRIMARY_COST_BPS,
    )
    evaluation_40 = evaluation_table(
        {
            selected_name: results_40[selected_name],
            "canonical_v1_0": v1_40,
            "buy_hold": buy_hold_40,
        },
        cost_bps=STRESS_COST_BPS,
    )
    evaluation = pd.concat([evaluation_20, evaluation_40], ignore_index=True)
    annual = annual_return_table(selected, v1_20, buy_hold_20)

    signal_log = schedules[selected_name].daily.loc[
        schedules[selected_name].daily["entry_signal"]
        | schedules[selected_name].daily["exit_signal"]
    ].copy()

    _write_frame(output / "candidate_development_ranking.csv", development)
    _write_frame(output / "evaluation_metrics.csv", evaluation)
    _write_frame(output / "selected_daily.csv", selected_daily)
    _write_frame(output / "selected_trades.csv", selected.trades)
    _write_frame(output / "selected_signal_log.csv", signal_log)
    _write_frame(output / "tactical_episodes.csv", episodes)
    _write_frame(output / "period_concentration.csv", period_table)
    _write_frame(output / "annual_returns.csv", annual)
    _write_frame(output / "claimant_same_close_daily.csv", same_close.daily)

    (output / "summary.json").write_text(
        json.dumps(
            decision,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        _report(decision, development, same_close_metrics),
        encoding="utf-8",
    )
    print(json.dumps(decision, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
