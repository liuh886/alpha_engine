"""SGOV defensive-asset challengers for the frozen v4.2 state trace."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import (
    StrategyResult,
    _normalise_bars,
    _return_metrics,
)
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

ASSETS = ("QQQI", "QQQ", "TQQQ", "SGOV")
V4_2_KEY = "rotation_vxn_bridge_v4_2_50_50"


def _variant_weights(contract: Mapping[str, Any], variant: str) -> dict[int, dict[str, float]]:
    portfolio = contract["portfolio"]
    if variant not in portfolio:
        raise ValueError(f"unknown portfolio variant: {variant}")
    raw = portfolio[variant]
    output: dict[int, dict[str, float]] = {}
    for state, key in ((0, "state_0"), (1, "state_1"), (2, "state_2")):
        weights = {asset: float(raw[key].get(asset, 0.0)) for asset in ASSETS}
        if any(value < 0.0 for value in weights.values()):
            raise ValueError(f"{variant} state {state} has negative weights")
        if not np.isclose(sum(weights.values()), 1.0):
            raise ValueError(f"{variant} state {state} weights must sum to one")
        output[state] = weights
    return output


def _sgov_return_series(bars: Mapping[str, pd.DataFrame]) -> pd.Series:
    if "SGOV" not in bars:
        raise ValueError("SGOV bars are required")
    sgov = _normalise_bars(bars["SGOV"], "SGOV")
    returns = sgov["open"].shift(-1).div(sgov["open"]).sub(1.0)
    returns.name = "SGOV_next_open_return"
    return returns


def _common_reference_daily(
    v4_2: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    daily = v4_2.daily.join(_sgov_return_series(bars), how="inner")
    return_columns = [f"{asset}_next_open_return" for asset in ASSETS]
    return daily.dropna(subset=return_columns).copy()


def run_state_weight_backtest(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    variant: str,
) -> StrategyResult:
    """Apply one predeclared defensive allocation to the unchanged v4.2 states."""

    daily = reference_daily.copy()
    weights_by_state = _variant_weights(contract, variant)
    weights = pd.DataFrame(0.0, index=daily.index, columns=list(ASSETS))
    for state, state_weights in weights_by_state.items():
        mask = daily["position_state"].astype(int).eq(state)
        for asset, value in state_weights.items():
            weights.loc[mask, asset] = value
            daily[f"weight_{asset}"] = weights[asset]

    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"] for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if bool(contract["portfolio"].get("charge_initial_entry", True)) and len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    elif len(turnover):
        turnover.iloc[0] = 0.0
    cost_bps = float(contract["portfolio"]["transaction_cost_bps_per_turnover_unit"])
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(contract["portfolio"].get("annual_risk_free_rate", 0.0)),
    )
    switches = daily["position_state"].ne(daily["position_state"].shift()).sum() - 1
    metrics.update(
        {
            "strategy": variant,
            "switch_count": int(max(switches, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            **{
                f"average_{asset.lower()}_weight": float(daily[f"weight_{asset}"].mean())
                for asset in ASSETS
            },
        }
    )
    trade_mask = daily["position_state"].ne(daily["position_state"].shift())
    trade_columns = [
        "position_state",
        "position_label",
        "executed_reason",
        *[f"weight_{asset}" for asset in ASSETS],
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[trade_mask, trade_columns].reset_index(names="date")
    return StrategyResult(variant, daily, trades, metrics)


def _chronological_metrics(result: StrategyResult, train_fraction: float) -> list[dict[str, Any]]:
    count = len(result.daily)
    split = min(max(int(count * train_fraction), 1), count - 1)
    rows: list[dict[str, Any]] = []
    for segment, sample in (
        ("early", result.daily.iloc[:split]),
        ("late", result.daily.iloc[split:]),
    ):
        metrics = _return_metrics(sample["net_return"], annual_risk_free_rate=0.0)
        rows.append({"strategy": result.metrics["strategy"], "segment": segment, **metrics})
    return rows


def run_sgov_defense_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    experiment_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame, dict[str, Any]]:
    """Run the two frozen SGOV structures against a common-window v4.2 baseline."""

    _, bridge_results, prepared, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    reference = _common_reference_daily(bridge_results[V4_2_KEY], bars)
    variants = (
        "current_v4_2",
        "sgov_pure_defense",
        "qqqi_sgov_blended_defense",
    )
    results = {
        variant: run_state_weight_backtest(reference, experiment_contract, variant)
        for variant in variants
    }
    baseline_states = results["current_v4_2"].daily["position_state"]
    for key, result in results.items():
        if not baseline_states.equals(result.daily["position_state"]):
            raise AssertionError(f"{key} changed the v4.2 state trace")
        state_two = result.daily.loc[result.daily["position_state"].eq(2)]
        if not (
            np.allclose(state_two["weight_QQQ"], 0.25)
            and np.allclose(state_two["weight_TQQQ"], 0.75)
            and np.allclose(state_two["weight_QQQI"], 0.0)
            and np.allclose(state_two["weight_SGOV"], 0.0)
        ):
            raise AssertionError(f"{key} changed the frozen state-2 allocation")

    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    tail = {key: tail_risk_metrics(result) for key, result in results.items()}
    train_fraction = float(experiment_contract["validation"]["chronological_train_fraction"])
    chronological = pd.DataFrame(
        [
            row
            for result in results.values()
            for row in _chronological_metrics(result, train_fraction)
        ]
    )
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "same_state_trace_every_session": True,
        "same_state_2_allocation": True,
        "cost_bps_per_turnover_unit": float(
            experiment_contract["portfolio"]["transaction_cost_bps_per_turnover_unit"]
        ),
        "common_sample_start": reference.index.min().date().isoformat(),
        "common_sample_end": reference.index.max().date().isoformat(),
        "observations": int(len(reference)),
        "tail_risk": tail,
        "chronological_metrics": chronological.to_dict(orient="records"),
    }
    return headline.sort_index(), results, chronological, diagnostics
