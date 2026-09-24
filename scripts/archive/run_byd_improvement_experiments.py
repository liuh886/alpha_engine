#!/usr/bin/env python3
"""Reproduce the BYD architecture experiments merged in PR #588.

This runner is diagnostic only. It normalizes the inconsistent return contracts
of the historical experiment modules and never authorizes model promotion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    AllocationResult,
    prepare_common_dataset,
)
from src.research.byd_adaptive_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
)
from src.research.byd_adaptive_expansion import build_evaluation as ae_eval
from src.research.byd_adaptive_expansion import episode_attribution as ae_episodes
from src.research.byd_adaptive_expansion import governed_result as ae_gov
from src.research.byd_adaptive_expansion import period_contribution as ae_pc
from src.research.byd_adaptive_expansion import run_candidates as ae_run
from src.research.byd_multi_signal_blend import build_evaluation as bl_eval
from src.research.byd_multi_signal_blend import governed_result as bl_gov
from src.research.byd_multi_signal_blend import period_contribution as bl_pc
from src.research.byd_multi_signal_blend import run_candidates as bl_run
from src.research.byd_trend_fix_v1 import build_evaluation as tf_eval
from src.research.byd_trend_fix_v1 import governed_result as tf_gov
from src.research.byd_trend_fix_v1 import period_contribution as tf_pc
from src.research.byd_trend_fix_v1 import run_candidates as tf_run
from src.research.byd_vol_target import build_evaluation as vt_eval
from src.research.byd_vol_target import governed_result as vt_gov
from src.research.byd_vol_target import period_contribution as vt_pc
from src.research.byd_vol_target import run_candidates as vt_run

BASELINE = "byd_v1_1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _normalise_run_output(
    value: Any,
) -> tuple[dict[str, AllocationResult], pd.DataFrame | None]:
    """Normalize historical modules that return either a dict or a tuple."""
    if isinstance(value, dict):
        return value, None
    if isinstance(value, tuple) and value and isinstance(value[0], dict):
        extra = value[1] if len(value) > 1 and isinstance(value[1], pd.DataFrame) else None
        return value[0], extra
    raise TypeError(f"unsupported experiment run output: {type(value).__name__}")


def run_expansion(
    name: str,
    common: pd.DataFrame,
    signals: pd.DataFrame,
    output: Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    primary_results, state = ae_run(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress_results, _ = ae_run(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    evaluation = ae_eval(primary_results, stress_results)
    contribution = ae_pc(primary_results)
    primary_key = next(name for name in primary_results if name != BASELINE)
    episodes = ae_episodes(
        primary_results[primary_key],
        primary_results[BASELINE],
        state,
    )
    governed = ae_gov(evaluation, contribution, episodes)
    return _save(
        name,
        output,
        evaluation,
        contribution,
        governed,
        primary_results,
        stress_results,
        state,
    )


def run_trend_fix(
    name: str,
    common: pd.DataFrame,
    signals: pd.DataFrame,
    output: Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    primary_results, state = tf_run(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress_results, _ = tf_run(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    evaluation = tf_eval(primary_results, stress_results)
    contribution = tf_pc(primary_results)
    governed = tf_gov(evaluation, contribution)
    return _save(
        name,
        output,
        evaluation,
        contribution,
        governed,
        primary_results,
        stress_results,
        state,
    )


def run_simple(
    name: str,
    common: pd.DataFrame,
    signals: pd.DataFrame,
    output: Path,
    run_fn: Any,
    eval_fn: Any,
    contribution_fn: Any,
    governed_fn: Any,
) -> tuple[dict[str, Any], pd.DataFrame]:
    primary_results, primary_extra = _normalise_run_output(
        run_fn(common, signals, cost_bps=PRIMARY_COST_BPS)
    )
    stress_results, _ = _normalise_run_output(
        run_fn(common, signals, cost_bps=STRESS_COST_BPS)
    )
    evaluation = eval_fn(primary_results, stress_results)
    contribution = contribution_fn(primary_results)
    governed = governed_fn(evaluation, contribution)
    return _save(
        name,
        output,
        evaluation,
        contribution,
        governed,
        primary_results,
        stress_results,
        primary_extra,
    )


def _save(
    name: str,
    output: Path,
    evaluation: pd.DataFrame,
    contribution: pd.DataFrame,
    governed: Any,
    primary_results: dict[str, AllocationResult],
    stress_results: dict[str, AllocationResult],
    extra: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    sub = output / name
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "daily").mkdir(parents=True, exist_ok=True)
    evaluation.to_csv(
        sub / "evaluation.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    contribution.to_csv(
        sub / "period_contribution.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    for model, result in primary_results.items():
        result.daily.to_csv(
            sub / "daily" / f"{model}_20bps.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )
        stress_results[model].daily.to_csv(
            sub / "daily" / f"{model}_40bps.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )
    if extra is not None:
        extra.to_csv(
            sub / "state_ledger.csv",
            index=True,
            float_format="%.12f",
            lineterminator="\n",
        )

    full = evaluation.loc[evaluation["window"] == "full_overlap"].copy()
    if "scenario" in full.columns:
        full = full.loc[full["scenario"] == "primary"]
    if "cost_bps" in full.columns:
        full = full.loc[full["cost_bps"] == PRIMARY_COST_BPS]
    full = full.set_index("model")

    fields = (
        "cagr",
        "total_return",
        "max_drawdown",
        "calmar",
        "round_trips_per_year",
    )
    summary = {
        "experiment": name,
        "decision": governed.decision,
        "gates": governed.gates,
        "diagnostics": governed.diagnostics,
        "headline": {
            model: {
                field: float(full.loc[model, field])
                for field in fields
                if field in full.columns
            }
            for model in full.index
        },
        "historical_evidence_consumed": True,
        "promotion_authorized": False,
        "research_only": True,
        "trade_ready": False,
    }
    (sub / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return summary, full


def _add_headlines(
    target: dict[str, dict[str, float]],
    prefix: str,
    frame: pd.DataFrame,
) -> None:
    fields = (
        "cagr",
        "total_return",
        "max_drawdown",
        "calmar",
        "round_trips_per_year",
    )
    for model in frame.index:
        target[f"{prefix}_{model}"] = {
            field: float(frame.loc[model, field]) for field in fields
        }


def main() -> int:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    common, signals, _ = prepare_common_dataset(args.byd_dir, args.etf_dir)
    print(
        f"Data: {len(common)} sessions, "
        f"{common.index.min().date()} to {common.index.max().date()}"
    )

    headlines: dict[str, dict[str, float]] = {}

    _, frame = run_expansion("adaptive_expansion", common, signals, output)
    _add_headlines(headlines, "ae", frame)

    _, frame = run_simple(
        "vol_target",
        common,
        signals,
        output,
        vt_run,
        vt_eval,
        vt_pc,
        vt_gov,
    )
    _add_headlines(headlines, "vt", frame)

    _, frame = run_simple(
        "multi_signal_blend",
        common,
        signals,
        output,
        bl_run,
        bl_eval,
        bl_pc,
        bl_gov,
    )
    _add_headlines(headlines, "bl", frame)

    _, frame = run_trend_fix("trend_fix", common, signals, output)
    _add_headlines(headlines, "tf", frame)

    comparison = pd.DataFrame(headlines).T
    comparison.to_csv(
        output / "master_comparison.csv",
        index=True,
        float_format="%.12f",
        lineterminator="\n",
    )
    print(comparison.to_string(float_format=lambda value: f"{value:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
