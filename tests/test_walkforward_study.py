"""Tests for Walk-Forward quantitative investment research pipeline.

Governed under Track B (#1296) and ADR-0005.
Verifies:
1. Multi-fold Walk-Forward execution across US tech candidates.
2. End-to-end determinism and cryptographic study hash immutability.
3. Fail-closed lookahead cutoff boundary interception.
4. Governance invariants: research_only=true, trade_ready=false, trade_signal=false,
   and zero duplicate databases or background processes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.research.walkforward.contracts import (
    WalkForwardConfig,
    WalkForwardFold,
)
from src.research.walkforward.pipeline import (
    DEFAULT_WALK_FORWARD_CONFIG,
    evaluate_walkforward_fold,
    run_walkforward_study,
)

ROOT = Path(__file__).resolve().parents[1]


def test_walkforward_study_happy_path() -> None:
    """Executes the complete default 3-fold Walk-Forward study and verifies metrics."""
    result = run_walkforward_study(root=ROOT)

    # 1. Study-level metadata and invariants
    assert result.study_id == "us_tech_vol_reversal_v1"
    assert result.market == "us"
    assert result.pool_id == "us_selected_equities_v2"
    assert result.benchmark == "QQQ"
    assert result.research_only is True
    assert result.trade_ready is False
    assert result.trade_signal is False

    # 2. Folds verification
    assert len(result.folds) == 3
    fold_ids = [f.fold_id for f in result.folds]
    assert fold_ids == ["fold_1_2025h1", "fold_2_2025h2", "fold_3_2026_tail"]

    for fold in result.folds:
        assert fold.status == "ready"
        assert fold.train_row_count > 0
        assert fold.test_row_count > 0
        assert len(fold.train_data_hash) == 64
        assert len(fold.test_data_hash) == 64
        assert fold.annualized_volatility > 0.0
        assert fold.turnover_ratio > 0.0
        assert fold.research_only is True
        assert fold.trade_ready is False

    # 3. Overall performance validation
    assert isinstance(result.overall_oos_cumulative_return, float)
    assert isinstance(result.overall_benchmark_cumulative_return, float)
    assert isinstance(result.overall_oos_excess_return, float)
    assert isinstance(result.overall_oos_sharpe_ratio, float)
    assert isinstance(result.overall_oos_max_drawdown, float)
    assert len(result.study_hash) == 64


def test_walkforward_study_determinism() -> None:
    """Proves that repeated study execution generates identical cryptographic digests."""
    res1 = run_walkforward_study(root=ROOT)
    res2 = run_walkforward_study(root=ROOT)

    assert res1.study_hash == res2.study_hash
    assert res1.overall_oos_cumulative_return == res2.overall_oos_cumulative_return
    assert res1.overall_benchmark_cumulative_return == res2.overall_benchmark_cumulative_return
    assert res1.overall_oos_sharpe_ratio == res2.overall_oos_sharpe_ratio

    for f1, f2 in zip(res1.folds, res2.folds, strict=True):
        assert f1.fold_id == f2.fold_id
        assert f1.train_data_hash == f2.train_data_hash
        assert f1.test_data_hash == f2.test_data_hash
        assert f1.out_of_sample_cumulative_return == f2.out_of_sample_cumulative_return
        assert f1.sharpe_ratio == f2.sharpe_ratio


def test_walkforward_fail_closed_lookahead_violation() -> None:
    """Verifies that an Out-of-Sample fold with test_end > test_cutoff fails closed."""
    violated_fold = WalkForwardFold(
        fold_id="fold_lookahead_violation",
        train_start="2022-01-03",
        train_end="2024-12-31",
        train_cutoff="2024-12-31",
        test_start="2025-01-02",
        test_end="2025-07-15",
        test_cutoff="2025-06-30",  # Cutoff is prior to test_end!
    )

    result = evaluate_walkforward_fold(violated_fold, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)
    assert result.status == "blocked"
    assert result.out_of_sample_cumulative_return == 0.0
    assert result.test_data_hash == ""
    assert result.test_row_count == 0


def test_walkforward_unlisted_symbol_blocked() -> None:
    """Verifies that a fold requesting an unlisted/unregistered candidate fails closed."""
    invalid_config = WalkForwardConfig(
        study_id="invalid_symbol_study",
        hypothesis_name="Invalid Symbol Test",
        hypothesis_description="Tests invalid symbol handling",
        market="us",
        pool_id="us_selected_equities_v2",
        symbols=("AAPL", "NONEXISTENT_TICKER_999"),
        benchmark="QQQ",
        price_mode="anchored_adjusted",
        folds=DEFAULT_WALK_FORWARD_CONFIG.folds[:1],
    )

    result = evaluate_walkforward_fold(invalid_config.folds[0], invalid_config, root=ROOT)
    assert result.status == "blocked"
    assert result.out_of_sample_cumulative_return == 0.0


def test_walkforward_governance_invariants() -> None:
    """Asserts that running walkforward creates zero secondary databases and enforces safety."""
    study = run_walkforward_study(root=ROOT)
    study_dict = study.to_dict()

    # Verify dictionary serialization preserves research boundaries
    assert study_dict["research_only"] is True
    assert study_dict["trade_ready"] is False
    assert study_dict["trade_signal"] is False

    # Check that no new auxiliary SQLite/DuckDB databases were spawned
    db_candidates = (
        list(ROOT.glob("*.db"))
        + list((ROOT / "data").glob("*.db"))
        + list(ROOT.glob("*.duckdb"))
        + list(ROOT.glob("*.sqlite"))
    )
    assert len(db_candidates) == 0, f"Unexpected secondary database generated: {db_candidates}"
