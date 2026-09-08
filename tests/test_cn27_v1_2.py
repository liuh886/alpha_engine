from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.cn27_sharpe_discovery import (
    compute_discovery_features,
    load_discovery_contract,
)
from src.research.cn27_v1_2 import (
    compute_v1_2_features,
    execute_target_with_deferral,
    load_v1_2_contract,
    load_v1_3_contract,
    run_robustness_recipe,
    score_v1_2_features,
    v1_2_factor_diagnostics,
)


SPEC = "configs/research_experiments/cn_27_sharpe_1_discovery_v1.yaml"
V12_SPEC = "configs/research_experiments/cn_27_v1_2_robustness_discovery_v1.yaml"
V13_SPEC = "configs/research_experiments/cn_27_v1_3_stability_discovery_v1.yaml"


def test_locked_target_difference_is_retried_when_tradability_returns() -> None:
    candidates = ("A", "B")
    target = {"A": 0.5, "B": 0.25, "ETF": 0.25, "CASH": 0.0}
    before = {"A": 0.0, "B": 0.0, "ETF": 1.0, "CASH": 0.0}
    costs = {
        "stock_buy_rate": 0.0005,
        "stock_sell_rate": 0.0010,
        "etf_buy_rate": 0.0002,
        "etf_sell_rate": 0.0002,
    }

    locked, _, _, pending, drift = execute_target_with_deferral(
        before,
        target,
        {"A": False, "B": True, "ETF": True},
        candidate_symbols=candidates,
        defensive_symbol="ETF",
        cost_spec=costs,
    )

    assert locked["A"] == 0.0
    assert pending is True
    assert drift > 0.0

    completed, _, _, pending, drift = execute_target_with_deferral(
        locked,
        target,
        {"A": True, "B": True, "ETF": True},
        candidate_symbols=candidates,
        defensive_symbol="ETF",
        cost_spec=costs,
    )

    assert np.isclose(completed["A"], 0.5)
    assert np.isclose(completed["B"], 0.25)
    assert np.isclose(completed["ETF"], 0.25)
    assert pending is False
    assert drift < 1e-12


def test_frozen_v1_1_recipe_retries_historical_trade_locks() -> None:
    contract = load_discovery_contract(SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_discovery_features(bars, contract)
    recipe = next(
        row for row in contract.spec["candidate_recipes"] if row["id"] == "c2_risk_adjusted_momentum"
    )
    result = run_robustness_recipe(
        bars,
        features,
        contract,
        recipe,
        end_date="2026-09-04",
        window_names=("development", "selection_validation", "locked_test"),
    )

    pending = result.daily["pending_execution"].astype(bool)
    episode_starts = pending & ~pending.shift(1, fill_value=False)

    assert int(episode_starts.sum()) == 3
    assert int(result.daily["target_drift_due_to_trade_lock"].gt(1e-12).sum()) == 6
    assert not bool(pending.iloc[-1])


def test_v1_2_features_are_trailing_only_and_diagnostics_cover_six_folds() -> None:
    contract = load_v1_2_contract(V12_SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    cutoff = pd.Timestamp("2025-03-12")
    full = compute_v1_2_features(bars, contract)
    truncated = compute_v1_2_features(bars.loc[bars["date"].le(cutoff)], contract)
    factor_ids = [row["id"] for row in contract.spec["factor_diagnostics"]["factors"]]
    common_full = full.loc[full["date"].le(cutoff), ["date", "symbol", *factor_ids]]
    common_truncated = truncated[["date", "symbol", *factor_ids]]

    pd.testing.assert_frame_equal(
        common_full.reset_index(drop=True),
        common_truncated.reset_index(drop=True),
    )
    diagnostics = v1_2_factor_diagnostics(full, contract)
    assert len(diagnostics) == len(factor_ids) * 6
    assert set(diagnostics["fold"]) == {"f1", "f2", "f3", "f4", "f5", "f6"}
    assert int(diagnostics["observations"].max()) < 122


def test_dynamic_factor_weights_use_only_available_labels() -> None:
    contract = load_v1_2_contract(V12_SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    cutoff = pd.Timestamp("2025-03-12")
    recipe = next(
        row for row in contract.spec["candidate_recipes"] if row["id"] == "r7_dynamic_ic20"
    )
    full = compute_v1_2_features(bars, contract)
    truncated = compute_v1_2_features(bars.loc[bars["date"].le(cutoff)], contract)
    _, full_weights = score_v1_2_features(full, recipe, contract)
    _, truncated_weights = score_v1_2_features(truncated, recipe, contract)

    assert full_weights is not None
    assert truncated_weights is not None
    pd.testing.assert_frame_equal(
        full_weights.loc[:cutoff],
        truncated_weights.loc[:cutoff],
    )
    assert np.allclose(full_weights.sum(axis=1), 1.0)
    assert float(full_weights.max().max()) <= 0.25 + 1e-12


def test_v1_3_stability_contract_is_bound_to_v1_2_evidence() -> None:
    contract = load_v1_3_contract(V13_SPEC)

    assert contract.spec["iteration_semantics"]["fresh_confirmation_claim_allowed"] is False
    assert len(contract.spec["candidate_recipes"]) == 7
    assert contract.spec["selection_gate"]["minimum_stable_selected_factor_share"] == 0.75
