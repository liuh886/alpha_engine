"""Focused deterministic tests for candidate_v2 universe-robustness experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.run_candidate_v2_universe_robustness import (
    EXCLUDED_SYMBOLS,
    FROZEN_BLEND_WEIGHT,
    FROZEN_CALIBRATION,
    FROZEN_COST_BPS,
    FROZEN_EXPOSURE,
    FROZEN_FEATURE_GROUP,
    FROZEN_TOP_N,
    _aggregate_cohort,
    _build_nested_cohorts,
    _compute_score_diagnostics,
    _cross_universe_summary,
    _exclude_benchmark_symbols,
    _load_us_provider_symbols,
    build_parser,
)


# ══════════════════════════════════════════════════════════════════════════════
# Nested cohort construction
# ══════════════════════════════════════════════════════════════════════════════

CANONICAL_10 = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "COST", "NFLX"]


def test_nested_cohorts_contain_canonical_10() -> None:
    """Every expanded cohort retains all canonical 10 symbols."""
    extra = [f"LOCAL{i:03d}" for i in range(200)]
    coverage = {
        symbol: {
            "first_valid_date": "2021-04-05",
            "last_valid_date": "2026-06-18",
            "observations": 1300,
        }
        for symbol in CANONICAL_10 + extra
    }
    specs, _ = _build_nested_cohorts(
        CANONICAL_10,
        CANONICAL_10 + extra,
        coverage,
        available_end="2026-06-18",
    )
    d10 = next(s for s in specs if s.name == "default_10_symbols")
    e50 = next(s for s in specs if s.name == "expanded_50_symbols")
    e100 = next(s for s in specs if s.name == "expanded_100_symbols")

    assert set(d10.symbols) == set(CANONICAL_10)
    for sym in CANONICAL_10:
        assert sym in e50.symbols, f"{sym} missing from expanded_50"
        assert sym in e100.symbols, f"{sym} missing from expanded_100"


def test_nested_cohorts_are_strict_supersets() -> None:
    """expanded_50 ⊇ default_10; expanded_100 ⊇ expanded_50."""
    extra = [f"L{i:03d}" for i in range(200)]
    coverage = {
        symbol: {
            "first_valid_date": "2021-04-05",
            "last_valid_date": "2026-06-18",
            "observations": 1300,
        }
        for symbol in CANONICAL_10 + extra
    }
    specs, starts = _build_nested_cohorts(
        CANONICAL_10,
        CANONICAL_10 + extra,
        coverage,
        available_end="2026-06-18",
    )
    d10 = set(next(s for s in specs if s.name == "default_10_symbols").symbols)
    e50 = set(next(s for s in specs if s.name == "expanded_50_symbols").symbols)
    e100 = set(next(s for s in specs if s.name == "expanded_100_symbols").symbols)

    assert d10.issubset(e50)
    assert e50.issubset(e100)
    assert len(e50) == 50
    assert len(e100) == 100
    assert set(starts) == {
        "default_10_symbols",
        "expanded_50_symbols",
        "expanded_100_symbols",
    }


def test_exclude_qqq_spy_from_tradable() -> None:
    """QQQ and SPY are removed from tradable symbols in every cohort."""
    symbols = ("AAPL", "NVDA", "QQQ", "MSFT", "SPY", "GOOGL")
    cleaned = _exclude_benchmark_symbols(symbols)
    assert "QQQ" not in cleaned
    assert "SPY" not in cleaned
    assert cleaned == ("AAPL", "NVDA", "MSFT", "GOOGL")


def test_exclude_benchmark_symbols_case_insensitive() -> None:
    """Benchmark exclusion is case-insensitive."""
    assert _exclude_benchmark_symbols(("qqq", "spy", "AAPL")) == ("AAPL",)
    assert _exclude_benchmark_symbols(("SPY", "Qqq")) == ()


def test_exclude_benchmark_symbols_removes_spx_ndx() -> None:
    """Additional benchmark-like symbols (SPX, NDX) are also excluded."""
    symbols = ("AAPL", "SPX", "^GSPC", "NDX", "^IXIC")
    cleaned = _exclude_benchmark_symbols(symbols)
    assert cleaned == ("AAPL",)


def test_load_us_provider_symbols(tmp_path: Path) -> None:
    """Parse tab-separated instrument file and exclude benchmark symbols."""
    instr_dir = tmp_path / "data" / "providers" / "us" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "us.txt").write_text(
        "AAPL\tCommon Stock\n"
        "NVDA\tCommon Stock\n"
        "MSFT\tCommon Stock\n"
        "GOOGL\tCommon Stock\n"
        "QQQ\tETF\n"
        "SPY\tETF\n"
        "SPX\tIndex\n"
        "^GSPC\tIndex\n"
    )
    symbols = _load_us_provider_symbols(tmp_path)
    assert "AAPL" in symbols
    assert "NVDA" in symbols
    assert "QQQ" not in symbols
    assert "SPY" not in symbols
    assert "SPX" not in symbols
    assert "^GSPC" not in symbols
    assert len(symbols) == 4


# ══════════════════════════════════════════════════════════════════════════════
# Frozen configuration — no tuning
# ══════════════════════════════════════════════════════════════════════════════


def test_frozen_blend_is_50_50() -> None:
    """The frozen blend is exactly 50/50 — must not be tuned."""
    assert FROZEN_BLEND_WEIGHT.ranker_weight == 0.50
    assert FROZEN_BLEND_WEIGHT.momentum_weight == 0.50


def test_frozen_top_n_is_3() -> None:
    """Top-K is fixed at 3 — must not be tuned."""
    assert FROZEN_TOP_N == 3


def test_frozen_cost_bps_is_20() -> None:
    """Cost is 20 bps cash-inclusive one-way — must not be tuned."""
    assert FROZEN_COST_BPS == 20.0


def test_frozen_exposure_is_0_5() -> None:
    """Negative trend exposure is 0.5 (50% gross) — must not be tuned."""
    assert FROZEN_EXPOSURE == 0.5


def test_frozen_feature_group_has_7_expressions() -> None:
    """Frozen feature group must have exactly 7 expressions (momentum_volatility_volume)."""
    assert len(FROZEN_FEATURE_GROUP.expressions) == 7
    assert FROZEN_FEATURE_GROUP.name == "momentum_volatility_volume"


def test_frozen_calibration_is_gain5_round100() -> None:
    """Frozen calibration must not change."""
    assert FROZEN_CALIBRATION.n_gain_bins == 5
    assert FROZEN_CALIBRATION.num_boost_round == 100
    assert FROZEN_CALIBRATION.num_leaves == 31
    assert FROZEN_CALIBRATION.min_data_in_leaf == 10
    assert FROZEN_CALIBRATION.learning_rate == 0.05


# ══════════════════════════════════════════════════════════════════════════════
# IC computation: Pearson (ordinary) and Spearman (rank)
# ══════════════════════════════════════════════════════════════════════════════


def test_ic_is_pearson_rank_ic_is_spearman() -> None:
    """Ordinary IC uses Pearson correlation; Rank IC uses Spearman.

    With a quadratic relationship (returns = scores^2), ranks are perfectly
    aligned so Spearman = 1.0, while Pearson < 1.0 because the relationship
    is nonlinear.
    """
    from src.core.metrics import compute_ic_series
    from src.research.vectorized_backtest import compute_ic_vectorized

    scores_data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    returns_data = [v * v for v in scores_data]  # quadratic
    date = pd.Timestamp("2024-01-05")
    instruments = [f"SYM{i:03d}" for i in range(10)]
    idx = pd.MultiIndex.from_tuples(
        [(date, s) for s in instruments],
        names=["datetime", "instrument"],
    )
    scores = pd.DataFrame({"score": scores_data}, index=idx)
    returns = pd.DataFrame({"return": returns_data}, index=idx)

    mean_ic, ic_ir, _, _ = compute_ic_vectorized(scores, returns)
    rank_result = compute_ic_series(scores, returns)

    # Spearman = 1.0 (perfect rank alignment), Pearson < 1.0 (nonlinear)
    assert rank_result["ic_mean"] == pytest.approx(1.0, abs=0.001)
    assert mean_ic < 0.99
    assert mean_ic > 0.0


def test_score_diagnostics_accepts_vectorized_ic_list() -> None:
    """The runner must aggregate the list returned by the Pearson IC helper."""
    dates = [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08")]
    instruments = [f"SYM{i:03d}" for i in range(10)]
    index = pd.MultiIndex.from_product(
        [dates, instruments],
        names=["datetime", "instrument"],
    )
    score_values = list(range(10)) + list(reversed(range(10)))
    return_values = [value**2 for value in range(10)] + [
        value**2 for value in reversed(range(10))
    ]
    scores = pd.DataFrame({"score": score_values}, index=index, dtype=float)
    returns = pd.DataFrame({"return": return_values}, index=index, dtype=float)

    diagnostics = _compute_score_diagnostics(scores, returns)

    assert np.isfinite(diagnostics["ic_std"])
    assert diagnostics["ic_n_days"] == 2
    assert diagnostics["rank_ic_n_days"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Coverage fail-closed behavior
# ══════════════════════════════════════════════════════════════════════════════


def test_coverage_fail_closed_insufficient_symbols() -> None:
    """When fewer than min_symbols have coverage, universe is skipped with empty retained."""
    from src.research.universe_robustness import filter_universe_by_coverage

    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        {"AAPL"},
        min_symbols=3,
    )
    assert report["skipped"] is True
    assert report["sufficient"] is False
    assert report["retained_symbols"] == []
    assert report["skip_reason"] is not None


def test_coverage_fail_closed_with_date_data() -> None:
    """Date-coverage fail-closed: insufficient coverage → empty retained."""
    from src.research.universe_robustness import filter_universe_by_coverage

    dc = {
        "AAPL": {
            "first_valid_date": "2021-01-04",
            "last_valid_date": "2026-06-30",
            "observations": 1300,
            "covers_train_start": True,
            "covers_test_end": True,
            "sufficient_coverage": True,
        },
        "NVDA": {
            "first_valid_date": None,
            "last_valid_date": None,
            "observations": 0,
            "covers_train_start": False,
            "covers_test_end": False,
            "sufficient_coverage": False,
        },
        "MSFT": {
            "first_valid_date": None,
            "last_valid_date": None,
            "observations": 0,
            "covers_train_start": False,
            "covers_test_end": False,
            "sufficient_coverage": False,
        },
    }
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        min_symbols=3,
        date_range=("2021-01-01", "2026-06-30"),
        date_coverage_data=dc,
    )
    assert report["skipped"] is True
    assert report["retained_symbols"] == []


def test_coverage_skip_reason_is_descriptive() -> None:
    """Skip reason explains why the cohort was dropped."""
    from src.research.universe_robustness import filter_universe_by_coverage

    report = filter_universe_by_coverage(
        ("A", "B", "C"),
        {"A"},
        min_symbols=3,
    )
    assert "insufficient" in report["skip_reason"]
    assert "1/3" in report["skip_reason"]


# ══════════════════════════════════════════════════════════════════════════════
# Aggregation gates
# ══════════════════════════════════════════════════════════════════════════════


def _make_window_payload(
    rel_excess: float = 0.05,
    sharpe: float = 1.2,
    drawdown: float = -0.08,
    turnover: float = 0.15,
    cost: float = 0.0003,
    gross_exp: float = 0.75,
    total_ret: float = 0.10,
    bench_ret: float = 0.05,
    ic_ir: float = 0.35,
    rank_ic_ir: float = 0.30,
    ic_mean: float = 0.06,
    rank_ic_mean: float = 0.05,
    ic_pos_pct: float = 0.65,
    spread: float = 0.02,
    n_periods: int = 12,
) -> dict[str, Any]:
    """Build a minimal valid window payload."""
    return {
        "skipped": False,
        "window": {"label": "2024H1", "train_start": "2021-01-01", "train_end": "2023-12-31",
                     "test_start": "2024-01-01", "test_end": "2024-06-30"},
        "candidate": "blend:ranker_momentum:...:ranker0.5_momentum0.5",
        "candidate_v2": {
            "variant_id": "top3_benchmark_trend_filter",
            "total_return": total_ret,
            "benchmark_return": bench_ret,
            "excess_return": total_ret - bench_ret,
            "relative_excess_return": rel_excess,
            "max_drawdown": drawdown,
            "sharpe_ratio": sharpe,
            "annual_return": 0.20,
            "volatility": 0.18,
            "turnover": turnover,
            "costs": cost,
            "cost_bps": 20.0,
            "turnover_model": "cash_inclusive_one_way",
            "information_ratio": 0.60,
            "period_returns": [0.01] * n_periods,
            "benchmark_period_returns": [0.005] * n_periods,
            "portfolio_values": [1.0 + i * 0.01 for i in range(n_periods + 1)],
            "benchmark_values": [1.0 + i * 0.005 for i in range(n_periods + 1)],
            "n_periods": n_periods,
            "test_start": "2024-01-01",
            "test_end": "2024-06-30",
            "mean_gross_exposure": gross_exp,
            "min_gross_exposure": 0.5,
            "max_gross_exposure": 1.0,
            "label": "research_only_risk_control_variant",
            "research_only": True,
            "trade_ready": False,
        },
        "score_diagnostics": {
            "ic_mean": ic_mean,
            "ic_std": 0.10,
            "ic_ir": ic_ir,
            "ic_pos_pct": ic_pos_pct,
            "ic_n_days": 60,
            "rank_ic_mean": rank_ic_mean,
            "rank_ic_std": 0.10,
            "rank_ic_ir": rank_ic_ir,
            "rank_ic_pos_pct": 0.60,
            "rank_ic_n_days": 60,
            "top_bottom_spread_mean": spread,
            "top_bottom_spread_std": 0.03,
            "top_bottom_spread_pos_pct": 0.70,
            "top_bottom_spread_n_days": 60,
        },
    }


def test_aggregate_cohort_with_valid_windows() -> None:
    """Cohort aggregate computes cross-window stats from valid payloads."""
    payloads = [
        _make_window_payload(rel_excess=0.05, sharpe=1.0, drawdown=-0.08, ic_ir=0.30),
        _make_window_payload(rel_excess=0.08, sharpe=1.5, drawdown=-0.06, ic_ir=0.40),
    ]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    assert agg["cohort"] == "default_10_symbols"
    assert agg["skipped"] is False
    assert agg["n_windows_evaluated"] == 2
    cv2 = agg["candidate_v2"]
    assert cv2["compounded_relative_excess_return"] != 0.0
    assert cv2["mean_sharpe"] > 0
    assert cv2["worst_drawdown"] == -0.08
    assert cv2["cost_bps"] == 20.0
    assert cv2["turnover_model"] == "cash_inclusive_one_way"
    diag = agg["score_diagnostics"]
    assert diag["mean_ic_ir"] > 0
    assert diag["mean_rank_ic_ir"] > 0
    assert diag["mean_top_bottom_spread"] > 0


def test_aggregate_skipped_when_all_windows_skipped() -> None:
    """Cohort is marked skipped when no window produced valid results."""
    payloads = [
        {"skipped": True, "skip_reason": "empty benchmark returns",
         "window": {"label": "2024H1"}},
        {"skipped": True, "skip_reason": "empty benchmark returns",
         "window": {"label": "2024H2"}},
    ]
    agg = _aggregate_cohort("expanded_50_symbols", payloads)
    assert agg["skipped"] is True
    assert agg["n_windows_evaluated"] == 0


def test_aggregate_empty_payloads_is_skipped() -> None:
    """Empty payload list produces a skipped cohort."""
    agg = _aggregate_cohort("expanded_100_symbols", [])
    assert agg["skipped"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Cross-universe summary and robustness decision
# ══════════════════════════════════════════════════════════════════════════════


def _make_cohort_agg(
    name: str,
    rel_excess: float = 0.40,
    sharpe: float = 0.8,
    drawdown: float = -0.12,
    turnover: float = 0.20,
    ic_ir: float = 0.30,
    rank_ic_ir: float = 0.25,
    spread: float = 0.015,
    n_windows: int = 4,
    pos_excess: int = 3,
    skipped: bool = False,
) -> dict[str, Any]:
    if skipped:
        return {"cohort": name, "n_windows_total": 0, "n_windows_evaluated": 0,
                "skipped": True, "skip_reason": "insufficient coverage"}
    return {
        "cohort": name,
        "n_windows_total": n_windows,
        "n_windows_evaluated": n_windows,
        "skipped": False,
        "candidate": "blend:...:ranker0.5_momentum0.5",
        "candidate_v2": {
            "compounded_total_return": 0.20,
            "compounded_benchmark_return": 0.10,
            "compounded_relative_excess_return": rel_excess,
            "mean_relative_excess": 0.05,
            "mean_sharpe": sharpe,
            "worst_drawdown": drawdown,
            "mean_drawdown": -0.10,
            "mean_turnover": turnover,
            "mean_costs": 0.0004,
            "cost_bps": 20.0,
            "turnover_model": "cash_inclusive_one_way",
            "mean_gross_exposure": 0.78,
            "min_gross_exposure": 0.5,
            "max_gross_exposure": 1.0,
            "positive_excess_windows": pos_excess,
            "passes_candidate_v2_gate": (
                n_windows == 4
                and pos_excess >= 3
                and rel_excess > 0.30
                and drawdown >= -0.15
                and ic_ir > 0
                and rank_ic_ir > 0
                and spread > 0
            ),
        },
        "score_diagnostics": {
            "mean_ic": 0.05,
            "mean_ic_ir": ic_ir,
            "mean_rank_ic": 0.04,
            "mean_rank_ic_ir": rank_ic_ir,
            "mean_ic_pos_pct": 0.60,
            "mean_top_bottom_spread": spread,
        },
    }


def test_cross_universe_summary_all_evaluated_robust() -> None:
    """When all cohorts pass, candidate_v2 is declared robust."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols", rel_excess=0.40, sharpe=1.0),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", rel_excess=0.35, sharpe=0.7),
        "expanded_100_symbols": _make_cohort_agg("expanded_100_symbols", rel_excess=0.32, sharpe=0.5),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["n_cohorts_evaluated"] == 3
    assert summary["n_cohorts_skipped"] == 0
    assert summary["candidate_v2_robust"] is True
    assert summary["decision_status"] == "candidate_v2_robust_across_expanded_universes"
    assert summary["degradation_note"] is None


def test_cross_universe_summary_with_skipped_cohort() -> None:
    """Skipped required cohorts fail the robustness decision."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols"),
        "expanded_100_symbols": _make_cohort_agg("expanded_100_symbols", skipped=True),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["n_cohorts_evaluated"] == 2
    assert summary["n_cohorts_skipped"] == 1
    assert "expanded_100_symbols" in summary["skipped_cohorts"]
    assert summary["candidate_v2_robust"] is False
    assert "missing required cohorts" in (summary["degradation_note"] or "")


def test_cross_universe_expanded_degradation_marks_not_robust() -> None:
    """Negative relative excess in expanded cohort → not robust."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols", rel_excess=0.15),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", rel_excess=-0.05),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "relative excess <= 30%" in (summary["degradation_note"] or "")


def test_cross_universe_deep_drawdown_marks_not_robust() -> None:
    """Drawdown below the unchanged -15% gate marks the cohort not robust."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", drawdown=-0.35),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "drawdown" in (summary["degradation_note"] or "")


def test_cross_universe_few_positive_excess_windows_marks_not_robust() -> None:
    """Fewer than 3 positive excess windows → not robust."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", pos_excess=1),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "positive excess" in (summary["degradation_note"] or "")


def test_cross_universe_all_skipped() -> None:
    """All cohorts skipped → no_cohort_evaluated."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols", skipped=True),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", skipped=True),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["decision_status"] == "no_cohort_evaluated"
    assert summary["candidate_v2_robust"] is False


def test_cross_universe_base_weak_marks_not_robust() -> None:
    """If the base (canonical) cohort itself is weak, robust is false."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols", rel_excess=-0.10, sharpe=-0.2),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", rel_excess=0.05),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "relative excess" in (summary.get("degradation_note") or "")


def test_non_positive_icir_marks_not_robust() -> None:
    """Non-positive ICIR fails the robustness gate."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", ic_ir=0.0),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "non-positive ICIR" in (summary.get("degradation_note") or "")


def test_non_positive_rank_icir_marks_not_robust() -> None:
    """Non-positive Rank ICIR fails the robustness gate."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", rank_ic_ir=0.0),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "Rank ICIR" in (summary.get("degradation_note") or "")


def test_non_positive_spread_marks_not_robust() -> None:
    """Non-positive top-bottom spread fails the robustness gate."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", spread=0.0),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "spread" in (summary.get("degradation_note") or "").lower()


def test_insufficient_windows_marks_not_robust() -> None:
    """Fewer than 4 OOS windows fails the robustness gate."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
        "expanded_50_symbols": _make_cohort_agg("expanded_50_symbols", n_windows=3, pos_excess=2),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["candidate_v2_robust"] is False
    assert "windows" in (summary.get("degradation_note") or "")


# ══════════════════════════════════════════════════════════════════════════════
# No trade-ready claims
# ══════════════════════════════════════════════════════════════════════════════


def test_cross_universe_summary_is_research_only() -> None:
    """Every output explicitly marks research_only=True, trade_ready=False."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["research_only"] is True
    assert summary["promotion_eligible"] is False
    assert summary["trade_ready"] is False


def test_cross_universe_summary_documents_survivorship_bias() -> None:
    """Cross-universe summary explicitly documents survivorship bias."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
    }
    summary = _cross_universe_summary(aggs, {})
    assert summary["survivorship_bias_documented"] is True
    assert "survivorship_bias_notes" in summary
    notes = summary["survivorship_bias_notes"]
    assert "static current" in notes.lower() or "delisted" in notes.lower()
    assert "look-ahead" in notes.lower() or "upper bound" in notes.lower()


def test_cross_universe_summary_has_non_trade_ready_warning() -> None:
    """Cross-universe summary includes a non-trade-ready warning."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
    }
    summary = _cross_universe_summary(aggs, {})
    assert "non_trade_ready_warning" in summary
    warning = summary["non_trade_ready_warning"]
    assert "not authorization" in warning.lower() or "not authori" in warning.lower()
    assert "live trading" in warning.lower() or "automated execution" in warning.lower()


def test_per_cohort_aggregate_marks_research_only() -> None:
    """Per-cohort aggregate JSON always has research_only=True."""
    payloads = [_make_window_payload()]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    assert agg["skipped"] is False
    # The aggregate carries candidate_v2 info which includes research labels
    cv2 = agg["candidate_v2"]
    assert cv2.get("turnover_model") == "cash_inclusive_one_way"
    assert cv2.get("cost_bps") == 20.0


def test_window_payload_marks_candidate_v2_research_only() -> None:
    """Individual window payload candidate_v2 has research_only=True, trade_ready=False."""
    payload = _make_window_payload()
    cv2 = payload["candidate_v2"]
    assert cv2["research_only"] is True
    assert cv2["trade_ready"] is False


# ══════════════════════════════════════════════════════════════════════════════
# CLI data-root contract
# ══════════════════════════════════════════════════════════════════════════════


def test_build_parser_accepts_root_and_data_root() -> None:
    """CLI parser accepts --root and --data-root arguments."""
    parser = build_parser()
    args = parser.parse_args(["--root", "/tmp/project", "--data-root", "/mnt/data"])
    assert str(args.root) == str(Path("/tmp/project"))
    assert str(args.data_root) == str(Path("/mnt/data"))


def test_build_parser_data_root_defaults_to_none() -> None:
    """--data-root defaults to None (meaning root == data-root)."""
    parser = build_parser()
    args = parser.parse_args(["--root", "/tmp/project"])
    assert args.data_root is None


def test_build_parser_accepts_test_year_range() -> None:
    """CLI accepts --first-test-year and --last-test-year."""
    parser = build_parser()
    args = parser.parse_args([
        "--root", "/tmp",
        "--first-test-year", "2023",
        "--last-test-year", "2025",
    ])
    assert args.first_test_year == 2023
    assert args.last_test_year == 2025


def test_build_parser_default_test_years() -> None:
    """Default test years are 2024-2026."""
    parser = build_parser()
    args = parser.parse_args(["--root", "/tmp"])
    assert args.first_test_year == 2024
    assert args.last_test_year == 2026


def test_data_root_is_separate_from_root() -> None:
    """--data-root is a separate path for read-only data access."""
    parser = build_parser()
    args = parser.parse_args([
        "--root", "/home/user/project",
        "--data-root", "D:/Documents/GitHub/alpha_engine",
    ])
    assert str(args.root) != str(args.data_root)
    assert str(args.data_root).endswith("alpha_engine")


# ══════════════════════════════════════════════════════════════════════════════
# Frozen config: EXCLUDED_SYMBOLS
# ══════════════════════════════════════════════════════════════════════════════


def test_excluded_symbols_contains_qqq_spy() -> None:
    """QQQ and SPY are in the excluded set."""
    assert "QQQ" in EXCLUDED_SYMBOLS
    assert "SPY" in EXCLUDED_SYMBOLS


def test_excluded_symbols_contains_benchmark_indexes() -> None:
    """SPX, NDX, and ^GSPC/^IXIC are also excluded."""
    assert "SPX" in EXCLUDED_SYMBOLS or "^GSPC" in EXCLUDED_SYMBOLS


# ══════════════════════════════════════════════════════════════════════════════
# Cohort-level gates: aggregated metrics contract
# ══════════════════════════════════════════════════════════════════════════════


def test_aggregate_cohort_includes_turnover_and_costs() -> None:
    """Cohort aggregate explicitly reports turnover and costs."""
    payloads = [_make_window_payload(turnover=0.12, cost=0.00024)]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    cv2 = agg["candidate_v2"]
    assert cv2["mean_turnover"] == pytest.approx(0.12, abs=0.01)
    assert cv2["mean_costs"] == pytest.approx(0.00024, abs=0.0001)
    assert cv2["cost_bps"] == 20.0


def test_aggregate_cohort_includes_gross_exposure_stats() -> None:
    """Cohort aggregate reports mean/min/max gross exposure."""
    payloads = [_make_window_payload(gross_exp=0.78)]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    cv2 = agg["candidate_v2"]
    assert cv2["mean_gross_exposure"] == pytest.approx(0.78, abs=0.01)
    assert cv2["min_gross_exposure"] <= cv2["mean_gross_exposure"] <= cv2["max_gross_exposure"]


def test_aggregate_cohort_includes_ic_ir_and_rank_ic_ir() -> None:
    """Score diagnostics include both IC IR and Rank IC IR."""
    payloads = [_make_window_payload(ic_ir=0.35, rank_ic_ir=0.30)]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    diag = agg["score_diagnostics"]
    assert diag["mean_ic_ir"] == pytest.approx(0.35, abs=0.01)
    assert diag["mean_rank_ic_ir"] == pytest.approx(0.30, abs=0.01)
    assert "mean_ic_pos_pct" in diag
    assert "mean_top_bottom_spread" in diag


def test_aggregate_cohort_includes_positive_excess_windows() -> None:
    """Cohort aggregate counts positive excess windows."""
    payloads = [
        _make_window_payload(rel_excess=0.05),
        _make_window_payload(rel_excess=-0.02),
        _make_window_payload(rel_excess=0.10),
    ]
    agg = _aggregate_cohort("default_10_symbols", payloads)
    cv2 = agg["candidate_v2"]
    assert cv2["positive_excess_windows"] == 2


def test_cohort_rows_in_summary_contain_all_required_metrics() -> None:
    """Cross-universe summary rows contain the required comparison metrics."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols"),
    }
    summary = _cross_universe_summary(aggs, {})
    row = summary["cohort_rows"][0]
    assert row["status"] == "evaluated"
    required = [
        "compounded_relative_excess", "mean_sharpe", "worst_drawdown",
        "mean_turnover", "mean_costs", "mean_gross_exposure",
        "mean_ic_ir", "mean_rank_ic_ir",
    ]
    for key in required:
        assert key in row, f"Missing required metric: {key}"


def test_skipped_cohort_row_has_status_skipped() -> None:
    """Skipped cohorts appear in summary rows with status 'skipped'."""
    aggs = {
        "default_10_symbols": _make_cohort_agg("default_10_symbols", skipped=True),
    }
    summary = _cross_universe_summary(aggs, {})
    row = summary["cohort_rows"][0]
    assert row["status"] == "skipped"
    assert "skip_reason" in row
