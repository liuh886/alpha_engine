"""Contracts for the single-window Top-3 objective holdout."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.run_candidate_v2_top3_holdout_evidence import (
    HOLDOUT_LABEL,
    build_holdout_comparison,
    latest_complete_forward_return_date,
)


def _payload(
    *,
    candidate: str,
    relative_excess: float,
    drawdown: float,
    top3_spread: float,
    positive_top3: float,
    periods: int = 11,
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "ranker_contract": {"mode": candidate},
        "candidate_v2": {
            "total_return": relative_excess + 0.1,
            "benchmark_return": 0.1,
            "relative_excess_return": relative_excess,
            "sharpe_ratio": 1.0,
            "max_drawdown": drawdown,
            "turnover": 8.0,
            "costs": 0.016,
        },
        "score_diagnostics": {
            "ic_mean": 0.01,
            "ic_ir": 0.1,
            "rank_ic_mean": 0.02,
            "rank_ic_ir": 0.2,
            "top_bottom_spread_mean": 0.003,
        },
        "selection_tail_diagnostics": {
            "aggregate": {
                "n_periods": periods,
                "mean_spread": top3_spread,
                "positive_spread_ratio": positive_top3,
                "mean_selected_realized_percentile": 0.55,
            }
        },
    }


def test_latest_complete_forward_return_date_requires_every_symbol() -> None:
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"]),
            ["A", "B", "QQQ"],
        ],
        names=["datetime", "instrument"],
    )
    raw = pd.DataFrame(
        {
            "return": [
                0.1,
                0.2,
                0.3,
                0.1,
                0.2,
                0.3,
                0.1,
                np.nan,
                0.3,
            ]
        },
        index=index,
    )

    result = latest_complete_forward_return_date(
        raw,
        required_symbols=["A", "B", "QQQ"],
    )

    assert result == pd.Timestamp("2026-06-09")


def test_holdout_comparison_can_support_but_never_promote() -> None:
    frozen = _payload(
        candidate="frozen_gain5",
        relative_excess=-0.05,
        drawdown=-0.12,
        top3_spread=-0.01,
        positive_top3=0.45,
    )
    aligned = _payload(
        candidate="top3_binary_trunc6",
        relative_excess=0.08,
        drawdown=-0.10,
        top3_spread=0.02,
        positive_top3=0.64,
    )

    comparison = build_holdout_comparison(frozen, aligned)

    assert comparison["holdout_label"] == HOLDOUT_LABEL
    assert comparison["hypothesis_supported_on_single_holdout"] is True
    assert comparison["decision"] == (
        "top3_alignment_supported_on_single_holdout_not_promotable"
    )
    assert comparison["single_window_only"] is True
    assert comparison["promotion_eligible"] is False
    assert comparison["trade_ready"] is False


def test_holdout_comparison_refutes_negative_excess_despite_tail_improvement() -> None:
    frozen = _payload(
        candidate="frozen_gain5",
        relative_excess=-0.10,
        drawdown=-0.12,
        top3_spread=-0.02,
        positive_top3=0.36,
    )
    aligned = _payload(
        candidate="top3_binary_trunc6",
        relative_excess=-0.02,
        drawdown=-0.11,
        top3_spread=0.01,
        positive_top3=0.64,
    )

    comparison = build_holdout_comparison(frozen, aligned)

    assert comparison["checks"]["relative_excess_improved_vs_frozen"] is True
    assert comparison["checks"]["positive_relative_excess_vs_qqq"] is False
    assert comparison["hypothesis_supported_on_single_holdout"] is False
    assert "positive_relative_excess_vs_qqq" in comparison["failed_checks"]
    assert comparison["decision"] == "top3_alignment_not_supported_on_holdout"


def test_holdout_comparison_requires_identical_period_counts() -> None:
    frozen = _payload(
        candidate="frozen_gain5",
        relative_excess=0.0,
        drawdown=-0.1,
        top3_spread=0.0,
        positive_top3=0.5,
        periods=11,
    )
    aligned = _payload(
        candidate="top3_binary_trunc6",
        relative_excess=0.0,
        drawdown=-0.1,
        top3_spread=0.0,
        positive_top3=0.5,
        periods=10,
    )

    with pytest.raises(ValueError, match="identical rebalance periods"):
        build_holdout_comparison(frozen, aligned)
