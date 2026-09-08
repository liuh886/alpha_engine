from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.research.cn27_sharpe_discovery import DiscoveryBacktestResult
from src.research.cn27_v1_3 import (
    load_v1_3_discovery_contract,
    run_v1_3_discovery_recipe,
)
from src.research.cn27_v1_3_staggered import (
    combine_sleeve_results,
    load_staggered_discovery_contract,
    run_staggered_recipe,
)
from src.research.cn27_v1_2 import compute_v1_2_features


SPEC = "configs/research_experiments/cn_27_v1_3_concentration_discovery_v1.yaml"
STAGGERED_SPEC = "configs/research_experiments/cn_27_v1_3_staggered_sleeve_discovery_v1.yaml"


def _result(contract, returns: list[float], symbol: str) -> DiscoveryBacktestResult:
    dates = pd.date_range("2024-01-01", periods=len(returns), freq="D")
    equity = pd.Series(returns, index=dates).add(1.0).cumprod()
    daily = pd.DataFrame(
        {
            "gross_return": returns,
            "transaction_cost": 0.0,
            "net_return": returns,
            "equity": equity,
            "one_way_turnover": 0.0,
            "return_weights": [json.dumps({symbol: 1.0})] * len(dates),
            "asset_weights": [json.dumps({symbol: 1.0})] * len(dates),
            "target_drift_due_to_trade_lock": 0.0,
            "pending_execution": False,
        },
        index=dates,
    )
    return DiscoveryBacktestResult("sleeve", daily, {})


def test_staggered_sleeve_accounting_compounds_capital_and_weights() -> None:
    contract = load_v1_3_discovery_contract(SPEC)
    first, second = contract.candidate_symbols[:2]
    combined = combine_sleeve_results(
        [_result(contract, [0.10, 0.0], first), _result(contract, [0.0, 0.20], second)],
        contract,
        recipe_id="test",
        compute_metrics=False,
    )

    assert np.isclose(combined.daily.iloc[-1]["equity"], 1.15)
    assert np.isclose(combined.daily.iloc[0]["net_return"], 0.05)
    end_weights = json.loads(combined.daily.iloc[-1]["asset_weights"])
    assert np.isclose(sum(end_weights.values()), 1.0)
    assert end_weights[second] > end_weights[first]


def test_staggered_contract_is_frozen_and_single_sleeve_matches_direct_path() -> None:
    contract = load_staggered_discovery_contract(STAGGERED_SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    recipe = contract.spec["candidate_recipes"][0]
    constraint = {
        **contract.spec["frozen_constraint_recipes"]["g1"],
        "id": str(recipe["id"]),
    }
    direct = run_v1_3_discovery_recipe(bars, features, contract, constraint)
    staggered = run_staggered_recipe(bars, features, contract, recipe)

    assert np.allclose(staggered.daily["net_return"], direct.daily["net_return"], atol=1e-12)
