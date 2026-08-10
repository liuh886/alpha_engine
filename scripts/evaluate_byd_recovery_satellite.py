#!/usr/bin/env python3
"""Evaluate the frozen Issue #732 BYD recovery-only satellite.

The challenger is a strict delta on the accepted V1.2 Champion. It uses one
pre-result-frozen recovery state and never changes the existing offense branch.
All historical results are retrospective consumed evidence and cannot authorize
promotion.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import WINDOWS, metrics, prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    build_decisions as build_v12_decisions,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    run_financed_allocation,
)
from src.research.rules_based_allocation_experiment_runner import (
    _extract_inputs,
    _formal_daily,
    _formal_section,
    _load_formal,
    _load_spec,
    _trace_reproduction,
)

SPEC = PROJECT_ROOT / "configs/research_experiments/byd_v1_3_min_hold_bear_defense_certification_v1.yaml"
CHALLENGER = "byd_recovery_satellite_drawdown252_rebound60_v1"
RECOVERY_THRESHOLD = 0.026937
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
EPS = 1e-12


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _window_metrics(daily: pd.DataFrame, window: str) -> dict[str, float]:
    start, end = WINDOWS[window]
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    output = metrics(block)
    returns = block["net_return"].dropna()
    output["financed_sessions"] = float(
        block.loc[returns.index, "borrowed_weight"].gt(EPS).sum()
    )
    output["transaction_cost_paid"] = float(block.loc[returns.index, "cost"].sum())
    output["financing_cost_paid"] = float(
        block.loc[returns.index, "financing_cost"].sum()
    )
    return output


def _relative_wealth(candidate: pd.DataFrame, baseline: pd.DataFrame, window: str) -> float:
    start, end = WINDOWS[window]
    c = _wealth(candidate.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    b = _wealth(baseline.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    return c / b - 1.0


def _episodes(mask: pd.Series) -> pd.DataFrame:
    active = mask.fillna(False).astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    ids = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in active.groupby(ids):
        if pd.isna(raw_id):
            continue
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
            }
        )
    return pd.DataFrame(rows)


def _build_challenger_decision(
    champion_decision: pd.DataFrame,
    base: pd.Series,
    recovery_factor: pd.Series,
) -> tuple[pd.DataFrame, pd.Series]:
    state = base.eq(0.75) & recovery_factor.ge(RECOVERY_THRESHOLD)
    challenger = champion_decision.copy(deep=True)
    challenger.loc[state, "byd_weight"] = 1.0
    challenger.loc[state, "etf_weight"] = 0.0
    challenger.loc[state, "cash_weight"] = 0.0

    changed = challenger.ne(champion_decision).any(axis=1)
    if not changed.equals(state.astype(bool)):
        raise AssertionError("recovery challenger changed outside the frozen state")
    if (changed & base.ne(0.75)).any():
        raise AssertionError("recovery challenger changed a non-defensive core state")
    if champion_decision.loc[changed, "cash_weight"].lt(-EPS).any():
        raise AssertionError("recovery challenger overlapped an existing financed expansion")
    if not np.allclose(challenger.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("recovery challenger weights do not sum to one")
    if challenger.lt(-EPS).any().any():
        raise AssertionError("recovery challenger produced a negative long-only sleeve")
    return challenger, state.astype(bool)


def _evaluation(
    common: pd.DataFrame,
    champion_decision: pd.DataFrame,
    challenger_decision: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scenario_results: dict[str, Any] = {}
    for scenario, cost_bps, financing_rate in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE),
    ):
        champion = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        challenger = run_financed_allocation(
            CHALLENGER,
            common,
            challenger_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        scenario_results[scenario] = {"champion": champion, "challenger": challenger}
        for window in WINDOWS:
            champion_metrics = _window_metrics(champion.daily, window)
            challenger_metrics = _window_metrics(challenger.daily, window)
            rows.append(
                {
                    "scenario": scenario,
                    "window": window,
                    "champion": champion_metrics,
                    "challenger": challenger_metrics,
                    "delta": {
                        "cagr": challenger_metrics["cagr"] - champion_metrics["cagr"],
                        "sharpe": challenger_metrics["sharpe"] - champion_metrics["sharpe"],
                        "max_drawdown": challenger_metrics["max_drawdown"]
                        - champion_metrics["max_drawdown"],
                        "calmar": challenger_metrics["calmar"] - champion_metrics["calmar"],
                        "turnover_units": challenger_metrics["turnover_units"]
                        - champion_metrics["turnover_units"],
                        "relative_terminal_wealth": _relative_wealth(
                            challenger.daily, champion.daily, window
                        ),
                    },
                }
            )
    return rows, scenario_results


def _episode_attribution(champion: pd.DataFrame, challenger: pd.DataFrame) -> list[dict[str, Any]]:
    delta_active = challenger["position_byd_weight"].gt(
        champion["position_byd_weight"] + EPS
    )
    table = _episodes(delta_active)
    rows: list[dict[str, Any]] = []
    for episode in table.itertuples(index=False):
        c = challenger.loc[episode.start : episode.end, "net_return"]
        b = champion.loc[episode.start : episode.end, "net_return"]
        relative = _wealth(c) / _wealth(b) - 1.0
        rows.append(
            {
                "episode_id": int(episode.episode_id),
                "start": episode.start.strftime("%Y-%m-%d"),
                "end": episode.end.strftime("%Y-%m-%d"),
                "sessions": int(episode.sessions),
                "relative_terminal_wealth": relative,
            }
        )
    positive_total = sum(max(float(row["relative_terminal_wealth"]), 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(float(row["relative_terminal_wealth"]), 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


def _period_attribution(champion: pd.DataFrame, challenger: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in ("development", "fixed_validation", "retrospective_2025_plus"):
        rows.append(
            {
                "window": window,
                "relative_terminal_wealth": _relative_wealth(
                    challenger, champion, window
                ),
            }
        )
    positive_total = sum(max(float(row["relative_terminal_wealth"]), 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(float(row["relative_terminal_wealth"]), 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


def _annual_attribution(champion: pd.DataFrame, challenger: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in sorted(set(champion.index.year)):
        mask = champion.index.year == year
        idx = champion.index[mask]
        rows.append(
            {
                "year": int(year),
                "champion_return": _wealth(champion.loc[idx, "net_return"]) - 1.0,
                "challenger_return": _wealth(challenger.loc[idx, "net_return"]) - 1.0,
                "relative_terminal_wealth": _wealth(challenger.loc[idx, "net_return"])
                / _wealth(champion.loc[idx, "net_return"])
                - 1.0,
                "executed_recovery_sessions": int(
                    challenger.loc[idx, "position_byd_weight"].gt(
                        champion.loc[idx, "position_byd_weight"] + EPS
                    ).sum()
                ),
            }
        )
    return rows


def _gate_result(
    evaluation: list[dict[str, Any]],
    period_attribution: list[dict[str, Any]],
    episode_attribution: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {(row["scenario"], row["window"]): row for row in evaluation}
    primary_full = by_key[("primary", "full_overlap")]
    primary_fixed = by_key[("primary", "fixed_validation")]
    primary_recent = by_key[("primary", "retrospective_2025_plus")]
    stress_full = by_key[("stress", "full_overlap")]
    stress_recent = by_key[("stress", "retrospective_2025_plus")]

    max_period_share = max(
        (float(row["positive_contribution_share"]) for row in period_attribution),
        default=0.0,
    )
    max_episode_share = max(
        (float(row["positive_contribution_share"]) for row in episode_attribution),
        default=0.0,
    )
    champion_turnover = float(primary_full["champion"]["turnover_units"])
    challenger_turnover = float(primary_full["challenger"]["turnover_units"])

    gates = {
        "full_cagr_delta_ge_minus_50bp": float(primary_full["delta"]["cagr"]) >= -0.005,
        "full_sharpe_delta_nonnegative": float(primary_full["delta"]["sharpe"]) >= 0.0,
        "mdd_deterioration_le_100bp": float(primary_full["delta"]["max_drawdown"]) >= -0.01,
        "fixed_validation_relative_wealth_nonnegative": float(
            primary_fixed["delta"]["relative_terminal_wealth"]
        ) >= 0.0,
        "recent_relative_wealth_nonnegative": float(
            primary_recent["delta"]["relative_terminal_wealth"]
        ) >= 0.0,
        "stress_full_relative_wealth_nonnegative": float(
            stress_full["delta"]["relative_terminal_wealth"]
        ) >= 0.0,
        "stress_recent_relative_wealth_nonnegative": float(
            stress_recent["delta"]["relative_terminal_wealth"]
        ) >= 0.0,
        "period_positive_concentration_le_60pct": max_period_share <= 0.60 + EPS,
        "largest_positive_episode_share_le_50pct": max_episode_share <= 0.50 + EPS,
        "turnover_le_1_5x_champion": challenger_turnover <= champion_turnover * 1.5 + EPS,
    }
    return {
        "gates": gates,
        "passed": int(sum(gates.values())),
        "total": int(len(gates)),
        "all_pass": bool(all(gates.values())),
        "max_period_positive_contribution_share": max_period_share,
        "max_episode_positive_contribution_share": max_episode_share,
        "champion_turnover_units": champion_turnover,
        "challenger_turnover_units": challenger_turnover,
    }


def run() -> dict[str, Any]:
    spec = _load_spec(SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-recovery-phase2-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = _extract_inputs(spec, root)
        common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
        cutoff = pd.Timestamp(str(spec["data"]["historical_cutoff"]))
        common = common.loc[:cutoff].copy()
        signals = signals.reindex(common.index)

        standard_results, _ = run_v12_candidates(
            common,
            signals,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        formal = _load_formal(spec)
        performance_path, performance_sha = _formal_section(
            formal,
            "performance",
            str(spec["baseline"]["performance_sha256"]),
        )
        formal_daily = _formal_daily(performance_path, str(cutoff.date()))
        formal_trace = _trace_reproduction(
            formal_daily, standard_results[V12_MODEL_ID].daily
        )
        if not formal_trace["exact"]:
            raise RuntimeError("Phase 2 refuses a non-exact V1.2 Champion")

        decisions, _ = build_v12_decisions(common, signals)
        champion_decision = decisions[V12_MODEL_ID]
        champion_rebuilt = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        rebuilt_trace = _trace_reproduction(formal_daily, champion_rebuilt.daily)
        if not rebuilt_trace["exact"]:
            raise RuntimeError("rebuilt V1.2 decision path does not match formal trace")

        canonical = load_canonical_snapshot(byd_dir)
        full = build_research_dataset(canonical.adjusted, canonical.sessions)
        full.index = pd.to_datetime(full.index).normalize()
        factor = full["drawdown252_x_rebound60"].reindex(common.index).astype(float)
        base = signals["base_byd_weight"].astype(float)
        challenger_decision, recovery_state = _build_challenger_decision(
            champion_decision, base, factor
        )

        evaluation, scenario_results = _evaluation(
            common, champion_decision, challenger_decision
        )
        primary_champion = scenario_results["primary"]["champion"].daily
        primary_challenger = scenario_results["primary"]["challenger"].daily
        period = _period_attribution(primary_champion, primary_challenger)
        episodes = _episode_attribution(primary_champion, primary_challenger)
        annual = _annual_attribution(primary_champion, primary_challenger)
        gates = _gate_result(evaluation, period, episodes)

    return {
        "schema_version": "1.0",
        "issue": 732,
        "challenger": CHALLENGER,
        "research_only": True,
        "historical_evidence_consumed": True,
        "automatic_promotion": False,
        "frozen_contract": {
            "threshold": RECOVERY_THRESHOLD,
            "state": "base_byd_weight == 0.75 AND drawdown252_x_rebound60 >= threshold",
            "action": "75% BYD / 25% 515180 -> 100% BYD / 0% 515180 while state is true",
            "existing_v1_2_expansion_changed": False,
            "vol_1_15_combined": False,
            "shorter_sma_combined": False,
            "min_hold_or_hysteresis_added": False,
        },
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "formal_trace": formal_trace,
            "rebuilt_decision_trace": rebuilt_trace,
        },
        "data_identity": data_identity,
        "decision_state_sessions": int(recovery_state.sum()),
        "evaluation": evaluation,
        "period_attribution": period,
        "episode_attribution": episodes,
        "annual_attribution": annual,
        "retrospective_gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/research/byd_recovery_satellite_phase2.json",
    )
    args = parser.parse_args()
    payload = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
