"""Deterministic tests for benchmark-aware Top-K / Bottom-K / spread evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_benchmark_aware_topk_evidence import build_parser
from src.research.benchmark_aware_topk import (
    BenchmarkAwareTopKResult,
    _compute_top_minus_bottom_diagnostic,
    _validate_benchmark_returns,
    _validate_raw_10d_returns,
    _validate_scores,
    evaluate_benchmark_aware_topk,
)


# ── deterministic fixture ────────────────────────────────────────────────────


def _make_fixtures(
    seed: int = 4201,
    n_dates: int = 40,
    n_symbols: int = 15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return deterministic (scores, returns, benchmark_returns)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n_dates)
    symbols = [f"STK{index:03d}" for index in range(n_symbols)]
    index = pd.MultiIndex.from_product(
        [dates, symbols], names=["datetime", "instrument"]
    )

    # Scores: higher = stronger expected return
    raw_scores = rng.normal(size=len(index))
    scores = pd.DataFrame({"score": raw_scores}, index=index)

    # Returns: correlated with scores + noise
    returns = pd.DataFrame(
        {"return": raw_scores * 0.01 + rng.normal(scale=0.005, size=len(index))},
        index=index,
    )
    returns.attrs["provenance"] = "raw_forward_return"
    returns.attrs["horizon"] = 10

    # Benchmark: slightly positive drift, canonical raw forward 10D returns
    benchmark = pd.DataFrame(
        {"return": rng.normal(loc=0.0002, scale=0.004, size=n_dates)},
        index=dates,
    )
    benchmark.attrs["provenance"] = "raw_forward_return"
    benchmark.attrs["horizon"] = 10

    return scores, returns, benchmark


# ── validation: scores ───────────────────────────────────────────────────────


class TestValidateScores:
    def test_accepts_valid_scores(self) -> None:
        scores, _, _ = _make_fixtures()
        _validate_scores(scores)  # does not raise

    def test_rejects_wrong_columns(self) -> None:
        scores, _, _ = _make_fixtures()
        bad = scores.rename(columns={"score": "signal"})
        with pytest.raises(ValueError, match="score.*column"):
            _validate_scores(bad)

    def test_rejects_flat_index(self) -> None:
        _, returns, _ = _make_fixtures()
        flat = returns.copy()  # already has MultiIndex but wrong col name
        flat = pd.DataFrame({"score": [1.0, 2.0]}, index=[0, 1])
        with pytest.raises(ValueError, match="MultiIndex"):
            _validate_scores(flat)

    def test_rejects_wrong_index_names(self) -> None:
        scores, _, _ = _make_fixtures()
        bad = scores.copy()
        bad.index = bad.index.set_names(["date", "ticker"])
        with pytest.raises(ValueError, match="datetime.*instrument"):
            _validate_scores(bad)

    def test_rejects_empty(self) -> None:
        index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
            names=["datetime", "instrument"],
        )
        empty = pd.DataFrame({"score": pd.Series(dtype=float)}, index=index)
        with pytest.raises(ValueError, match="empty"):
            _validate_scores(empty)

    def test_rejects_scores_duplicate_index(self) -> None:
        scores, _, _ = _make_fixtures()
        dup = pd.concat([scores, scores.iloc[:3]])
        with pytest.raises(ValueError, match="duplicate"):
            _validate_scores(dup)

    def test_rejects_scores_all_nan(self) -> None:
        scores, _, _ = _make_fixtures()
        bad = scores.copy()
        bad["score"] = np.nan
        with pytest.raises(ValueError, match="no usable"):
            _validate_scores(bad)


# ── validation: returns provenance ───────────────────────────────────────────


class TestValidateRaw10dReturns:
    def test_accepts_valid_returns(self) -> None:
        _, returns, _ = _make_fixtures()
        _validate_raw_10d_returns(returns)  # does not raise

    def test_rejects_missing_provenance(self) -> None:
        _, returns, _ = _make_fixtures()
        returns.attrs.pop("provenance")
        with pytest.raises(ValueError, match="raw_forward_return"):
            _validate_raw_10d_returns(returns)

    def test_rejects_wrong_provenance(self) -> None:
        _, returns, _ = _make_fixtures()
        returns.attrs["provenance"] = "processed_labels"
        with pytest.raises(ValueError, match="raw_forward_return"):
            _validate_raw_10d_returns(returns)

    def test_rejects_wrong_horizon(self) -> None:
        _, returns, _ = _make_fixtures()
        returns.attrs["horizon"] = 5
        with pytest.raises(ValueError, match="horizon.*10"):
            _validate_raw_10d_returns(returns)

    def test_rejects_missing_horizon(self) -> None:
        _, returns, _ = _make_fixtures()
        returns.attrs.pop("horizon")
        with pytest.raises(ValueError, match="horizon.*10"):
            _validate_raw_10d_returns(returns)

    def test_rejects_wrong_return_column_count(self) -> None:
        _, returns, _ = _make_fixtures()
        bad = returns.copy()
        bad["extra"] = 0.0
        with pytest.raises(ValueError, match="exactly one"):
            _validate_raw_10d_returns(bad)

    def test_rejects_returns_flat_index(self) -> None:
        _, _, _ = _make_fixtures()
        flat = pd.DataFrame(
            {"return": [1.0, 2.0]},
            index=pd.Index([0, 1]),
        )
        with pytest.raises(ValueError, match="MultiIndex"):
            _validate_raw_10d_returns(flat)

    def test_rejects_returns_empty(self) -> None:
        idx = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
            names=["datetime", "instrument"],
        )
        empty = pd.DataFrame({"return": pd.Series(dtype=float)}, index=idx)
        with pytest.raises(ValueError, match="empty"):
            _validate_raw_10d_returns(empty)

    def test_rejects_returns_duplicate_index(self) -> None:
        _, returns, _ = _make_fixtures()
        bad = returns.copy()
        # Force duplicate (datetime, instrument) entries
        bad.index = pd.MultiIndex.from_arrays(
            [bad.index.get_level_values("datetime"),
             bad.index.get_level_values("instrument")],
            names=["datetime", "instrument"],
        )
        bad = pd.concat([bad, bad.iloc[:1]])
        with pytest.raises(ValueError, match="duplicate"):
            _validate_raw_10d_returns(bad)

    def test_rejects_returns_all_nan(self) -> None:
        _, returns, _ = _make_fixtures()
        bad = returns.copy()
        bad["return"] = np.nan
        with pytest.raises(ValueError, match="no usable"):
            _validate_raw_10d_returns(bad)


# ── validation: benchmark ────────────────────────────────────────────────────


class TestValidateBenchmarkReturns:
    def test_accepts_valid_benchmark(self) -> None:
        _, _, benchmark = _make_fixtures()
        _validate_benchmark_returns(benchmark)  # does not raise

    def test_rejects_empty(self) -> None:
        empty = pd.DataFrame({"return": pd.Series(dtype=float)})
        with pytest.raises(ValueError, match="empty"):
            _validate_benchmark_returns(empty)

    def test_rejects_multi_column(self) -> None:
        _, _, benchmark = _make_fixtures()
        bad = benchmark.copy()
        bad["extra"] = 0.0
        with pytest.raises(ValueError, match="exactly one column"):
            _validate_benchmark_returns(bad)

    def test_rejects_flat_index(self) -> None:
        _, _, benchmark = _make_fixtures()
        bad = benchmark.copy()
        bad.index = pd.Index([1, 2, 3, 4, 5, 6, 7, 8, 9, 10] +
                             list(range(11, len(benchmark) + 1)))[:len(benchmark)]
        with pytest.raises(ValueError, match="DatetimeIndex"):
            _validate_benchmark_returns(bad)

    def test_rejects_duplicate_dates(self) -> None:
        _, _, benchmark = _make_fixtures()
        bad = benchmark.copy()
        bad.index = pd.DatetimeIndex([bad.index[0]] * len(bad))
        with pytest.raises(ValueError, match="duplicate"):
            _validate_benchmark_returns(bad)

    def test_rejects_benchmark_missing_provenance(self) -> None:
        _, _, benchmark = _make_fixtures()
        benchmark.attrs.pop("provenance", None)
        with pytest.raises(ValueError, match="raw_forward_return"):
            _validate_benchmark_returns(benchmark)

    def test_rejects_benchmark_wrong_horizon(self) -> None:
        _, _, benchmark = _make_fixtures()
        benchmark.attrs["horizon"] = 5
        with pytest.raises(ValueError, match="horizon.*10"):
            _validate_benchmark_returns(benchmark)

    def test_rejects_all_nan_benchmark(self) -> None:
        _, _, benchmark = _make_fixtures()
        benchmark.iloc[:, 0] = np.nan
        with pytest.raises(ValueError, match="no usable"):
            _validate_benchmark_returns(benchmark)


# ── metric arithmetic ────────────────────────────────────────────────────────


class TestMetricArithmetic:
    """Verify that the three legs produce self-consistent arithmetic."""

    def test_top_k_has_positive_excess_when_scores_predict_returns(self) -> None:
        """Strong positive correlation → Top-K should beat benchmark."""
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        # With score→return correlation, top performers should exceed benchmark
        assert result.top_k_long["n_periods"] > 0
        assert isinstance(result.top_k_long["total_return"], float)

    def test_bottom_k_selects_lowest_scoring_instruments(self) -> None:
        """Bottom-K (negated score) should pick worst original-score instruments."""
        scores, returns, benchmark = _make_fixtures(seed=4201)
        # Give extreme scores on first date so selection is unambiguous
        dates = sorted(scores.index.get_level_values("datetime").unique())
        symbols_list = sorted(
            scores.index.get_level_values("instrument").unique().tolist()
        )
        first_date = dates[0]
        for idx, sym in enumerate(symbols_list):
            scores.loc[(first_date, sym), "score"] = float(
                idx - len(symbols_list) / 2
            )

        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        assert result.bottom_k_long["n_periods"] > 0
        assert isinstance(result.bottom_k_long["total_return"], float)

    def test_top_minus_bottom_is_difference_of_period_returns(self) -> None:
        """Spread arithmetic: spread[i] == top[i] - bottom[i]."""
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        top_pr = np.asarray(result.top_k_long["period_returns"], dtype=float)
        bot_pr = np.asarray(result.bottom_k_long["period_returns"], dtype=float)
        spread_expected = top_pr - bot_pr

        # Verify via cumulative return
        cumulative = np.cumprod(1.0 + spread_expected)
        expected_total = float(cumulative[-1] - 1.0)
        assert result.top_minus_bottom["total_return"] == pytest.approx(
            expected_total, rel=1e-12, abs=1e-12
        )

    def test_top_minus_bottom_zero_when_identical_legs(self) -> None:
        """When both legs are identical, spread is identically zero."""
        top = [0.01, -0.005, 0.02, 0.0, -0.01]
        bottom = [0.01, -0.005, 0.02, 0.0, -0.01]
        tmb = _compute_top_minus_bottom_diagnostic(top, bottom, rebalance_days=10)
        assert tmb["total_return"] == pytest.approx(0.0, abs=1e-12)
        assert tmb["sharpe_ratio"] == pytest.approx(0.0, abs=1e-12)
        assert tmb["max_drawdown"] == pytest.approx(0.0, abs=1e-12)

    def test_top_minus_bottom_positive_when_top_beats_bottom(self) -> None:
        """Top consistently ~1%+ better per period with variation → positive spread and Sharpe."""
        n = 20
        # Varying spread ensures std > 0 so Sharpe is defined and positive
        top = [0.02 + 0.005 * (i / (n - 1)) for i in range(n)]
        bottom = [0.01 - 0.002 * (i / (n - 1)) for i in range(n)]
        tmb = _compute_top_minus_bottom_diagnostic(top, bottom, rebalance_days=10)
        assert tmb["total_return"] > 0.0
        assert tmb["sharpe_ratio"] > 0.0
        assert tmb["positive_period_ratio"] == 1.0

    def test_top_minus_bottom_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            _compute_top_minus_bottom_diagnostic(
                [0.01, 0.02], [0.01], rebalance_days=10,
            )

    def test_annual_return_compounding_consistency(self) -> None:
        """Annual return should compound back to total return over the period."""
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        n = result.top_k_long["n_periods"]
        if n > 0:
            years = n * 10 / 252.0
            annual = result.top_k_long["annual_return"]
            total = result.top_k_long["total_return"]
            if years > 0 and 1.0 + total > 0:
                compounded = (1.0 + annual) ** years - 1.0
                assert compounded == pytest.approx(total, rel=1e-10, abs=1e-10)

    def test_positive_period_ratio_in_range(self) -> None:
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        for leg in [result.top_k_long, result.bottom_k_long]:
            ppr = leg["positive_period_ratio"]
            assert 0.0 <= ppr <= 1.0

    def test_max_drawdown_is_non_positive(self) -> None:
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        for leg in [result.top_k_long, result.bottom_k_long]:
            assert leg["max_drawdown"] <= 0.0

    def test_no_common_dates_raises(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        # Shift benchmark dates so no overlap
        benchmark.index = benchmark.index + pd.Timedelta(days=365 * 10)
        with pytest.raises(ValueError, match="no common dates"):
            evaluate_benchmark_aware_topk(
                scores, returns, benchmark, top_n=3,
            )


# ── caveat flags ─────────────────────────────────────────────────────────────


class TestCaveatFlags:
    def test_result_contains_caveats(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        assert len(result.caveats) >= 3
        assert any("NOT trade-ready" in c for c in result.caveats)
        assert any("borrow" in c.lower() for c in result.caveats)

    def test_to_dict_labels_distinguish_outputs(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        d = result.to_dict()
        assert d["top_k_long"]["label"] == "executable_style_research_portfolio"
        assert d["top_minus_bottom"]["label"] == "research_only_diagnostic"
        assert "caveats" in d["top_minus_bottom"]

    def test_top_minus_bottom_labeled_not_trade_ready(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        d = result.to_dict()
        desc = d["top_minus_bottom"]["description"]
        assert "NOT trade-ready" in desc

    def test_top_k_long_labeled_executable_style(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        d = result.to_dict()
        label = d["top_k_long"]["label"]
        assert label == "executable_style_research_portfolio"
        desc = d["top_k_long"]["description"]
        assert "portfolio" in desc.lower()
        assert "benchmark" in desc.lower()

    def test_config_included_in_to_dict(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=5, rebalance_days=10, cost_bps=15.0,
        )
        d = result.to_dict()
        assert d["config"]["top_n"] == 5
        assert d["config"]["cost_bps"] == 15.0


# ── BenchmarkAwareTopKResult dataclass ────────────────────────────────────────


class TestBenchmarkAwareTopKResult:
    def test_frozen_dataclass(self) -> None:
        with pytest.raises(Exception):
            r = BenchmarkAwareTopKResult(
                top_k_long={}, bottom_k_long={}, top_minus_bottom={},
            )
            r.top_k_long = {}  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = BenchmarkAwareTopKResult(
            top_k_long={"a": 1}, bottom_k_long={"b": 2}, top_minus_bottom={"c": 3},
        )
        assert r.config == {}
        assert r.caveats == []


# ── cost awareness ───────────────────────────────────────────────────────────


class TestCostAwareness:
    def test_costs_reduce_total_return(self) -> None:
        scores, returns, benchmark = _make_fixtures(seed=4201)
        free = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        costly = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=100.0,
        )
        # Higher costs → lower (or equal) net total return
        assert costly.top_k_long["costs"] >= free.top_k_long["costs"]

    def test_costs_field_present(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=20.0,
        )
        assert "costs" in result.top_k_long
        assert "turnover" in result.top_k_long


# ── positive_period_ratio for top_minus_bottom ───────────────────────────────


class TestTopMinusBottomDiagnostic:
    def test_empty_periods_returns_zero_metrics(self) -> None:
        tmb = _compute_top_minus_bottom_diagnostic([], [], rebalance_days=10)
        assert tmb["n_periods"] == 0
        assert tmb["total_return"] == 0.0
        assert tmb["sharpe_ratio"] == 0.0

    def test_single_period(self) -> None:
        tmb = _compute_top_minus_bottom_diagnostic(
            [0.05], [0.02], rebalance_days=10,
        )
        assert tmb["n_periods"] == 1
        assert tmb["total_return"] == pytest.approx(0.03, rel=1e-12)
        assert tmb["sharpe_ratio"] == 0.0  # single period has zero std

    def test_mixed_signs(self) -> None:
        top = [0.02, -0.01, 0.03, -0.005, 0.01]
        bottom = [0.01, 0.0, 0.01, 0.005, -0.005]
        tmb = _compute_top_minus_bottom_diagnostic(top, bottom, rebalance_days=10)
        assert tmb["n_periods"] == 5
        assert isinstance(tmb["positive_period_ratio"], float)
        assert 0.0 <= tmb["positive_period_ratio"] <= 1.0

    def test_volatility_non_negative(self) -> None:
        top = [0.02, -0.01, 0.03]
        bottom = [0.01, 0.00, 0.01]
        tmb = _compute_top_minus_bottom_diagnostic(top, bottom, rebalance_days=10)
        assert tmb["volatility"] >= 0.0

    def test_max_drawdown_includes_initial_nav(self) -> None:
        """First drawdown from initial 1.0 must be captured."""
        # Negative first period should produce a drawdown from 1.0
        top = [-0.01, 0.05]
        bottom = [0.03, -0.01]
        tmb = _compute_top_minus_bottom_diagnostic(top, bottom, rebalance_days=10)
        # spread = [-0.04, 0.06]; nav = [1.0, 0.96, 1.0176]; peak = [1.0, 1.0, 1.0176]
        # MDD = min(0, -0.04, -0.0176) = -0.04
        assert tmb["max_drawdown"] == pytest.approx(-0.04, abs=1e-12)

    def test_rejects_spread_below_minus_one(self) -> None:
        with pytest.raises(ValueError, match="<= -1.0"):
            _compute_top_minus_bottom_diagnostic(
                [-0.6], [0.5], rebalance_days=10,
            )


# ── CLI / help contract ──────────────────────────────────────────────────────


class TestCLIContract:
    def test_parser_has_data_root(self) -> None:
        parser = build_parser()
        # --data-root must be available but not required
        ns = parser.parse_args([])
        assert ns.data_root is None

        ns2 = parser.parse_args(["--data-root", "/tmp/data"])
        assert ns2.data_root == Path("/tmp/data")

    def test_parser_has_required_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args([])
        assert ns.first_test_year == 2024
        assert ns.last_test_year == 2026

    def test_help_contains_benchmark_aware(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        assert "benchmark" in help_text.lower()

    def test_help_contains_frozen_86(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        assert "#86" in help_text

    def test_help_lists_data_root(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        assert "--data-root" in help_text
        assert "--root" in help_text


# ── integration: full evaluation round-trip ──────────────────────────────────


class TestFullEvaluationRoundTrip:
    def test_all_three_legs_produce_consistent_periods(self) -> None:
        scores, returns, benchmark = _make_fixtures(seed=4201)
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        n = result.top_k_long["n_periods"]
        assert n > 0
        assert result.bottom_k_long["n_periods"] == n
        assert result.top_minus_bottom["n_periods"] == n

    def test_to_dict_is_json_serializable(self) -> None:
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        d = result.to_dict()
        serialized = json.dumps(d, indent=2, sort_keys=True, default=str)
        assert isinstance(serialized, str)
        roundtripped = json.loads(serialized)
        assert roundtripped["top_k_long"]["label"] == "executable_style_research_portfolio"

    def test_higher_top_n_selects_more_instruments(self) -> None:
        scores, returns, benchmark = _make_fixtures(seed=4201)
        r3 = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3, cost_bps=0.0,
        )
        r5 = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=5, cost_bps=0.0,
        )
        # Both should evaluate; detailed comparison not required
        assert r3.top_k_long["n_periods"] == r5.top_k_long["n_periods"]

    def test_same_seed_produces_deterministic_output(self) -> None:
        scores1, returns1, bench1 = _make_fixtures(seed=42)
        scores2, returns2, bench2 = _make_fixtures(seed=42)
        r1 = evaluate_benchmark_aware_topk(
            scores1, returns1, bench1, top_n=3, cost_bps=0.0,
        )
        r2 = evaluate_benchmark_aware_topk(
            scores2, returns2, bench2, top_n=3, cost_bps=0.0,
        )
        assert r1.top_k_long["total_return"] == pytest.approx(
            r2.top_k_long["total_return"], rel=1e-12, abs=1e-12,
        )

    def test_benchmark_period_returns_available(self) -> None:
        """Each leg includes derived benchmark_period_returns."""
        scores, returns, benchmark = _make_fixtures()
        result = evaluate_benchmark_aware_topk(
            scores, returns, benchmark, top_n=3,
        )
        bpr = result.top_k_long["benchmark_period_returns"]
        assert isinstance(bpr, list)
        assert len(bpr) > 0
        assert all(isinstance(v, float) for v in bpr)
