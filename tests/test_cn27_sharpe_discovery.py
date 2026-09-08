from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.cn27_sharpe_discovery import (
    DiscoveryBacktestResult,
    _capped_inverse_volatility_weights,
    _select_screen_candidate,
    _select_target_weights,
    compute_discovery_features,
    factor_rank_ic_diagnostics,
    load_discovery_contract,
    run_discovery_recipe,
)


SPEC = Path("configs/research_experiments/cn_27_sharpe_1_discovery_v1.yaml")


def _bars(periods: int = 170) -> pd.DataFrame:
    contract = load_discovery_contract(SPEC)
    dates = pd.bdate_range("2023-05-01", periods=periods)
    rows = []
    for symbol_index, symbol in enumerate(contract.candidate_symbols):
        trend = 0.03 + symbol_index * 0.001
        close = 20.0 + np.arange(periods) * trend + np.sin(np.arange(periods) / 7.0)
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close[index] - 0.02,
                    "high": close[index] + 0.10,
                    "low": close[index] - 0.10,
                    "close": close[index],
                    "volume": 1_000_000 + symbol_index * 10_000 + index * 100,
                }
            )
    return pd.DataFrame(rows)


def _bars_with_references(periods: int = 60) -> pd.DataFrame:
    contract = load_discovery_contract(SPEC)
    bars = _bars(periods)
    dates = pd.bdate_range("2023-05-01", periods=periods)
    rows = []
    for symbol, trend in [
        (contract.defensive_symbol, 0.01),
        (contract.market_reference_symbol, 0.02),
    ]:
        close = 10.0 + np.arange(periods) * trend
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close[index],
                    "high": close[index] + 0.05,
                    "low": close[index] - 0.05,
                    "close": close[index],
                    "volume": 5_000_000,
                }
            )
    return pd.concat([bars, pd.DataFrame(rows)], ignore_index=True)


def test_discovery_contract_is_hash_bound_and_role_separated() -> None:
    contract = load_discovery_contract(SPEC)

    assert len(contract.candidate_symbols) == 27
    assert contract.defensive_symbol == "515180"
    assert contract.market_reference_symbol == "000300"
    assert contract.defensive_symbol not in contract.candidate_symbols
    assert contract.market_reference_symbol not in contract.candidate_symbols
    assert contract.spec["windows"]["locked_test_may_enter_selection"] is False


def test_discovery_features_use_trailing_values_and_delayed_open_label() -> None:
    contract = load_discovery_contract(SPEC)
    bars = _bars()
    features = compute_discovery_features(bars, contract)
    symbol = contract.candidate_symbols[0]
    raw = bars.loc[bars["symbol"].eq(symbol)].set_index("date")
    observed = features.loc[features["symbol"].eq(symbol)].set_index("date")
    date = observed.index[130]

    assert np.isclose(observed.loc[date, "momentum_20"], raw["close"].pct_change(20).loc[date])
    assert np.isclose(
        observed.loc[date, "slope_20_10"],
        raw["close"].rolling(20).mean().pct_change(10).loc[date],
    )
    expected_forward = raw["open"].iloc[141] / raw["open"].iloc[131] - 1.0
    assert np.isclose(observed.loc[date, "forward_return_10"], expected_forward)


def test_future_prices_cannot_rewrite_prior_signal_features() -> None:
    contract = load_discovery_contract(SPEC)
    bars = _bars()
    cutoff = pd.Timestamp("2023-10-13")
    before = compute_discovery_features(bars, contract)
    changed = bars.copy()
    changed.loc[changed["date"] > cutoff, ["open", "high", "low", "close"]] *= 5.0
    after = compute_discovery_features(changed, contract)
    signal_columns = [
        "momentum_20",
        "momentum_60",
        "trend_60",
        "slope_20_10",
        "low_volatility_20",
        "risk_adjusted_momentum_20",
    ]

    pd.testing.assert_frame_equal(
        before.loc[before["date"] <= cutoff, signal_columns].reset_index(drop=True),
        after.loc[after["date"] <= cutoff, signal_columns].reset_index(drop=True),
    )


def test_factor_screen_does_not_emit_locked_test_rows() -> None:
    contract = load_discovery_contract(SPEC)
    diagnostics = factor_rank_ic_diagnostics(compute_discovery_features(_bars(), contract), contract)

    assert set(diagnostics["window"]) == {"development", "selection_validation"}
    assert "locked_test" not in set(diagnostics["window"])
    assert len(diagnostics) == 32


def test_rank_buffer_retains_existing_name_without_breaking_sector_cap() -> None:
    cross_section = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "composite_score": [0.9, 0.8, 0.7, 0.6, 0.5],
            "volatility_20": [0.2] * 5,
            "momentum_60": [0.1] * 5,
        }
    )
    recipe = {
        "top_k": 3,
        "exit_rank_buffer": 2,
        "maximum_names_per_sector": 2,
        "weighting": "equal",
        "absolute_momentum_filter": "none",
    }
    weights = _select_target_weights(
        cross_section,
        recipe,
        {"D"},
        {"A": "x", "B": "x", "C": "x", "D": "y", "E": "y"},
        equity_exposure=0.75,
        maximum_single_weight=0.30,
    )

    assert set(weights) == {"A", "B", "D"}
    assert np.isclose(sum(weights.values()), 0.75)


def test_inverse_volatility_weights_respect_cap_and_exposure() -> None:
    weights = _capped_inverse_volatility_weights(
        ["A", "B", "C"],
        {"A": 0.01, "B": 0.20, "C": 0.30},
        exposure=0.45,
        cap=0.20,
    )

    assert np.isclose(sum(weights.values()), 0.45)
    assert max(weights.values()) <= 0.20 + 1e-12
    assert weights["A"] == 0.20


def test_scheduled_recipe_does_not_rebalance_targets_daily() -> None:
    contract = load_discovery_contract(SPEC)
    bars = _bars_with_references()
    dates = pd.bdate_range("2023-05-01", periods=60)
    spec = copy.deepcopy(contract.spec)
    spec["windows"]["development"] = {
        "start": dates[0].date().isoformat(),
        "end": dates[-1].date().isoformat(),
        "sessions": len(dates),
    }
    contract = replace(contract, spec=spec)
    features = compute_discovery_features(bars, contract)
    recipe = copy.deepcopy(spec["candidate_recipes"][0])
    result = run_discovery_recipe(
        bars,
        features,
        contract,
        recipe,
        end_date=dates[-1].date().isoformat(),
        window_names=("development",),
    )

    assert len(result.daily) == 60
    assert result.daily["one_way_turnover"].gt(0.0).sum() <= 3
    assert np.isclose(
        result.daily[["equity_exposure", "etf_weight", "cash_weight"]].sum(axis=1),
        1.0,
    ).all()


def test_screen_selection_maximizes_worst_window_without_locked_test() -> None:
    contract = load_discovery_contract(SPEC)

    def result(recipe_id: str, development: float, validation: float) -> DiscoveryBacktestResult:
        return DiscoveryBacktestResult(
            recipe_id=recipe_id,
            daily=pd.DataFrame(),
            metrics_by_window={
                "development": {
                    "sharpe_log_excess": development,
                    "annual_one_way_turnover": 2.0,
                    "maximum_drawdown": -0.20,
                },
                "selection_validation": {
                    "sharpe_log_excess": validation,
                    "annual_one_way_turnover": 2.0,
                    "maximum_drawdown": -0.20,
                },
            },
        )

    summary, selection = _select_screen_candidate(
        [
            result("c1_balanced_momentum_lowvol", 0.80, 0.70),
            result("c2_risk_adjusted_momentum", 1.20, 0.20),
        ],
        contract,
    )

    assert selection["selected_recipe_id"] == "c1_balanced_momentum_lowvol"
    assert selection["locked_test_metrics_observed"] is False
    assert summary.iloc[0]["selection_gate_passed"]
