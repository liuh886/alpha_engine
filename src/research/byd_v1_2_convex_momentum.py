"""BYD v1.2 convex-momentum exposure budget.

The candidate was selected on consumed historical evidence in Issue #592 and
is eligible for prospective validation only. Historical diagnostics produced
by this module never authorize formal promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import (
    AllocationResult,
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    metrics,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    build_expansion_state,
    run_financed_allocation,
)

BASELINE = "byd_v1_1"
CANDIDATE = "byd_v1_2_convex_momentum_budget_v1"
MAX_FINANCED_INCREMENT = 0.125
FULL_INCREMENT_MOMENTUM = 0.15
CONVEX_POWER = 4.0

NEIGHBOR_SPECS: tuple[tuple[float, float], ...] = (
    (3.0, 0.18),
    (3.25, 0.17),
    (3.5, 0.16),
    (4.0, 0.16),
    (4.0, 0.19),
)


@dataclass(frozen=True)
class ConvexMomentumDecision:
    decision: str
    prospective_candidate_selected: bool
    promotion_authorized: bool
    gates: dict[str, bool]
    diagnostics: dict[str, float]


def momentum_scale(
    momentum: pd.Series,
    *,
    full_increment_momentum: float = FULL_INCREMENT_MOMENTUM,
    convex_power: float = CONVEX_POWER,
) -> pd.Series:
    """Map positive 20-session momentum to a bounded financing scale."""
    if full_increment_momentum <= 0.0:
        raise ValueError("full_increment_momentum must be positive")
    if convex_power <= 0.0:
        raise ValueError("convex_power must be positive")
    normalized = (momentum.astype(float).clip(lower=0.0) / float(full_increment_momentum)).clip(
        lower=0.0, upper=1.0
    )
    return normalized.pow(float(convex_power))


def build_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    full_increment_momentum: float = FULL_INCREMENT_MOMENTUM,
    convex_power: float = CONVEX_POWER,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    state = build_expansion_state(common, signals)
    base = state["base_byd_weight"].astype(float)
    active = state["trend_expansion_active"].astype(bool)
    scale = momentum_scale(
        common["mom_20"],
        full_increment_momentum=full_increment_momentum,
        convex_power=convex_power,
    )
    increment = active.astype(float) * MAX_FINANCED_INCREMENT * scale

    baseline = pd.DataFrame(
        {
            "byd_weight": base,
            "etf_weight": 1.0 - base,
            "cash_weight": 0.0,
        },
        index=common.index,
    )
    candidate_byd = base + increment
    candidate_etf = (1.0 - base).where(increment.eq(0.0), 0.0)
    candidate = pd.DataFrame(
        {
            "byd_weight": candidate_byd,
            "etf_weight": candidate_etf,
            "cash_weight": 1.0 - candidate_byd - candidate_etf,
        },
        index=common.index,
    )

    for name, frame in ((BASELINE, baseline), (CANDIDATE, candidate)):
        if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
            raise AssertionError(f"{name} weights do not sum to one")
        if frame["byd_weight"].lt(0.0).any() or frame["etf_weight"].lt(0.0).any():
            raise AssertionError(f"{name} contains a negative risky-asset weight")
    if candidate["byd_weight"].gt(1.125 + 1e-12).any():
        raise AssertionError("candidate exceeds the 112.5% BYD cap")
    if (increment.gt(0.0) & ~active).any():
        raise AssertionError("financing exists outside the original frozen state")

    diagnostics = state.copy()
    diagnostics["momentum_scale"] = scale
    diagnostics["financed_increment"] = increment
    diagnostics["candidate_byd_weight"] = candidate_byd
    return {BASELINE: baseline, CANDIDATE: candidate}, diagnostics


def run_candidates(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
    full_increment_momentum: float = FULL_INCREMENT_MOMENTUM,
    convex_power: float = CONVEX_POWER,
) -> tuple[dict[str, AllocationResult], pd.DataFrame]:
    decisions, diagnostics = build_decisions(
        common,
        signals,
        full_increment_momentum=full_increment_momentum,
        convex_power=convex_power,
    )
    results = {
        name: run_financed_allocation(
            name,
            common,
            decision,
            cost_bps=cost_bps,
            annual_financing_rate=annual_financing_rate,
        )
        for name, decision in decisions.items()
    }
    return results, diagnostics


def _window_metrics(result: AllocationResult, start: str, end: str) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty evaluation window: {start} to {end}")
    output = metrics(block)
    returns = block["net_return"].dropna()
    output.update(
        {
            "transaction_cost_paid": float(block.loc[returns.index, "cost"].sum()),
            "financing_cost_paid": float(block.loc[returns.index, "financing_cost"].sum()),
            "mean_borrowed_weight": float(block.loc[returns.index, "borrowed_weight"].mean()),
            "financed_sessions": float(block.loc[returns.index, "borrowed_weight"].gt(0.0).sum()),
        }
    )
    return output


def build_evaluation(
    primary_results: dict[str, AllocationResult],
    stress_results: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario, cost_bps, rate, results in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE, primary_results),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, stress_results),
    ):
        for model, result in results.items():
            for window, (start, end) in WINDOWS.items():
                rows.append(
                    {
                        "scenario": scenario,
                        "model": model,
                        "cost_bps": cost_bps,
                        "annual_financing_rate": rate,
                        "window": window,
                        **_window_metrics(result, start, end),
                    }
                )
    return pd.DataFrame(rows)


def _terminal_wealth(result: AllocationResult, start: str, end: str) -> float:
    returns = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"]
    return float((1.0 + returns.dropna()).prod())


def period_attribution(results: dict[str, AllocationResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    relative: dict[str, float] = {}
    for period, (start, end) in WINDOWS.items():
        if period == "full_overlap":
            continue
        relative[period] = (
            _terminal_wealth(results[CANDIDATE], start, end)
            / _terminal_wealth(results[BASELINE], start, end)
            - 1.0
        )
    positive_total = sum(max(value, 0.0) for value in relative.values())
    for period, value in relative.items():
        rows.append(
            {
                "model": CANDIDATE,
                "period": period,
                "relative_terminal_wealth": value,
                "positive_contribution_share": (
                    max(value, 0.0) / positive_total if positive_total > 0.0 else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def episode_attribution(results: dict[str, AllocationResult]) -> pd.DataFrame:
    candidate = results[CANDIDATE].daily
    baseline = results[BASELINE].daily.reindex(candidate.index)
    active = candidate["borrowed_weight"].gt(0.0)
    starts = active & ~active.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in candidate.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        base = baseline.loc[block.index]
        candidate_wealth = float((1.0 + block["net_return"]).prod())
        baseline_wealth = float((1.0 + base["net_return"]).prod())
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
                "relative_terminal_wealth": candidate_wealth / baseline_wealth - 1.0,
                "mean_financed_increment": float(block["borrowed_weight"].mean()),
                "maximum_financed_increment": float(block["borrowed_weight"].max()),
            }
        )
    positive_total = sum(max(row["relative_terminal_wealth"], 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(row["relative_terminal_wealth"], 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return pd.DataFrame(rows)


def leave_one_episode_out(
    results: dict[str, AllocationResult],
    episodes: pd.DataFrame,
) -> pd.DataFrame:
    candidate = results[CANDIDATE].daily
    baseline = results[BASELINE].daily.reindex(candidate.index)
    daily_ratio = (1.0 + candidate["net_return"]) / (1.0 + baseline["net_return"])
    rows: list[dict[str, Any]] = []
    for episode in episodes.itertuples(index=False):
        excluded = daily_ratio.loc[
            ~daily_ratio.index.to_series().between(episode.start, episode.end)
        ]
        rows.append(
            {
                "excluded_episode_id": int(episode.episode_id),
                "excluded_start": episode.start,
                "excluded_end": episode.end,
                "relative_terminal_wealth": float(excluded.prod() - 1.0),
            }
        )
    return pd.DataFrame(rows)


def episode_bootstrap(
    episodes: pd.DataFrame,
    *,
    seed: int = 42,
    samples: int = 100_000,
) -> dict[str, float]:
    values = episodes["relative_terminal_wealth"].to_numpy(dtype=float)
    if len(values) == 0:
        return {
            "samples": float(samples),
            "positive_probability": 0.0,
            "median_relative_terminal_wealth": 0.0,
            "fifth_percentile_relative_terminal_wealth": 0.0,
        }
    generator = np.random.default_rng(seed)
    draws = generator.choice(values, size=(samples, len(values)), replace=True)
    terminal = np.prod(1.0 + draws, axis=1) - 1.0
    return {
        "samples": float(samples),
        "positive_probability": float(np.mean(terminal > 0.0)),
        "median_relative_terminal_wealth": float(np.median(terminal)),
        "fifth_percentile_relative_terminal_wealth": float(np.quantile(terminal, 0.05)),
    }


def _full_row(evaluation: pd.DataFrame, model: str, scenario: str) -> pd.Series:
    selected = evaluation.loc[
        (evaluation["model"] == model)
        & (evaluation["scenario"] == scenario)
        & (evaluation["window"] == "full_overlap")
    ]
    if len(selected) != 1:
        raise ValueError(f"missing full-overlap row for {model}/{scenario}")
    return selected.iloc[0]


def _spec_passes(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    convex_power: float,
    full_increment_momentum: float,
) -> bool:
    primary, _ = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
        convex_power=convex_power,
        full_increment_momentum=full_increment_momentum,
    )
    stress, _ = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
        convex_power=convex_power,
        full_increment_momentum=full_increment_momentum,
    )
    evaluation = build_evaluation(primary, stress)
    periods = period_attribution(primary)
    episodes = episode_attribution(primary)
    baseline_primary = _full_row(evaluation, BASELINE, "primary")
    candidate_primary = _full_row(evaluation, CANDIDATE, "primary")
    baseline_stress = _full_row(evaluation, BASELINE, "stress")
    candidate_stress = _full_row(evaluation, CANDIDATE, "stress")
    period_map = periods.set_index("period")["relative_terminal_wealth"]
    return bool(
        float(candidate_primary["cagr"] - baseline_primary["cagr"]) >= 0.005
        and float(candidate_primary["max_drawdown"] - baseline_primary["max_drawdown"]) >= -0.02
        and float(candidate_stress["total_return"]) >= float(baseline_stress["total_return"])
        and float(period_map["fixed_validation"]) > 0.0
        and float(period_map["retrospective_2025_plus"]) > 0.0
        and float(periods["positive_contribution_share"].max()) <= 0.60
        and float(episodes["positive_contribution_share"].max()) <= 0.40
    )


def evaluate_decision(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    evaluation: pd.DataFrame,
    periods: pd.DataFrame,
    episodes: pd.DataFrame,
    leave_one_out: pd.DataFrame,
) -> ConvexMomentumDecision:
    baseline_primary = _full_row(evaluation, BASELINE, "primary")
    candidate_primary = _full_row(evaluation, CANDIDATE, "primary")
    baseline_stress = _full_row(evaluation, BASELINE, "stress")
    candidate_stress = _full_row(evaluation, CANDIDATE, "stress")
    period_map = periods.set_index("period")["relative_terminal_wealth"]
    max_period_share = float(periods["positive_contribution_share"].max())
    max_episode_share = float(episodes["positive_contribution_share"].max())
    passing_neighbors = sum(
        _spec_passes(
            common,
            signals,
            convex_power=power,
            full_increment_momentum=momentum,
        )
        for power, momentum in NEIGHBOR_SPECS
    )
    stress_relative = float(
        (1.0 + candidate_stress["total_return"]) / (1.0 + baseline_stress["total_return"]) - 1.0
    )
    gates = {
        "cagr_improvement_gte_0_50pp": float(candidate_primary["cagr"] - baseline_primary["cagr"])
        >= 0.005,
        "mdd_worsening_lte_2pp": float(
            candidate_primary["max_drawdown"] - baseline_primary["max_drawdown"]
        )
        >= -0.02,
        "stress_relative_wealth_positive": stress_relative > 0.0,
        "fixed_validation_relative_positive": float(period_map["fixed_validation"]) > 0.0,
        "retrospective_2025_plus_relative_positive": float(period_map["retrospective_2025_plus"])
        > 0.0,
        "period_concentration_lte_60pct": max_period_share <= 0.60,
        "episode_concentration_lte_40pct": max_episode_share <= 0.40,
        "minimum_10_episodes": int(len(episodes)) >= 10,
        "round_trips_per_year_lte_3": float(candidate_primary["round_trips_per_year"]) <= 3.0,
        "leave_any_episode_out_positive": float(leave_one_out["relative_terminal_wealth"].min())
        > 0.0,
        "minimum_3_passing_neighbors": passing_neighbors >= 3,
    }
    selected = all(gates.values())
    return ConvexMomentumDecision(
        decision=(
            "select_for_prospective_validation"
            if selected
            else "retain_byd_v1_1_without_new_challenger"
        ),
        prospective_candidate_selected=selected,
        promotion_authorized=False,
        gates=gates,
        diagnostics={
            "cagr_delta": float(candidate_primary["cagr"] - baseline_primary["cagr"]),
            "mdd_delta": float(
                candidate_primary["max_drawdown"] - baseline_primary["max_drawdown"]
            ),
            "stress_relative_terminal_wealth": stress_relative,
            "max_period_positive_share": max_period_share,
            "max_episode_positive_share": max_episode_share,
            "completed_episodes": float(len(episodes)),
            "financed_sessions": float(candidate_primary["financed_sessions"]),
            "round_trips_per_year": float(candidate_primary["round_trips_per_year"]),
            "minimum_leave_one_episode_out_relative_wealth": float(
                leave_one_out["relative_terminal_wealth"].min()
            ),
            "passing_neighbor_specs": float(passing_neighbors),
        },
    )


def run_full_diagnostic(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> dict[str, Any]:
    primary, ledger = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress, stress_ledger = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    if not ledger.equals(stress_ledger):
        raise RuntimeError("candidate decisions drifted across cost scenarios")
    evaluation = build_evaluation(primary, stress)
    periods = period_attribution(primary)
    episodes = episode_attribution(primary)
    leave_one_out = leave_one_episode_out(primary, episodes)
    bootstrap = episode_bootstrap(episodes)
    decision = evaluate_decision(
        common,
        signals,
        evaluation,
        periods,
        episodes,
        leave_one_out,
    )
    return {
        "primary_results": primary,
        "stress_results": stress,
        "ledger": ledger,
        "evaluation": evaluation,
        "periods": periods,
        "episodes": episodes,
        "leave_one_out": leave_one_out,
        "bootstrap": bootstrap,
        "decision": decision,
    }
