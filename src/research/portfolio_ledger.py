"""Observation and attribution of the canonical walkforward return engine.

Units are fractional adjusted-price units per unit pre-fill gross NAV. They are
not broker shares: E4 deducts costs from returns without modelling fee funding.
The E4 turnover convention and exact NumPy tie policy remain in the engine.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def ledger_tables(snapshots: list[dict], *, signal_sessions: dict[str, str],
                  mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert engine states into auditable daily and per-asset accounting."""
    daily, assets = [], []
    nav = gross_nav = 1.0
    for row in snapshots:
        start, end = row["return_start"], row["return_end"]
        signal = signal_sessions[start]
        if signal > start or (mode == "delayed_close_1session" and signal >= start):
            raise ValueError("signal is not available before the declared fill")
        before = np.asarray(row["weight_before_fill"])
        held = np.asarray(row["target_and_held_weight"])
        drift = np.asarray(row["weight_drifted"])
        p0, p1 = np.asarray(row["price_start"]), np.asarray(row["price_end"])
        trade = held - before
        # These are allocations of the engine's original turnover/cost convention.
        entry_turn = np.abs(trade) * (1.0 if row["entry_from_cash"] else 0.5)
        exit_turn = drift if row["terminal_liquidation"] else np.zeros(len(held))
        cost = (entry_turn + exit_turn) * row["friction_per_turnover"]
        contribution = held * (p1 / p0 - 1.0)
        if not (np.isclose(contribution.sum(), row["gross"], atol=1e-13, rtol=0) and
                np.isclose((contribution-cost).sum(), row["net"], atol=1e-13, rtol=0) and
                np.isclose((entry_turn+exit_turn).sum(), row["turnover"], atol=1e-13, rtol=0)):
            raise ValueError("ledger does not reconcile to canonical engine")
        for j, symbol in enumerate(row["symbols"]):
            assets.append({
                "date": end, "symbol": symbol, "signal_session": signal,
                "order_session": start, "fill_session": start,
                "order_phase": ("after_close_idealized_same_price" if mode == "e4_same_close_idealized"
                                else "before_next_close_assumption_not_observed_order"),
                "fill_phase": "official_close_price_proxy",
                "signal_available_phase": "after_official_close",
                "return_start": start, "return_end": end,
                "fill_price_kind": "verified_anchored_adjusted_close_proxy",
                "actual_fill_observed": False,
                "fill_price": p0[j], "mark_price": p1[j],
                "weight_before_fill": before[j], "target_weight": held[j],
                "simulated_held_weight": held[j], "drifted_weight": drift[j],
                "trade_weight": trade[j],
                "quantity_before_per_unit_gross_nav": before[j] / p0[j],
                "quantity_after_per_unit_gross_nav": held[j] / p0[j],
                "fill_quantity_per_unit_gross_nav": trade[j] / p0[j],
                "terminal_sell_quantity_per_unit_gross_nav":
                    -held[j] / p0[j] if row["terminal_liquidation"] else 0.0,
                "turnover": entry_turn[j] + exit_turn[j],
                "cost_return": cost[j], "gross_contribution": contribution[j],
                "net_contribution": contribution[j] - cost[j],
                # Additive NAV contributions telescope exactly to final net return.
                "pnl_nav_units": nav * (contribution[j] - cost[j]),
            })
        daily.append({
            "date": end, "return_start": start, "signal_session": signal,
            "order_session": start, "fill_session": start,
            "terminal_fill_session": end if row["terminal_liquidation"] else None,
            "execution_mode": mode, "gross": row["gross"], "net": row["net"],
            "qqq": row["qqq"], "turnover": row["turnover"],
            "cost_return": float(cost.sum()), "nav_before": nav,
            "nav": nav * (1+row["net"]), "gross_nav": gross_nav * (1+row["gross"]),
            "cash_weight_before_fill": float(1-before.sum()),
            "cash_weight_after_fill": float(1-held.sum()),
            "cash_weight_after_terminal": 1.0 if row["terminal_liquidation"] else 0.0,
            "max_held_weight": float(held.max()), "held_hhi": float(np.square(held).sum()),
            "max_drifted_weight": float(drift.max()),
            "full_replacements": int(((held > 0) & (before == 0)).sum()),
            "cost_accounting": "E4_return_deduction_no_fee_funding_model",
            "actual_fill_observed": False,
        })
        nav *= 1+row["net"]
        gross_nav *= 1+row["gross"]
    return pd.DataFrame(daily), pd.DataFrame(assets)


def replay_ledger(*, scores: pd.DataFrame, prices: pd.DataFrame, qqq: pd.Series,
                  sessions: list[str], top_k: int = 5, friction: float = 0.0008,
                  signal_sessions: dict[str, str] | None = None,
                  mode: str = "e4_same_close_idealized") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Record a canonical simulation, never infer trades from published Top5 strings."""
    from src.research.walkforward.pipeline import _simulate_portfolio
    if mode not in ("e4_same_close_idealized", "delayed_close_1session"):
        raise ValueError("unsupported execution contract")
    for frame in (scores.loc[sessions], prices.loc[sessions, scores.columns]):
        if not np.isfinite(frame.to_numpy()).all():
            raise ValueError("nonfinite replay matrix")
    snapshots: list[dict[str, Any]] = []
    _simulate_portfolio(scores, prices, qqq, sessions, top_k, friction,
                        liquidate_at_end=True, ledger=snapshots)
    return ledger_tables(snapshots, signal_sessions=signal_sessions or
                         {s: s for s in sessions}, mode=mode)


def summarize_ledger(daily: pd.DataFrame, assets: pd.DataFrame) -> dict:
    nav = np.r_[1.0, daily["nav"].to_numpy()]
    contribution = assets.groupby("symbol")["pnl_nav_units"].sum().sort_values(ascending=False)
    net = float(nav[-1]-1)
    if not np.isclose(contribution.sum(), net, atol=1e-11, rtol=0):
        raise ValueError("asset NAV contributions do not telescope")
    positive = contribution.clip(lower=0)
    qqq = float(np.prod(1+daily["qqq"].to_numpy())-1)
    return {
        "sessions": len(daily), "net_return": net, "qqq_return": qqq,
        "net_excess": net-qqq, "max_drawdown": float(np.min(nav/np.maximum.accumulate(nav)-1)),
        "turnover": float(daily["turnover"].sum()),
        "cost_loss_cumulative": float(daily["gross_nav"].iloc[-1]-nav[-1]),
        "cost_debits_nav_units": float((daily["nav_before"]*daily["cost_return"]).sum()),
        "asset_pnl_nav_units": {k: float(v) for k, v in contribution.items()},
        "top5_positive_pnl_share": float(positive.nlargest(5).sum()/positive.sum()) if positive.sum() else None,
        "max_held_weight": float(daily["max_held_weight"].max()),
        "max_drifted_weight": float(daily["max_drifted_weight"].max()),
        "mean_held_hhi": float(daily["held_hhi"].mean()),
        "mean_new_names_per_day": float(daily["full_replacements"].iloc[1:].mean()),
        "research_only": True, "trade_ready": False, "pit_certified": False,
    }
