"""Tests for Walk-Forward quantitative investment research pipeline.

Governed under Track B (#1296) and ADR-0005.
Verifies:
1. Exact Spearman rank correlation behavior (positive, negative, ties, degenerate constant).
2. Strict fail-closed fold integrity (blocked fold halts overall study publication).
3. Active purged margin execution and in-sample parameter optimization/freezing.
4. Transaction cost, slippage, and turnover drag sensitivity.
5. End-to-end determinism and cryptographic study hash immutability.
6. Governance invariants: research_only=true, trade_ready=false, trade_signal=false,
   and zero duplicate databases or background processes.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pandas as pd

import numpy as np
import pytest

from src.research.walkforward.contracts import (
    WalkForwardConfig,
    WalkForwardFold,
)
from src.research.walkforward.pipeline import (
    DEFAULT_WALK_FORWARD_CONFIG,
    _compute_spearman_ic,
    _simulate_portfolio,
    _study_provenance,
    WalkForwardDataError,
    evaluate_walkforward_fold,
    run_walkforward_study,
)

ROOT = Path(__file__).resolve().parents[1]


def test_compute_spearman_ic_exactness() -> None:
    """Proves Spearman IC calculation formula exactness across standard and degenerate cases."""
    # 1. Perfect positive rank agreement
    pos_x = np.array([1.0, 2.0, 3.0, 4.0])
    pos_y = np.array([10.0, 20.0, 30.0, 40.0])
    assert _compute_spearman_ic(pos_x, pos_y) == pytest.approx(1.0, abs=1e-6)

    # 2. Perfect negative rank agreement
    neg_x = np.array([1.0, 2.0, 3.0, 4.0])
    neg_y = np.array([40.0, 30.0, 20.0, 10.0])
    assert _compute_spearman_ic(neg_x, neg_y) == pytest.approx(-1.0, abs=1e-6)

    # 3. Tied ranks
    tied_x = np.array([1.0, 2.0, 2.0, 3.0])
    tied_y = np.array([10.0, 20.0, 20.0, 30.0])
    assert _compute_spearman_ic(tied_x, tied_y) == pytest.approx(1.0, abs=1e-6)

    # 4. Degenerate constant series (zero variance, must return 0.0 instead of NaN or error)
    const_x = np.array([1.0, 1.0, 1.0, 1.0])
    const_y = np.array([10.0, 20.0, 30.0, 40.0])
    assert _compute_spearman_ic(const_x, const_y) == 0.0

    # 5. Length under 3 or mismatched lengths
    assert _compute_spearman_ic(np.array([1.0, 2.0]), np.array([10.0, 20.0])) == 0.0
    assert _compute_spearman_ic(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0])) == 0.0


def test_walkforward_study_happy_path() -> None:
    """Executes the complete default 3-fold Walk-Forward study and verifies metrics."""
    result = run_walkforward_study(root=ROOT)

    # 1. Study-level metadata and invariants
    assert result.study_id == "us_tech_vol_reversal_v1"
    assert result.status == "ready"
    assert result.blocked_reasons == ()
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
        assert len(fold.daily_sessions) == len(fold.daily_net_returns) == len(fold.daily_benchmark_returns)
        assert len(fold.daily_sessions) == fold.test_row_count // 9
        assert len(set(fold.daily_sessions)) == len(fold.daily_sessions)
        assert fold.train_source_manifest_hashes and fold.test_source_manifest_hashes
        assert fold.purged_rows_count > 0
        assert "w_rev" in fold.selected_parameters
        assert "w_vol" in fold.selected_parameters
        assert "top_k" in fold.selected_parameters
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


def test_walkforward_fail_closed_if_any_fold_blocked() -> None:
    """Verifies fail-closed integrity: if any single fold is blocked, overall study halts."""
    partially_blocked_config = WalkForwardConfig(
        study_id="partially_blocked_study",
        hypothesis_name="Fail Closed Verification",
        hypothesis_description="Tests study-level halt when fold 2 is blocked",
        market="us",
        pool_id="us_selected_equities_v2",
        symbols=("AAPL", "MSFT", "GOOGL"),
        benchmark="QQQ",
        price_mode="anchored_adjusted",
        folds=(
            DEFAULT_WALK_FORWARD_CONFIG.folds[0],
            WalkForwardFold(
                fold_id="fold_2_blocked_by_cutoff",
                train_start="2022-01-03",
                train_end="2025-06-30",
                train_cutoff="2025-06-30",
                test_start="2025-07-01",
                test_end="2025-12-31",
                test_cutoff="2025-06-30",  # Cutoff prior to test_end!
            ),
        ),
    )

    result = run_walkforward_study(partially_blocked_config, root=ROOT)
    assert result.status == "blocked"
    assert len(result.blocked_reasons) > 0
    # Must NOT report partial performance as a valid study
    assert result.overall_oos_gross_return == 0.0
    assert result.overall_oos_net_return == 0.0
    assert result.overall_oos_sharpe_ratio == 0.0
    assert result.overall_oos_max_drawdown == 0.0


def test_walkforward_purged_margin_and_parameter_selection() -> None:
    """Verifies that purged_margin_days prunes training samples and parameters are frozen."""
    fold1 = DEFAULT_WALK_FORWARD_CONFIG.folds[0]
    res = evaluate_walkforward_fold(fold1, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)

    assert res.status == "ready"
    assert res.purged_rows_count == 180  # 20 trading sessions * 9 symbols (8 cands + 1 bench)
    assert res.selected_parameters["w_rev"] in (0.5, 1.0, 1.5)
    assert res.selected_parameters["w_vol"] in (0.5, 1.0, 1.5)
    assert res.selected_parameters["top_k"] in (2, 3)
    assert res.in_sample_best_sharpe > 0.0


def test_walkforward_cost_sensitivity_and_net_return() -> None:
    """Verifies that transaction friction monotonically reduces net returns across cost tiers."""
    study = run_walkforward_study(root=ROOT)
    assert study.status == "ready"

    summary = study.cost_sensitivity_summary
    assert "0_bps_gross" in summary
    assert "standard_config" in summary
    assert "15_bps_stress" in summary
    assert "total_cost_drag_standard" in summary

    # Monotonic degradation assertion
    assert summary["0_bps_gross"] > summary["standard_config"]
    assert summary["standard_config"] > summary["15_bps_stress"]
    assert summary["total_cost_drag_standard"] > 0.0

    # Ensure net return matches standard 8 bps sensitivity
    assert study.overall_oos_net_return == summary["standard_config"]
    assert study.overall_oos_gross_return == summary["0_bps_gross"]


def test_walkforward_study_determinism() -> None:
    """Proves that repeated study execution generates identical cryptographic digests."""
    res1 = run_walkforward_study(root=ROOT)
    res2 = run_walkforward_study(root=ROOT)

    assert res1.study_hash == res2.study_hash
    assert res1.overall_oos_net_return == res2.overall_oos_net_return
    assert res1.overall_benchmark_cumulative_return == res2.overall_benchmark_cumulative_return
    assert res1.overall_oos_sharpe_ratio == res2.overall_oos_sharpe_ratio

    for f1, f2 in zip(res1.folds, res2.folds, strict=True):
        assert f1.fold_id == f2.fold_id
        assert f1.train_data_hash == f2.train_data_hash
        assert f1.test_data_hash == f2.test_data_hash
        assert f1.selected_parameters == f2.selected_parameters
        assert f1.out_of_sample_net_return == f2.out_of_sample_net_return
        assert f1.sharpe_ratio == f2.sharpe_ratio


def test_walkforward_pit_limitations_and_governance() -> None:
    """Verifies PIT limitation disclosures, research exclusivity, and zero secondary databases."""
    study = run_walkforward_study(root=ROOT)

    # Disclosures assertion
    limitations = list(study.pit_limitations)
    assert any("Observation cutoff boundary verified" in s for s in limitations)
    assert any("pit_certified: false" in s for s in limitations)
    assert any("Candidate pool (8 equities) is fixed ex-post" in s for s in limitations)
    assert any("survivorship/selection bias acknowledged" in s for s in limitations)

    # Invariants assertion
    study_dict = study.to_dict()
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


def test_simulation_covers_first_oos_session_using_prior_train_anchor() -> None:
    """Both pre-OOS closes are anchors; every OOS session must generate a return."""
    sessions = ["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"]
    scores = pd.DataFrame({"A": [4.0, 4.0, 1.0, 1.0], "B": [1.0, 1.0, 4.0, 4.0]}, index=sessions)
    prices = pd.DataFrame({"A": [100.0, 100.0, 110.0, 121.0], "B": [100.0] * 4}, index=sessions)
    benchmark = pd.Series([100.0, 100.0, 105.0, 110.25], index=sessions)
    gross, net, turns, bench = _simulate_portfolio(
        scores, prices, benchmark, sessions, top_k=1,
        friction_per_turnover=0.001, liquidate_at_end=False,
    )
    assert len(net) == 2 == len(bench)
    assert gross[0] == pytest.approx(0.1)
    assert net[0] == pytest.approx(0.099)
    assert bench[0] == pytest.approx(0.05)
    assert turns[0] == pytest.approx(1.0)
    assert gross[1] == pytest.approx(0.1)
    # Score at 2024-12-31, not 2025-01-02, selects day-2 holdings.
    assert turns[1] == pytest.approx(0.0)


def test_simulation_rejects_missing_benchmark_candidate_and_signals() -> None:
    sessions = ["2024-12-30", "2024-12-31", "2025-01-02"]
    scores = pd.DataFrame({"A": [1.0] * 3, "B": [2.0] * 3}, index=sessions)
    prices = pd.DataFrame({"A": [100.0] * 3, "B": [100.0] * 3}, index=sessions)
    benchmark = pd.Series([100.0] * 3, index=sessions)
    bad_benchmark = benchmark.copy()
    bad_benchmark.iloc[-1] = np.nan
    with pytest.raises(WalkForwardDataError, match="missing_or_invalid_candidate_or_benchmark_price"):
        _simulate_portfolio(scores, prices, bad_benchmark, sessions, 1, 0.0008)
    bad_prices = prices.copy()
    bad_prices.iloc[-1, 0] = np.nan
    with pytest.raises(WalkForwardDataError, match="missing_or_invalid_candidate_or_benchmark_price"):
        _simulate_portfolio(scores, bad_prices, benchmark, sessions, 1, 0.0008)
    bad_scores = scores.copy()
    bad_scores.iloc[0] = np.nan
    with pytest.raises(WalkForwardDataError, match="insufficient_ranked_candidates"):
        _simulate_portfolio(bad_scores, prices, benchmark, sessions, 1, 0.0008)


def test_turnover_accounts_for_weight_drift_and_end_liquidation() -> None:
    sessions = ["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"]
    scores = pd.DataFrame({"A": [2.0] * 4, "B": [1.0] * 4}, index=sessions)
    prices = pd.DataFrame({"A": [100, 100, 110, 121], "B": [100] * 4}, index=sessions)
    benchmark = pd.Series([100] * 4, index=sessions)
    _, net_no_liquidation, turnover_no_liquidation, _ = _simulate_portfolio(
        scores, prices, benchmark, sessions, 2, 0.001, liquidate_at_end=False
    )
    assert turnover_no_liquidation[0] == pytest.approx(1.0)
    assert turnover_no_liquidation[1] == pytest.approx(0.5 * 1.1 / 1.05 - 0.5)
    _, net_with_liquidation, turnover_with_liquidation, _ = _simulate_portfolio(
        scores, prices, benchmark, sessions, 2, 0.001
    )
    assert turnover_with_liquidation[-1] - turnover_no_liquidation[-1] == pytest.approx(1.0)
    assert net_no_liquidation[-1] - net_with_liquidation[-1] == pytest.approx(0.001)


def test_declared_purge_is_required_or_fold_blocks() -> None:
    fold = replace(DEFAULT_WALK_FORWARD_CONFIG.folds[0], purged_margin_days=100000)
    result = evaluate_walkforward_fold(fold, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)
    assert result.status == "blocked"
    assert "insufficient_training_sessions_for_purge" in result.blocked_reasons[0]


def test_study_config_and_executed_source_are_hash_bound() -> None:
    original = DEFAULT_WALK_FORWARD_CONFIG
    cfg_hash, code = _study_provenance(original)
    assert len(cfg_hash) == 64
    assert set(code) == {"walkforward_pipeline", "walkforward_contracts", "research_data_slice"}
    assert all(len(h) == 64 for h in code.values())
    altered = replace(original, cost_bps=original.cost_bps + 1)
    other_hash, other_code = _study_provenance(altered)
    assert other_hash != cfg_hash
    assert other_code == code
    study = run_walkforward_study(original, root=ROOT)
    assert study.config_hash == cfg_hash
    assert study.code_source_sha256 == code
    assert study.to_dict()["config_hash"] == cfg_hash
