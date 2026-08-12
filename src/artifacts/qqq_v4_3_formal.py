"""Build the accepted QQQ Rotation v4.3 formal evidence package.

The formal model is the frozen v4.33 joint portfolio:

- v4.2 state machine;
- v4.27 Panic Repair risk-budget overlay;
- falling-SMA200 strong state-0 defense;
- MA20 + VIX repair release;
- 50% QQQI / 50% SGOV during strong defense.

This module contains only deterministic evidence projection. It does not search
parameters, place orders, or weaken the research-only boundary.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars, _return_metrics
from src.artifacts.performance_semantics import build_performance_semantics

MODEL_ID = "qqqi_qqq_tqqq_v4_3"
DISPLAY_NAME = "QQQ Rotation v4.3"
JOINT_STRATEGY = "v4_33_panic_repair_ma200_ma20_vix_release"
ASSETS = ("QQQI", "QQQ", "TQQQ", "SGOV")


def portfolio_contract() -> dict[str, Any]:
    return {
        "symbols": list(ASSETS),
        "benchmark": "QQQ",
        "cost_bps": 10,
        "signal_time": "session_close_t",
        "execution_time": "next_session_open_t_plus_1",
        "return_measurement": "adjusted_open_to_adjusted_open",
        "formal_state_machine": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "base_state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
        "base_state_1": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
        "base_state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75, "SGOV": 0.0},
        "panic_repair": {
            "rsi_period": 14,
            "rsi_lt": 30.0,
            "fear_greed_lt": 10.0,
            "tqqq_boost": 0.25,
            "activation": "existing_v4_2_repair_confirmation",
            "eligible_formal_states": [0, 1],
            "formal_state_2_unchanged": True,
        },
        "slow_bear_defense": {
            "entry": "existing_SMA200_falling",
            "eligible_formal_state": 0,
            "allocation": {"QQQI": 0.5, "SGOV": 0.5},
            "release": "QQQ_at_or_above_existing_SMA20_AND_VIX_easing_or_normalized",
            "persistence": False,
            "cooldown": False,
        },
    }


def _asset_opens(bars: Mapping[str, pd.DataFrame], index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    output: dict[str, pd.Series] = {}
    for asset in ASSETS:
        if asset not in bars:
            raise ValueError(f"formal v4.3 bars missing {asset}")
        output[asset] = _normalise_bars(bars[asset], asset)["open"].reindex(index)
        if bool(output[asset].isna().any()):
            raise ValueError(f"formal v4.3 {asset} opens do not cover economic window")
    return output


def _weights(daily: pd.DataFrame) -> pd.DataFrame:
    columns = [f"weight_{asset}" for asset in ASSETS]
    missing = sorted(set(columns) - set(daily.columns))
    if missing:
        raise ValueError(f"formal v4.3 result missing weights: {missing}")
    weights = (
        daily[columns].rename(columns={f"weight_{asset}": asset for asset in ASSETS}).astype(float)
    )
    if not np.allclose(weights.sum(axis=1), 1.0, atol=1e-10):
        raise ValueError("formal v4.3 weights do not sum to one")
    if bool((weights < -1e-12).any().any()):
        raise ValueError("formal v4.3 contains negative weight")
    return weights


def _report(daily: pd.DataFrame) -> list[dict[str, Any]]:
    net = daily["net_return"].astype(float)
    benchmark_return = daily["QQQ_next_open_return"].astype(float)
    account = (1.0 + net).cumprod()
    benchmark = (1.0 + benchmark_return).cumprod()
    peak = account.cummax()
    rows: list[dict[str, Any]] = []
    for date, row in daily.iterrows():
        item = {
            "date": pd.Timestamp(date).date().isoformat(),
            "account": float(account.loc[date]),
            "bench_qqq": float(benchmark.loc[date]),
            "bench": float(benchmark_return.loc[date]),
            "turnover": float(row["turnover_units"]),
            "period_return": float(row["net_return"]),
            "gross_return": float(row["gross_return"]),
            "transaction_cost": float(row["transaction_cost"]),
            "position_state": int(row["position_state"]),
            "position_label": str(row.get("position_label", "")),
            "decision_state": int(row.get("decision_state", row["position_state"])),
            "decision_reason": str(row.get("decision_reason", "hold")),
            "executed_reason": str(row.get("executed_reason", "hold")),
            "drawdown": float(account.loc[date] / peak.loc[date] - 1.0),
            "trace_frequency": "daily_open_to_open",
            "panic_repair_active": bool(row.get("panic_repair_active_at_open", False)),
            "slow_bear_defense_active": bool(row.get("ma200_ma20_vix_defense_active", False)),
        }
        for asset in ASSETS:
            item[f"weight_{asset}"] = float(row[f"weight_{asset}"])
        rows.append(item)
    return rows


def _positions(daily: pd.DataFrame, bars: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
    opens = _asset_opens(bars, daily.index)
    rows: list[dict[str, Any]] = []
    for date, row in daily.iterrows():
        for asset in ASSETS:
            weight = float(row[f"weight_{asset}"])
            if weight <= 1e-12:
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "instrument": asset,
                    "weight": weight,
                    "price": float(opens[asset].loc[date]),
                    "position_state": int(row["position_state"]),
                    "position_label": str(row.get("position_label", "")),
                    "executed_reason": str(row.get("executed_reason", "hold")),
                    "panic_repair_active": bool(row.get("panic_repair_active_at_open", False)),
                    "slow_bear_defense_active": bool(
                        row.get("ma200_ma20_vix_defense_active", False)
                    ),
                }
            )
    return rows


def _action(previous: float, target: float) -> str:
    if previous == 0.0 and target > 0.0:
        return "BUY"
    if previous > 0.0 and target == 0.0:
        return "SELL"
    return "INCREASE" if target > previous else "DECREASE"


def _trade_reason(row: pd.Series) -> str:
    if bool(row.get("ma200_ma20_vix_defense_active", False)):
        return "ma200_slow_bear_defense"
    if bool(row.get("panic_repair_active_at_open", False)):
        return "panic_repair_risk_budget"
    return str(row.get("executed_reason", "rebalance"))


def _trades(daily: pd.DataFrame) -> list[dict[str, Any]]:
    weights = _weights(daily)
    previous = pd.Series(0.0, index=list(ASSETS), dtype=float)
    rows: list[dict[str, Any]] = []
    for date, target in weights.iterrows():
        changes = (target - previous).astype(float)
        absolute = float(changes.abs().sum())
        if absolute <= 1e-15:
            previous = target
            continue
        row = daily.loc[date]
        total_cost = float(row["transaction_cost"])
        for asset, delta in changes.items():
            if abs(float(delta)) <= 1e-15:
                continue
            old = float(previous[asset])
            new = float(target[asset])
            rows.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "instrument": asset,
                    "action": _action(old, new),
                    "previous_weight": old,
                    "target_weight": new,
                    "weight_delta": float(delta),
                    "transaction_cost": total_cost * abs(float(delta)) / absolute,
                    "reason": _trade_reason(row),
                    "position_state": int(row["position_state"]),
                    "position_label": str(row.get("position_label", "")),
                    "vix_close": float(row["vix_close"]),
                    "vix_regime": str(row.get("vix_regime", "")),
                    "vxn_close": float(row["vxn_close"]),
                    "vxn_regime": str(row.get("vxn_regime", "")),
                }
            )
        previous = target
    return rows


def _attribution(daily: pd.DataFrame) -> list[dict[str, Any]]:
    weights = _weights(daily)
    previous = pd.Series(0.0, index=list(ASSETS), dtype=float)
    contribution = {asset: 0.0 for asset in ASSETS}
    for date, row in daily.iterrows():
        current = weights.loc[date]
        for asset in ASSETS:
            contribution[asset] += float(current[asset]) * float(row[f"{asset}_next_open_return"])
        changes = (current - previous).abs()
        denominator = float(changes.sum())
        if denominator:
            for asset in ASSETS:
                contribution[asset] -= (
                    float(row["transaction_cost"]) * float(changes[asset]) / denominator
                )
        previous = current
    return [
        {
            "instrument": asset,
            "name": asset,
            "value": float(contribution[asset]),
            "semantics": "arithmetic daily contribution less allocated transition cost",
        }
        for asset in ASSETS
    ]


def _window_summary(result: StrategyResult) -> list[dict[str, Any]]:
    daily = result.daily
    split = max(1, min(len(daily) - 1, int(len(daily) * 0.60)))
    windows = (
        ("full", daily),
        ("early_60pct", daily.iloc[:split]),
        ("late_40pct", daily.iloc[split:]),
    )
    rows: list[dict[str, Any]] = []
    for label, sample in windows:
        metrics = _return_metrics(sample["net_return"].astype(float), annual_risk_free_rate=0.0)
        rows.append(
            {
                "window": label,
                "start": sample.index.min().date().isoformat(),
                "end": sample.index.max().date().isoformat(),
                "observations": int(len(sample)),
                "total_return": float(metrics["total_return"]),
                "cagr": float(metrics["cagr"]),
                "annual_volatility": float(metrics["annual_volatility"]),
                "sharpe": float(metrics["sharpe"]),
                "sortino": float(metrics["sortino"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "calmar": float(metrics["calmar"]),
            }
        )
    return rows


def build_formal_package(
    result: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
    *,
    generated_at: str,
    evidence_cutoff: str,
    backtest_id: str,
    evidence: Mapping[str, Any],
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one already-evaluated v4.3 result into formal v1 evidence."""
    if str(result.metrics.get("strategy")) != JOINT_STRATEGY:
        raise ValueError("formal v4.3 package requires the frozen v4.33 joint result")
    daily = result.daily.copy()
    daily.index = pd.to_datetime(daily.index).tz_localize(None).normalize()
    if daily.empty or daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
        raise ValueError("formal v4.3 daily trace is invalid")
    _weights(daily)
    benchmark_return = daily["QQQ_next_open_return"].astype(float)
    benchmark_total = float((1.0 + benchmark_return).prod() - 1.0)
    metrics = result.metrics
    package_freshness = dict(freshness or {})
    if not package_freshness:
        package_freshness = {
            "status": "current",
            "required_cutoff": evidence_cutoff,
            "latest_completed_session": evidence_cutoff,
            "latest_realized_holding_end": daily.index.max().date().isoformat(),
            "model_selection_reopened": False,
            "research_only": True,
            "trade_ready": False,
        }
    return {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "model_id": MODEL_ID,
        "display_name": DISPLAY_NAME,
        "market": "us",
        "benchmark": "QQQ",
        "publication_status": "accepted_formal_baseline",
        "backtest_id": backtest_id,
        "generated_at": generated_at,
        "evidence_cutoff": evidence_cutoff,
        "date_range": {
            "start": daily.index.min().date().isoformat(),
            "end": daily.index.max().date().isoformat(),
        },
        "trace_frequency": "daily_open_to_open",
        "portfolio_contract": portfolio_contract(),
        "performance_semantics": build_performance_semantics(
            portfolio_contract(), trace_frequency="daily_open_to_open"
        ),
        "metrics": {
            "Total Return": float(metrics["total_return"]),
            "Benchmark Return": benchmark_total,
            "CAGR": float(metrics["cagr"]),
            "Annualized Volatility": float(metrics["annual_volatility"]),
            "Sharpe Ratio": float(metrics["sharpe"]),
            "Sortino Ratio": float(metrics["sortino"]),
            "Max Drawdown": float(metrics["max_drawdown"]),
            "Calmar Ratio": float(metrics["calmar"]),
            "Turnover": float(metrics["turnover_units"]),
            "Transaction Cost": float(metrics["transaction_cost_paid"]),
        },
        "report": _report(daily),
        "positions": _positions(daily, bars),
        "trades": _trades(daily),
        "attribution": _attribution(daily),
        "window_summary": _window_summary(result),
        "evidence": dict(evidence),
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_daily_trace",
            "holdings": "retained_exact_daily_weights",
            "trades": "retained_exact",
            "attribution": "derived_exact_from_retained_daily_components",
            "missing": [],
        },
        "interpretation_notes": [
            "Formal v4.3 is the v4.33 joint risk-budget architecture; v4.2 is superseded as the active QQQ formal baseline.",
            "The fresh promotion rerun improved all headline metrics in the actual QQQI/SGOV product window.",
            "The 2010+ QQQ/BIL mechanism proxy improved maximum drawdown and Calmar but sacrificed CAGR; the failed pre-registered proxy-CAGR/early-Calmar gate remains disclosed.",
            "research_only=true; trade_ready=false; no broker execution is authorized.",
        ],
        "freshness": package_freshness,
        "research_only": True,
        "trade_ready": False,
    }
