"""Formal BYD v1.3 low-vol-confirmed recovery overlay.

The accepted V1.2 core and convex-momentum expansion remain unchanged. V1.3
adds one recovery lifecycle while the V1.2 base is defensive: a new recovery
edge may re-risk 75/25 to 100% BYD only when the same decision date is in the
existing low-volatility state. Historical retuning is not supported.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MODEL_ID = "byd_v1_3_recovery_event_low_vol_confirmation_v1"
PUBLIC_MODEL_ID = "byd_v1_3"
DISPLAY_NAME = "BYD v1.3"
RECOVERY_THRESHOLD = 0.026937
HOLD_ELIGIBLE_SESSIONS = 20
EPS = 1e-12


def build_detector(base_target: pd.Series, recovery_factor: pd.Series) -> pd.Series:
    """Return the frozen defensive recovery detector."""
    if not base_target.index.equals(recovery_factor.index):
        raise ValueError("BYD v1.3 detector inputs must share one index")
    return (base_target.eq(0.75) & recovery_factor.ge(RECOVERY_THRESHOLD)).astype(bool)


def build_recovery_decision(
    champion_decision: pd.DataFrame,
    base_target: pd.Series,
    recovery_factor: pd.Series,
    vol_state: pd.Series,
    eligible: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the frozen low-vol recovery lifecycle on top of exact V1.2 targets."""
    index = champion_decision.index
    for value in (base_target, recovery_factor, vol_state, eligible):
        if not value.index.equals(index):
            raise ValueError("BYD v1.3 recovery inputs must share one index")

    detector = build_detector(base_target, recovery_factor)
    event_edge = detector & ~detector.shift(1, fill_value=False)
    confirmed_edge = event_edge & vol_state.eq("low")

    active = False
    remaining = 0
    lifecycle_id = 0
    state_rows: list[dict[str, Any]] = []

    for i, _date in enumerate(index):
        termination = ""
        if active and float(base_target.iloc[i]) >= 1.0 - EPS:
            active = False
            remaining = 0
            termination = "core_recovered"

        started = False
        if (
            not active
            and bool(confirmed_edge.iloc[i])
            and np.isclose(float(base_target.iloc[i]), 0.75)
        ):
            active = True
            remaining = HOLD_ELIGIBLE_SESSIONS
            lifecycle_id += 1
            started = True

        overlay = active and np.isclose(float(base_target.iloc[i]), 0.75)
        state_rows.append(
            {
                "detector": bool(detector.iloc[i]),
                "event_edge": bool(event_edge.iloc[i]),
                "low_vol_confirmed_edge": bool(confirmed_edge.iloc[i]),
                "entry_vol_state": str(vol_state.iloc[i]),
                "lifecycle_started": started,
                "lifecycle_id": lifecycle_id if overlay else 0,
                "overlay_decision_active": overlay,
                "remaining_eligible_sessions_before_decision": remaining if overlay else 0,
                "termination_on_decision": termination,
            }
        )

        next_open_eligible = i + 1 < len(eligible) and bool(eligible.iloc[i + 1])
        if overlay and next_open_eligible:
            remaining -= 1
            if remaining <= 0:
                active = False
                remaining = 0
                state_rows[-1]["termination_on_decision"] = "max_hold"

    state = pd.DataFrame(state_rows, index=index)
    overlay = state["overlay_decision_active"].astype(bool)
    decision = champion_decision.copy(deep=True)
    decision.loc[overlay, "byd_weight"] = 1.0
    decision.loc[overlay, "etf_weight"] = 0.0
    decision.loc[overlay, "cash_weight"] = 0.0

    changed = decision.ne(champion_decision).any(axis=1)
    if not changed.equals(overlay):
        raise AssertionError("BYD v1.3 changed outside the declared recovery overlay")
    if (changed & base_target.ne(0.75)).any():
        raise AssertionError("BYD v1.3 changed a non-defensive V1.2 core state")
    if not np.allclose(decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("BYD v1.3 target weights do not sum to one")
    return decision, state
