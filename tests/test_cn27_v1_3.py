from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.cn27_v1_3 import (
    concentration_audit,
    concentration_governed_unit_weights,
    concentration_metrics,
    constrained_portfolio_target_weights,
    load_v1_3_discovery_contract,
    run_v1_3_discovery_recipe,
)
from src.research.cn27_v1_2 import compute_v1_2_features


SPEC = "configs/research_experiments/cn_27_v1_3_concentration_discovery_v1.yaml"


def test_v1_3_discovery_contract_is_frozen_and_bound_to_v1_4_evidence() -> None:
    contract = load_v1_3_discovery_contract(SPEC)

    assert contract.spec["fresh_historical_holdout"] is False
    assert contract.spec["objective"]["signal_frozen"] is True
    assert len(contract.spec["candidate_recipes"]) == 6


def test_concentration_governance_uses_largest_feasible_minimum_variance_blend() -> None:
    minimum_variance = pd.Series({"A": 0.55, "B": 0.25, "C": 0.10, "D": 0.10})
    diversified = pd.Series({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    sectors = {"A": "x", "B": "x", "C": "y", "D": "z"}

    weights, diagnostics = concentration_governed_unit_weights(
        minimum_variance,
        diversified,
        sectors,
        maximum_single_share=0.35,
        maximum_sector_share=0.55,
        minimum_effective_names=3.2,
        blend_step=0.1,
    )

    assert np.isclose(weights.sum(), 1.0)
    assert diagnostics["maximum_single_share"] <= 0.35
    assert diagnostics["maximum_sector_share"] <= 0.55
    assert diagnostics["effective_names"] >= 3.2
    assert diagnostics["minimum_variance_blend"] > 0.0


def test_constrained_target_respects_sleeve_and_absolute_caps() -> None:
    symbols = list("ABCDE")
    covariance = pd.DataFrame(
        np.diag([0.01, 0.02, 0.03, 0.04, 0.05]),
        index=symbols,
        columns=symbols,
    )
    sectors = {"A": "x", "B": "x", "C": "y", "D": "z", "E": "w"}
    recipe = {
        "concentration_governance": True,
        "maximum_single_equity_sleeve_share": 0.30,
        "maximum_sector_equity_sleeve_share": 0.45,
        "minimum_effective_names": 4.0,
        "minimum_variance_blend_step": 0.05,
    }

    weights, diagnostics = constrained_portfolio_target_weights(
        symbols,
        covariance,
        sectors,
        recipe,
        reference_exposure=0.60,
        minimum_exposure=0.25,
        maximum_exposure=0.75,
        maximum_single_absolute_weight=0.18,
    )

    assert np.isclose(sum(weights.values()), 0.60)
    assert max(weights.values()) <= 0.18 + 1e-12
    realized = concentration_metrics(weights, sectors)
    assert realized["maximum_single_share"] <= 0.30 + 1e-12
    assert realized["maximum_sector_share"] <= 0.45 + 1e-12
    assert realized["effective_names"] >= 4.0
    assert diagnostics["minimum_variance_blend"] <= 1.0


def test_unconstrained_control_reproduces_v1_4_selected_path() -> None:
    contract = load_v1_3_discovery_contract(SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    result = run_v1_3_discovery_recipe(
        bars, features, contract, contract.spec["candidate_recipes"][0]
    )
    frozen = pd.read_csv(
        "artifacts/evidence/cn_27_v1_4_risk_overlay_discovery_v1/selected_daily.csv",
        parse_dates=["date"],
    ).set_index("date")

    assert np.allclose(result.daily["net_return"], frozen["net_return"], atol=1e-12)


def test_concentration_audit_reports_post_drift_sleeve_metrics() -> None:
    contract = load_v1_3_discovery_contract(SPEC)
    daily = pd.DataFrame(
        {
            "asset_weights": [
                '{"002463": 0.3, "688183": 0.2, "601899": 0.1, "515180": 0.4}'
            ]
        },
        index=pd.DatetimeIndex(["2026-01-01"], name="date"),
    )

    audit, summary = concentration_audit(daily, contract)

    assert np.isclose(audit.iloc[0]["maximum_sector_share"], 5.0 / 6.0)
    assert np.isclose(summary["maximum_post_drift_single_equity_sleeve_share"], 0.5)
    assert np.isclose(audit.iloc[0]["effective_names"], 18.0 / 7.0)
