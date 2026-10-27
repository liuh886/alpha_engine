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

import numpy as np
import pandas as pd
import pytest

from src.research.walkforward.contracts import (
    WalkForwardConfig,
    WalkForwardFold,
)
from src.research.walkforward.pipeline import (
    DEFAULT_WALK_FORWARD_CONFIG,
    SimulationBlockError,
    _compute_spearman_ic,
    _simulate_portfolio,
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
        assert fold.purged_rows_count > 0
        assert fold.oos_sessions_count > 0
        assert len(fold.daily_net_returns) == fold.oos_sessions_count
        assert "w_rev" in fold.selected_parameters
        assert "w_vol" in fold.selected_parameters
        assert "top_k" in fold.selected_parameters
        assert len(fold.train_data_hash) == 64
        assert len(fold.test_data_hash) == 64
        assert fold.annualized_volatility > 0.0
        assert fold.turnover_ratio > 0.0
        assert fold.research_only is True
        assert fold.trade_ready is False

    # Check exact OOS session counts per fold (zero session dropped across boundaries)
    assert result.folds[0].oos_sessions_count == 122
    assert result.folds[1].oos_sessions_count == 128
    assert result.folds[2].oos_sessions_count == 170

    # 3. Overall performance validation
    assert isinstance(result.overall_oos_cumulative_return, float)
    assert isinstance(result.overall_benchmark_cumulative_return, float)
    assert isinstance(result.overall_oos_excess_return, float)
    assert isinstance(result.overall_oos_sharpe_ratio, float)
    assert isinstance(result.overall_oos_max_drawdown, float)
    assert len(result.study_hash) == 64
    assert result.git_commit != ""
    assert len(result.config_hash) == 64
    assert set(result.code_source_sha256.keys()) == {
        "walkforward_pipeline",
        "walkforward_contracts",
        "research_data_slice",
    }
    assert all(len(h) == 64 for h in result.code_source_sha256.values())
    assert isinstance(result.experiment_receipt, dict)
    assert result.experiment_receipt["study_id"] == "us_tech_vol_reversal_v1"


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
    assert "8_bps_standard" in summary
    assert "15_bps_stress" in summary
    assert "total_cost_drag_bps_8" in summary

    # Monotonic degradation assertion
    assert summary["0_bps_gross"] > summary["8_bps_standard"]
    assert summary["8_bps_standard"] > summary["15_bps_stress"]
    assert summary["total_cost_drag_bps_8"] > 0.0

    # Ensure net return matches standard 8 bps sensitivity
    assert study.overall_oos_net_return == summary["8_bps_standard"]
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


def test_walkforward_portfolio_drift_accounting() -> None:
    """Verifies textbook institutional accounting: initial cash turnover, weight drift, and rebalance friction."""
    sessions = ["2025-01-02", "2025-01-03", "2025-01-06"]

    # Price paths:
    # SYM_A: 100 -> 110 (+10%) -> 121 (+10%)
    # SYM_B: 100 -> 90 (-10%) -> 99 (+10%)
    prices_df = pd.DataFrame(
        {
            "SYM_A": [100.0, 110.0, 121.0],
            "SYM_B": [100.0, 90.0, 99.0],
        },
        index=sessions,
    )

    # Scores:
    # Session 0: A=2.0, B=1.0 -> target: A=1.0, B=0.0 (top_k=1)
    # Session 1: A=1.0, B=2.0 -> target: A=0.0, B=1.0 (top_k=1)
    # Session 2: A=2.0, B=1.0
    scores_df = pd.DataFrame(
        {
            "SYM_A": [2.0, 1.0, 2.0],
            "SYM_B": [1.0, 2.0, 1.0],
        },
        index=sessions,
    )

    bench_series = pd.Series([100.0, 101.0, 102.0], index=sessions)
    friction = 0.0010  # 10 bps

    # 1. With terminal liquidation (default: cash -> equity -> cash)
    gross, net, turnovers, _ = _simulate_portfolio(
        scores=scores_df,
        prices=prices_df,
        bench_series=bench_series,
        sessions=sessions,
        top_k=1,
        friction_per_turnover=friction,
        liquidate_at_end=True,
    )

    assert len(gross) == 2
    assert len(net) == 2
    assert len(turnovers) == 2

    # Day 1:
    # Held A=1.0 over (s0, s1]. Gross ret = 110/100 - 1 = +0.10.
    # Initial turnover from cash = 1.0. Cost drag = 1.0 * 0.0010 = 0.0010.
    # Net ret = 0.10 - 0.0010 = 0.0990.
    assert pytest.approx(gross[0], abs=1e-6) == 0.10
    assert pytest.approx(net[0], abs=1e-6) == 0.0990
    assert pytest.approx(turnovers[0], abs=1e-6) == 1.0

    # Day 2:
    # Held B=1.0 over (s1, s2]. Gross ret = 99/90 - 1 = +0.10.
    # Rebalance friction from day 1 turnover = 1.0 * 0.0010 = 0.0010.
    # Terminal liquidation friction from selling B=1.0 to cash = 1.0 * 0.0010 = 0.0010.
    # Total Day 2 net ret = 0.10 - 0.0010 - 0.0010 = 0.0980.
    # Total Day 2 turnover = 1.0 (rebalance) + 1.0 (terminal liquidation) = 2.0.
    assert pytest.approx(gross[1], abs=1e-6) == 0.10
    assert pytest.approx(net[1], abs=1e-6) == 0.0980
    assert pytest.approx(turnovers[1], abs=1e-6) == 2.0

    # 2. Without terminal liquidation
    _, net_no_liq, turnovers_no_liq, _ = _simulate_portfolio(
        scores=scores_df,
        prices=prices_df,
        bench_series=bench_series,
        sessions=sessions,
        top_k=1,
        friction_per_turnover=friction,
        liquidate_at_end=False,
    )
    assert pytest.approx(net_no_liq[1], abs=1e-6) == 0.0990
    assert pytest.approx(turnovers_no_liq[1], abs=1e-6) == 1.0


def test_walkforward_fail_closed_train_window_shorter_than_purge() -> None:
    """Verifies fail-closed block if train window is shorter than purged_margin_days."""
    short_fold = WalkForwardFold(
        fold_id="fold_short_train",
        train_start="2024-01-02",
        train_end="2024-01-10",  # Only 6 trading sessions
        train_cutoff="2024-01-10",
        test_start="2024-01-11",
        test_end="2024-01-31",
        test_cutoff="2024-01-31",
        purged_margin_days=20,  # 20 > 6!
    )
    res = evaluate_walkforward_fold(short_fold, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)
    assert res.status == "blocked"
    assert any("insufficient_train_sessions_for_purged_margin" in b for b in res.blocked_reasons)


def test_walkforward_fail_closed_missing_candidate_or_benchmark_prices() -> None:
    """Verifies that _simulate_portfolio raises SimulationBlockError upon invalid prices or benchmark."""
    sessions = ["2025-01-02", "2025-01-03"]
    scores_df = pd.DataFrame({"A": [1.0, 1.0], "B": [2.0, 2.0]}, index=sessions)
    bench_ok = pd.Series([100.0, 101.0], index=sessions)

    # 1. Candidate price contains NaN
    bad_prices_nan = pd.DataFrame({"A": [100.0, np.nan], "B": [100.0, 100.0]}, index=sessions)
    with pytest.raises(SimulationBlockError, match="invalid_price_data"):
        _simulate_portfolio(scores_df, bad_prices_nan, bench_ok, sessions, top_k=1, friction_per_turnover=0.0)

    # 2. Benchmark price contains NaN
    good_prices = pd.DataFrame({"A": [100.0, 101.0], "B": [100.0, 102.0]}, index=sessions)
    bad_bench_nan = pd.Series([100.0, np.nan], index=sessions)
    with pytest.raises(SimulationBlockError, match="missing_benchmark_data"):
        _simulate_portfolio(scores_df, good_prices, bad_bench_nan, sessions, top_k=1, friction_per_turnover=0.0)

    # 3. Insufficient candidates for top_k
    bad_scores_nan = pd.DataFrame({"A": [np.nan, np.nan], "B": [np.nan, np.nan]}, index=sessions)
    with pytest.raises(SimulationBlockError, match="insufficient_candidates_for_top_k"):
        _simulate_portfolio(bad_scores_nan, good_prices, bench_ok, sessions, top_k=1, friction_per_turnover=0.0)


def test_walkforward_study_hash_binds_experiment_receipt() -> None:
    """Verifies that changing experiment parameters (e.g. cost_bps) alters the cryptographic study_hash."""
    cfg1 = DEFAULT_WALK_FORWARD_CONFIG
    cfg2 = WalkForwardConfig(
        study_id=cfg1.study_id,
        hypothesis_name=cfg1.hypothesis_name,
        hypothesis_description=cfg1.hypothesis_description,
        market=cfg1.market,
        pool_id=cfg1.pool_id,
        symbols=cfg1.symbols,
        benchmark=cfg1.benchmark,
        price_mode=cfg1.price_mode,
        param_grid=cfg1.param_grid,
        cost_bps=12.0,  # Changed from 3.0
        slippage_bps=cfg1.slippage_bps,
        folds=cfg1.folds,
    )

    # Fold 1 evaluation under both configs
    res1 = run_walkforward_study(cfg1, root=ROOT)
    res2 = run_walkforward_study(cfg2, root=ROOT)

    assert res1.study_hash != res2.study_hash
    assert res1.experiment_receipt["cost_bps"] == 3.0
    assert res2.experiment_receipt["cost_bps"] == 12.0


def test_walkforward_purged_margin_days_zero() -> None:
    """Verifies that purged_margin_days=0 evaluates properly without negative-zero slicing error."""
    fold0 = WalkForwardFold(
        fold_id="fold_zero_purge",
        train_start="2024-01-02",
        train_end="2024-12-31",
        train_cutoff="2024-12-31",
        test_start="2025-01-02",
        test_end="2025-06-30",
        test_cutoff="2025-06-30",
        purged_margin_days=0,
    )
    res = evaluate_walkforward_fold(fold0, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)
    assert res.status == "ready"
    assert res.purged_rows_count == 0
    assert len(res.daily_net_returns) == 122


def test_walkforward_fail_closed_missing_exchange_calendar_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that if market data drops an official exchange trading session, fold fails closed."""
    import src.research.walkforward.pipeline as pipe
    from src.data.research_slice import DataSliceResult

    orig_get_slice = pipe.get_research_data_slice

    def mock_get_slice(req, root=None):
        res = orig_get_slice(req, root=root)
        if res.is_ready and res.data is not None and req.start_date == "2025-01-02":
            # Silently drop session 2025-01-03 from OOS data
            filtered = res.data[res.data["time"] != "2025-01-03"].reset_index(drop=True)
            return DataSliceResult(receipt=res.receipt, data=filtered)
        return res

    monkeypatch.setattr(pipe, "get_research_data_slice", mock_get_slice)
    fold1 = DEFAULT_WALK_FORWARD_CONFIG.folds[0]
    res = evaluate_walkforward_fold(fold1, DEFAULT_WALK_FORWARD_CONFIG, root=ROOT)
    assert res.status == "blocked"
    assert any("missing_or_extra_oos_exchange_sessions" in b for b in res.blocked_reasons)
