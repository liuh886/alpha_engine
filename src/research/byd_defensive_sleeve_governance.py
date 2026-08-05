"""Governance layer for the frozen BYD defensive-sleeve screen.

Period concentration must be computed from relative terminal wealth, not from
an arithmetic difference between standalone total returns. The latter embeds
the starting wealth accumulated in earlier calendar blocks and overstates the
contribution of the high-return development period.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.research.byd_defensive_sleeve_screen import (
    CANDIDATES,
    CHALLENGERS,
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
)

PERIOD_WINDOWS = (
    "development",
    "fixed_validation",
    "retrospective_2025_plus",
)


def relative_terminal_return(
    candidate_total_return: float,
    baseline_total_return: float,
) -> float:
    """Return candidate terminal wealth relative to baseline terminal wealth."""

    candidate_wealth = 1.0 + float(candidate_total_return)
    baseline_wealth = 1.0 + float(baseline_total_return)
    if candidate_wealth <= 0.0 or baseline_wealth <= 0.0:
        raise ValueError("terminal wealth must remain positive")
    return candidate_wealth / baseline_wealth - 1.0


def build_period_contribution(
    evaluation: pd.DataFrame,
    available_candidates: tuple[str, ...],
) -> pd.DataFrame:
    """Build period-relative returns and positive contribution shares."""

    primary = evaluation.loc[evaluation["cost_bps"].eq(PRIMARY_COST_BPS)].copy()
    rows: list[dict[str, Any]] = []
    for symbol in available_candidates:
        symbol_rows: list[dict[str, Any]] = []
        positive_total = 0.0
        for window in PERIOD_WINDOWS:
            candidate = primary.loc[
                primary["candidate"].eq(symbol) & primary["window"].eq(window)
            ]
            cash = primary.loc[
                primary["candidate"].eq("cash") & primary["window"].eq(window)
            ]
            if len(candidate) != 1 or len(cash) != 1:
                raise RuntimeError(
                    f"missing unique period metrics for {symbol} / {window}"
                )
            candidate_total = float(candidate.iloc[0]["total_return"])
            cash_total = float(cash.iloc[0]["total_return"])
            relative = relative_terminal_return(candidate_total, cash_total)
            positive_total += max(relative, 0.0)
            symbol_rows.append(
                {
                    "candidate": symbol,
                    "window": window,
                    "candidate_total_return": candidate_total,
                    "cash_total_return": cash_total,
                    "incremental_total_return": relative,
                    "relative_return_method": (
                        "candidate_terminal_wealth_divided_by_cash_terminal_wealth_minus_1"
                    ),
                }
            )
        for row in symbol_rows:
            row["positive_contribution_share"] = (
                max(float(row["incremental_total_return"]), 0.0) / positive_total
                if positive_total > 0.0
                else 1.0
            )
            rows.append(row)
    return pd.DataFrame(rows)


def govern_evaluation(
    evaluation: pd.DataFrame,
    provisional_summary: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply the exact Issue #546 gates to evaluation evidence."""

    available = tuple(str(value) for value in provisional_summary["available_candidates"])
    blocked = dict(provisional_summary["blocked_candidates"])
    periods = build_period_contribution(evaluation, available)

    full20 = evaluation.loc[
        evaluation["window"].eq("full_overlap")
        & evaluation["cost_bps"].eq(PRIMARY_COST_BPS)
    ].set_index("candidate")
    full40 = evaluation.loc[
        evaluation["window"].eq("full_overlap")
        & evaluation["cost_bps"].eq(STRESS_COST_BPS)
    ].set_index("candidate")
    cash20 = full20.loc["cash"]
    cash40 = full40.loc["cash"]
    reference20 = full20.loc["515180.SH"]
    reference40 = full40.loc["515180.SH"]

    gate_matrix: dict[str, dict[str, Any]] = {
        symbol: {
            "data_status": "blocked",
            "blocker": blocker,
            "cash_gates": {},
            "cash_qualified": False,
            "challenge_gates": {},
            "challenge_qualified": False,
        }
        for symbol, blocker in blocked.items()
    }
    qualified_challengers: list[str] = []
    for symbol in available:
        if symbol not in CANDIDATES:
            raise RuntimeError(f"unregistered candidate entered screen: {symbol}")
        current20 = full20.loc[symbol]
        current40 = full40.loc[symbol]
        symbol_periods = periods.loc[periods["candidate"].eq(symbol)]
        cash_gates = {
            "cagr_delta_at_least_50bp": (
                float(current20["cagr"] - cash20["cagr"]) >= 0.005
            ),
            "calmar_not_below_cash": (
                float(current20["calmar"]) >= float(cash20["calmar"])
            ),
            "drawdown_not_worse_by_more_than_1pp": (
                float(current20["max_drawdown"] - cash20["max_drawdown"]) >= -0.01
            ),
            "stress_total_increment_nonnegative": (
                relative_terminal_return(
                    float(current40["total_return"]),
                    float(cash40["total_return"]),
                )
                >= 0.0
            ),
            "all_three_periods_positive": bool(
                symbol_periods["incremental_total_return"].gt(0.0).all()
            ),
            "max_period_share_at_most_60pct": (
                float(symbol_periods["positive_contribution_share"].max()) <= 0.60
            ),
            "round_trips_at_most_3": (
                float(current20["round_trips_per_year"]) <= 3.0
            ),
        }
        cash_qualified = all(cash_gates.values())
        challenge_gates: dict[str, bool] = {}
        challenge_qualified = False
        if symbol in CHALLENGERS and cash_qualified:
            calmar_path = (
                float(current20["calmar"] - reference20["calmar"]) >= 0.02
                and float(current20["cagr"] - reference20["cagr"]) >= -0.005
            )
            drawdown_path = (
                float(current20["max_drawdown"] - reference20["max_drawdown"]) >= 0.02
                and float(current20["cagr"] - reference20["cagr"]) >= -0.005
            )
            challenge_gates = {
                "stress_total_not_below_515180": (
                    float(current40["total_return"])
                    >= float(reference40["total_return"])
                ),
                "calmar_or_drawdown_path": calmar_path or drawdown_path,
            }
            challenge_qualified = all(challenge_gates.values())
            if challenge_qualified:
                qualified_challengers.append(symbol)
        gate_matrix[symbol] = {
            "data_status": "canonical_pass",
            "cash_gates": cash_gates,
            "cash_qualified": cash_qualified,
            "challenge_gates": challenge_gates,
            "challenge_qualified": challenge_qualified,
        }

    reference_qualified = bool(gate_matrix["515180.SH"]["cash_qualified"])
    if not reference_qualified:
        decision = "structural_conflict_515180_failed_recalculation"
        selected = None
    elif not qualified_challengers:
        decision = "retain_515180_as_only_prospective_etf"
        selected = None
    else:
        ranked = sorted(
            qualified_challengers,
            key=lambda symbol: (
                float(full20.loc[symbol, "calmar"]),
                float(full40.loc[symbol, "total_return"]),
                -float(
                    periods.loc[
                        periods["candidate"].eq(symbol),
                        "positive_contribution_share",
                    ].max()
                ),
            ),
            reverse=True,
        )
        selected = ranked[0]
        decision = "add_single_historical_challenger_to_prospective_parallel"

    summary = dict(provisional_summary)
    summary.update(
        {
            "schema_version": "byd_defensive_sleeve_screen_v2",
            "period_contribution_method": (
                "candidate_terminal_wealth_divided_by_cash_terminal_wealth_minus_1"
            ),
            "gate_matrix": gate_matrix,
            "governed_decision": decision,
            "selected_challenger": selected,
            "research_only": True,
            "trade_ready": False,
            "fresh_holdout": False,
        }
    )
    return periods, summary
