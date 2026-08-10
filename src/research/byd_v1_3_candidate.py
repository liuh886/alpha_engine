"""Frozen BYD v1.3 challenger logic.

This module contains only the candidate delta relative to the accepted BYD v1.2
architecture:

1. a 20 eligible-session minimum hold on the V1.0 risk-on/off hysteresis;
2. 55% BYD / 45% 515180.SH defense while the canonical market state is bear;
3. a 15% maximum financed trend-expansion increment with convex power 2.

The accepted V1.2 baseline is never reimplemented here. Certification must bind
the current formal Bundle v2 baseline and may use the maintained V1.2 runner only
to reproduce stress scenarios after its primary trace has been checked against
the formal bundle.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import AllocationResult
from src.research.byd_v1_2_convex_momentum import momentum_scale
from src.research.byd_v1_2_trend_expansion import (
    build_expansion_state,
    run_financed_allocation,
)

CANDIDATE_NAME = "byd_v1_3_min_hold_bear_defense"

V13_MIN_HOLD_DAYS = 20
V13_BEAR_DEFENSE_BYD = 0.55
V13_BEAR_DEFENSE_ETF = 0.45
V13_EXPANSION_PCT = 0.15
V13_CONVEX_POWER = 2.0
V13_FULL_INCREMENT_MOMENTUM = 0.15

_REQUIRED_FULL_HISTORY_COLUMNS = {
    "sma_120",
    "mom_20",
    "mom_60",
    "market_state",
    "open_research_eligible",
}
_REQUIRED_COMMON_COLUMNS = {
    "market_state",
    "vol_state",
    "drawdown_252",
    "mom_20",
    "mom_60",
    "common_open_eligible",
    "byd_open_return",
    "etf_open_return",
}


def _stateful_min_hold(
    entry: pd.Series,
    exit_: pd.Series,
    eligible: pd.Series,
    *,
    min_hold: int,
) -> pd.Series:
    """Return a hysteresis state with a minimum count of eligible sessions.

    The state is decided at the close. The hold counter advances only on rows
    whose BYD open is research eligible, matching the evidence clock rather than
    counting quarantined opens as valid holding opportunities.
    """

    if min_hold < 1:
        raise ValueError("min_hold must be positive")
    if not entry.index.equals(exit_.index) or not entry.index.equals(eligible.index):
        raise ValueError("entry, exit and eligible indices must match")

    active = False
    eligible_held = 0
    values: list[float] = []
    for enter_now, exit_now, eligible_now in zip(
        entry.fillna(False),
        exit_.fillna(False),
        eligible.fillna(False),
        strict=True,
    ):
        if active and bool(eligible_now):
            eligible_held += 1

        if active and bool(exit_now) and eligible_held >= min_hold:
            active = False
            eligible_held = 0
        elif not active and bool(enter_now):
            active = True
            eligible_held = 0

        values.append(1.0 if active else 0.0)

    return pd.Series(values, index=entry.index, dtype=float, name="base_risk_on")


def build_v13_signals(
    full_byd_dataset: pd.DataFrame,
    *,
    target_index: Iterable[pd.Timestamp] | pd.Index | None = None,
) -> pd.DataFrame:
    """Build V1.3 signals on the full canonical BYD history.

    `full_byd_dataset` must be the output of `build_research_dataset()` before
    any 515180 overlap restriction. This preserves the pre-ETF SMA and hysteresis
    state. `target_index` may then restrict the finished signal path to the
    executable BYD/515180 overlap.
    """

    missing = sorted(_REQUIRED_FULL_HISTORY_COLUMNS - set(full_byd_dataset.columns))
    if missing:
        raise ValueError(f"full BYD dataset missing V1.3 signal columns: {missing}")

    risk_on_entry = (
        full_byd_dataset["close"].gt(full_byd_dataset["sma_120"])
        & full_byd_dataset["mom_20"].gt(0.0)
    )
    risk_off_exit = (
        full_byd_dataset["close"].lt(full_byd_dataset["sma_120"])
        & full_byd_dataset["mom_60"].lt(0.0)
    )
    base_risk_on = _stateful_min_hold(
        risk_on_entry,
        risk_off_exit,
        full_byd_dataset["open_research_eligible"].astype(bool),
        min_hold=V13_MIN_HOLD_DAYS,
    )

    bear = full_byd_dataset["market_state"].eq("bear")
    base_byd = pd.Series(0.75, index=full_byd_dataset.index, dtype=float)
    base_byd.loc[base_risk_on.gt(0.5)] = 1.0
    base_byd.loc[base_risk_on.lt(0.5) & bear] = V13_BEAR_DEFENSE_BYD

    result = pd.DataFrame(
        {
            "base_byd_weight": base_byd,
            "base_risk_on": base_risk_on,
            "is_bear": bear.astype(bool),
        },
        index=full_byd_dataset.index,
    )
    if target_index is None:
        return result

    index = pd.DatetimeIndex(pd.to_datetime(list(target_index))).normalize()
    restricted = result.reindex(index)
    if restricted.isna().any().any():
        missing_dates = [
            stamp.strftime("%Y-%m-%d")
            for stamp in restricted.index[restricted.isna().any(axis=1)]
        ]
        raise ValueError(f"V1.3 signals missing target dates: {missing_dates[:5]}")
    return restricted


def build_v13_decision(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the frozen V1.3 allocation and rule-input diagnostics."""

    missing = sorted(_REQUIRED_COMMON_COLUMNS - set(common.columns))
    if missing:
        raise ValueError(f"common dataset missing V1.3 execution columns: {missing}")
    if not common.index.equals(signals.index):
        raise ValueError("common and V1.3 signal indices must match")
    if "base_byd_weight" not in signals:
        raise ValueError("V1.3 signals missing base_byd_weight")

    expansion_state = build_expansion_state(
        common,
        signals[["base_byd_weight"]],
    )
    active = expansion_state["trend_expansion_active"].astype(bool)
    scale = momentum_scale(
        common["mom_20"],
        full_increment_momentum=V13_FULL_INCREMENT_MOMENTUM,
        convex_power=V13_CONVEX_POWER,
    )
    increment = active.astype(float) * V13_EXPANSION_PCT * scale

    base = signals["base_byd_weight"].astype(float)
    byd = base + increment
    etf = (1.0 - base).where(increment.eq(0.0), 0.0)
    cash = 1.0 - byd - etf
    decision = pd.DataFrame(
        {
            "byd_weight": byd,
            "etf_weight": etf,
            "cash_weight": cash,
        },
        index=common.index,
    )

    if not np.allclose(decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("V1.3 weights do not sum to one")
    if decision["byd_weight"].lt(0.0).any() or decision["etf_weight"].lt(0.0).any():
        raise AssertionError("V1.3 contains negative risky-asset weight")
    if decision["byd_weight"].gt(1.15 + 1e-12).any():
        raise AssertionError("V1.3 exceeds the frozen 115% BYD cap")
    bear_defense = signals["is_bear"] & signals["base_risk_on"].lt(0.5)
    if not np.allclose(
        decision.loc[bear_defense & increment.eq(0.0), "etf_weight"],
        V13_BEAR_DEFENSE_ETF,
        atol=1e-12,
    ):
        raise AssertionError("V1.3 bear defense ETF weight drifted")

    diagnostics = expansion_state.copy()
    diagnostics["base_risk_on"] = signals["base_risk_on"]
    diagnostics["is_bear"] = signals["is_bear"]
    diagnostics["momentum_scale"] = scale
    diagnostics["financed_increment"] = increment
    diagnostics["candidate_byd_weight"] = byd
    diagnostics["candidate_etf_weight"] = etf
    diagnostics["candidate_cash_weight"] = cash
    return decision, diagnostics


def run_v13_candidate(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> tuple[AllocationResult, pd.DataFrame]:
    """Execute the frozen candidate through the maintained allocation engine."""

    decision, diagnostics = build_v13_decision(common, signals)
    result = run_financed_allocation(
        CANDIDATE_NAME,
        common,
        decision,
        cost_bps=cost_bps,
        annual_financing_rate=annual_financing_rate,
    )
    return result, diagnostics
