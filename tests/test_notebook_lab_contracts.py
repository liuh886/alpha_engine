from __future__ import annotations

import pandas as pd

from src.research.notebook_lab_contracts import ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name
from src.research.risk_controlled_momentum import (
    build_risk_controlled_momentum_grid,
    build_volatility_adjusted_momentum,
)
from src.research.ten_day_model_gates import evaluate_model_gates


def test_research_session_config_defaults_to_fixed_10d() -> None:
    cfg = ResearchSessionConfig(
        market="us",
        symbols=["S0"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-05",
    )
    assert cfg.holding_days == 10
    assert cfg.rebalance_days == 10
    assert cfg.topk == 15


def test_sanitize_factor_name_matches_training_notebook_convention() -> None:
    assert sanitize_factor_name("close/Ref(close,10)-1") == "close_d_Ref_close_10-1"


def test_model_gate_blocks_low_icir_and_large_drawdown() -> None:
    gate = evaluate_model_gates(
        {
            "icir": 0.12,
            "rank_ic": 0.03,
            "positive_ic_ratio": 0.60,
            "sharpe": 1.2,
            "max_drawdown": -0.30,
            "score_direction": {
                "top_minus_bottom_spread": 0.01,
                "recommendation": "keep_score",
            },
        }
    )
    assert gate["ready_for_trade_guidance"] is False
    assert gate["failed_gates"] == ["icir", "drawdown"]


def test_volatility_adjusted_momentum_marks_high_risk_score_missing() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01"]), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    momentum = pd.DataFrame({"value": [0.04, 0.03, 0.02, 0.01]}, index=index)
    volatility = pd.DataFrame({"value": [0.10, 0.20, 0.30, 10.00]}, index=index)

    scores = build_volatility_adjusted_momentum(momentum, volatility, max_volatility_quantile=0.75)

    assert list(scores.columns) == ["score"]
    assert pd.isna(scores.loc[(pd.Timestamp("2025-01-01"), "D"), "score"])
    assert scores.attrs["provenance"] == "risk_controlled_momentum_score"


def test_risk_controlled_momentum_grid_builds_named_candidates() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01"]), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    momentum = pd.DataFrame({"value": [0.04, 0.03, 0.02, 0.01]}, index=index)
    volatility = pd.DataFrame({"value": [0.10, 0.20, 0.30, 10.00]}, index=index)

    grid = build_risk_controlled_momentum_grid(momentum, volatility, volatility_quantiles=(0.5, 0.75))

    assert list(grid) == [
        "factor:risk_controlled_momentum_volq50",
        "factor:risk_controlled_momentum_volq75",
    ]
    assert all(list(frame.columns) == ["score"] for frame in grid.values())
