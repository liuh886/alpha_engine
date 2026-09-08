from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_v1_4 import (
    load_v1_4_contract,
    portfolio_target_weights,
    run_risk_overlay_recipe,
    shrink_covariance,
    unit_risk_weights,
)
from src.research.cn27_v1_2 import compute_v1_2_features


SPEC = "configs/research_experiments/cn_27_v1_4_risk_overlay_discovery_v1.yaml"


def test_v1_4_contract_is_frozen_and_bound_to_v1_2() -> None:
    contract = load_v1_4_contract(SPEC)

    assert contract.spec["fresh_historical_holdout"] is False
    assert contract.spec["objective"]["signal_frozen"] is True
    assert len(contract.spec["candidate_recipes"]) == 6


def test_shrink_covariance_preserves_variance_and_reduces_cross_covariance() -> None:
    returns = pd.DataFrame({"A": [0.01, -0.01, 0.02], "B": [0.02, -0.02, 0.01]})
    raw = returns.cov(ddof=0)
    shrunk = shrink_covariance(returns, 0.5)

    assert np.allclose(np.diag(raw), np.diag(shrunk))
    assert np.isclose(shrunk.loc["A", "B"], raw.loc["A", "B"] * 0.5)


def test_sector_equal_weights_equalize_sector_budgets() -> None:
    covariance = pd.DataFrame(np.diag([0.01, 0.04, 0.09]), index=list("ABC"), columns=list("ABC"))
    sectors = {"A": "x", "B": "x", "C": "y"}
    weights = unit_risk_weights(list("ABC"), covariance, sectors, "sector_equal_inverse_volatility")

    assert np.isclose(weights.loc[["A", "B"]].sum(), 0.5)
    assert np.isclose(weights.loc["C"], 0.5)
    assert np.isclose(weights.sum(), 1.0)


def test_portfolio_volatility_target_is_capped_and_fully_accounted() -> None:
    covariance = pd.DataFrame(np.diag([0.04 / 252, 0.09 / 252]), index=["A", "B"], columns=["A", "B"])
    recipe = {
        "weighting": "inverse_volatility",
        "exposure_policy": "portfolio_volatility_target",
        "portfolio_target_annual_volatility": 0.18,
    }
    weights = portfolio_target_weights(
        ["A", "B"],
        covariance,
        {"A": "x", "B": "y"},
        recipe,
        reference_exposure=0.75,
        minimum_exposure=0.25,
        maximum_exposure=0.75,
        maximum_single_weight=0.40,
    )

    assert np.isclose(sum(weights.values()), 0.75)
    assert max(weights.values()) <= 0.40 + 1e-12


def test_v1_4_control_reproduces_frozen_v1_2_daily_returns() -> None:
    contract = load_v1_4_contract(SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    recipe = contract.spec["candidate_recipes"][0]
    result = run_risk_overlay_recipe(bars, features, contract, recipe)
    frozen = pd.read_csv(
        "artifacts/evidence/cn_27_v1_2/daily.csv", parse_dates=["date"]
    ).set_index("date")

    assert np.allclose(result.daily["net_return"], frozen["net_return"], atol=1e-12)


def test_v1_4_evidence_is_hash_bound_and_research_only() -> None:
    evidence = "artifacts/evidence/cn_27_v1_4_risk_overlay_discovery_v1"
    manifest_path = f"{evidence}/evidence_manifest.json"
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())
    body = dict(manifest)
    identity = body.pop("manifest_identity_sha256")

    assert canonical_sha256(body) == identity
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False
    assert manifest["decision"] == "retrospective_risk_overlay_candidate_identified"
    for name, expected in manifest["outputs"].items():
        assert sha256_file(f"{evidence}/{name}") == expected
