"""Leakage-safe execution engine for BYD/515180 allocation evidence."""

from __future__ import annotations

import pandas as pd

from src.research.byd_515180_allocation import AllocationResult


def execute_next_common_open(
    decision: pd.DataFrame,
    eligible: pd.Series,
) -> pd.DataFrame:
    """Execute only the preceding close decision at a common eligible open.

    The first overlap interval starts in cash because there is no preceding
    close decision inside the executable ETF sample. Ineligible opens do not
    advance the pending allocation.
    """

    if not decision.index.equals(eligible.index):
        raise ValueError("decision and common eligibility must align")
    required = {"byd_weight", "etf_weight", "cash_weight"}
    if set(decision.columns) != required:
        raise ValueError(f"decision columns must be exactly {sorted(required)}")
    current = pd.Series(
        {"byd_weight": 0.0, "etf_weight": 0.0, "cash_weight": 1.0},
        dtype=float,
    )
    prior_decision = decision.iloc[0].astype(float).copy()
    rows: list[pd.Series] = []
    for i, (_, is_eligible) in enumerate(eligible.items()):
        if i > 0 and bool(is_eligible):
            current = prior_decision.copy()
        rows.append(current.copy())
        prior_decision = decision.iloc[i].astype(float).copy()
    executed = pd.DataFrame(rows, index=decision.index)
    executed.columns = [f"position_{column}" for column in decision.columns]
    return executed


def run_allocation(
    name: str,
    common: pd.DataFrame,
    decision: pd.DataFrame,
    *,
    cost_bps: float,
) -> AllocationResult:
    executed = execute_next_common_open(decision, common["common_open_eligible"])
    byd_weight = executed["position_byd_weight"]
    etf_weight = executed["position_etf_weight"]
    gross = byd_weight * common["byd_open_return"] + etf_weight * common["etf_open_return"]
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = 0.0
    cost = turnover * cost_bps / 10_000.0
    daily = pd.concat([decision.add_prefix("decision_"), executed], axis=1)
    daily["common_open_eligible"] = common["common_open_eligible"]
    daily["byd_return"] = common["byd_open_return"]
    daily["etf_return"] = common["etf_open_return"]
    daily["gross_return"] = gross
    daily["turnover_units"] = turnover
    daily["cost"] = cost
    daily["net_return"] = gross - cost
    daily = daily.iloc[:-1].copy()
    changes = executed.ne(executed.shift(1)).any(axis=1)
    trades = daily.loc[
        changes.reindex(daily.index).fillna(False),
        [
            "position_byd_weight",
            "position_etf_weight",
            "position_cash_weight",
            "turnover_units",
            "cost",
            "common_open_eligible",
        ],
    ].copy()
    trades.index.name = "date"
    return AllocationResult(name=name, daily=daily, trades=trades.reset_index())
