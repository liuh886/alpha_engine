"""Focused deterministic tests for selection tail diagnostics.

Covers:
- Exact reconciliation with RiskVariantReport
- Fail-closed missing selected return and insufficient 2K cross-section
- Perfect/inverted tail behavior
- Period-weighted multi-window aggregation
- Full worst-period and symbol negative attribution
- Non-null failure-delta mapping
- No silent diagnostic skip
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.risk_control_variants import (
    RiskVariantSpec,
    VARIANT_TOP3_BENCHMARK_TREND,
    evaluate_risk_control_variant,
)
from src.research.selection_tail_diagnostics import (
    compute_selection_tail_diagnostics,
    summarize_window_diagnostics,
)


# ══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ══════════════════════════════════════════════════════════════════════════


def _scores() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    instruments = ["A", "B", "C", "D", "E", "F"]
    rows = []
    values = []
    for date in dates:
        for rank, instrument in enumerate(instruments):
            rows.append((date, instrument))
            values.append(float(10 - rank))
    index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
    return pd.DataFrame({"score": values}, index=index)


def _returns() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    instruments = ["A", "B", "C", "D", "E", "F"]
    values_by_instrument = {
        "A": 0.08,
        "B": 0.05,
        "C": 0.03,
        "D": 0.01,
        "E": -0.01,
        "F": -0.03,
    }
    rows = []
    values = []
    for date in dates:
        for instrument in instruments:
            rows.append((date, instrument))
            values.append(values_by_instrument[instrument])
    index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
    frame = pd.DataFrame({"return": values}, index=index)
    frame.attrs["provenance"] = "raw_forward_return"
    frame.attrs["horizon"] = 10
    return frame


def _benchmark() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    frame = pd.DataFrame({"return": [0.02, -0.01, 0.015]}, index=dates)
    frame.attrs["provenance"] = "raw_forward_return"
    frame.attrs["horizon"] = 10
    return frame


def _benchmark_trend() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    return pd.DataFrame({"trend_return_20d": [0.05, -0.03, 0.02]}, index=dates)


def _report():
    """Standard RiskVariantReport using frozen test fixtures."""
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=3,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=0.5,
    )
    return evaluate_risk_control_variant(
        _scores(),
        _returns(),
        _benchmark(),
        spec=spec,
        benchmark_trend=_benchmark_trend(),
        rebalance_days=1,
        cost_bps=20.0,
    )


# ══════════════════════════════════════════════════════════════════════════
# Labels and metadata
# ══════════════════════════════════════════════════════════════════════════


class TestMetadataLabels:
    """Diagnostic output carries correct research-only / trade-ready / bottom-leg labels."""

    def test_diagnostics_labels(self) -> None:
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), _report())
        assert diag["research_only"] is True
        assert diag["trade_ready"] is False
        assert diag["bottom_leg_is_diagnostic_only"] is True

    def test_summarizer_labels(self) -> None:
        summary = summarize_window_diagnostics([])
        assert summary["research_only"] is True
        assert summary["trade_ready"] is False
        assert summary["bottom_leg_is_diagnostic_only"] is True


# ══════════════════════════════════════════════════════════════════════════
# Period detail reconciliation with RiskVariantReport
# ══════════════════════════════════════════════════════════════════════════


class TestPeriodDetailReconciliation:
    """Period-level diagnostics exactly match the source RiskVariantReport."""

    def test_net_return_exactly_matches_period_returns(self) -> None:
        """Each PeriodDetail.net_return equals the corresponding period_returns entry."""
        report = _report()
        for i, pd_ in enumerate(report.period_details):
            assert pd_.net_return == pytest.approx(report.period_returns[i], abs=1e-12)

    def test_relative_excess_formula(self) -> None:
        """PeriodDetail.relative_excess = (1+net)/(1+benchmark)-1."""
        report = _report()
        for pd_ in report.period_details:
            expected = (1.0 + pd_.net_return) / (1.0 + pd_.benchmark_return) - 1.0
            assert pd_.relative_excess == pytest.approx(expected, abs=1e-12)

    def test_gross_return_minus_cost_equals_net(self) -> None:
        """For each period: gross_return - cost = net_return."""
        report = _report()
        for pd_ in report.period_details:
            assert pd_.gross_return - pd_.cost == pytest.approx(pd_.net_return, abs=1e-12)

    def test_portfolio_fields_reconcile_with_to_dict(self) -> None:
        """Diagnostic portfolio fields match RiskVariantReport.period_details via to_dict."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)
        report_dict = report.to_dict()

        for period_diag in diag["periods"]:
            date = period_diag["date"]
            match = [p for p in report_dict["period_details"] if p["date"] == date]
            assert len(match) == 1, f"no unique match for {date}"
            pd_dict = match[0]

            pf = period_diag["portfolio"]
            for key in ("gross_exposure", "turnover", "cost", "gross_return",
                        "net_return", "benchmark_return", "relative_excess"):
                assert pf[key] == pytest.approx(pd_dict[key], abs=1e-12)

    def test_selected_holdings_match_report(self) -> None:
        """Diagnostic selected holding weights/returns match report period details."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)

        for period_diag in diag["periods"]:
            date = period_diag["date"]
            pd_ = next(p for p in report.period_details if p.date == date)

            for h_diag in period_diag["selected_holdings"]:
                h_report = next(h for h in pd_.holdings if h.symbol == h_diag["symbol"])
                assert h_diag["weight"] == pytest.approx(h_report.weight, abs=1e-12)
                assert h_diag["raw_return"] == pytest.approx(h_report.raw_return, abs=1e-12)
                assert h_diag["gross_contribution"] == pytest.approx(
                    h_report.gross_contribution, abs=1e-12
                )


# ══════════════════════════════════════════════════════════════════════════
# Fail-closed: missing or non-finite selected return
# ══════════════════════════════════════════════════════════════════════════


class TestFailClosedMissingReturn:
    """evaluate_variant_weights must fail closed when a selected holding lacks a finite return."""

    def test_missing_symbol_raises_value_error(self) -> None:
        """Missing return data for a selected symbol raises ValueError."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
        # Symbol A (top scorer) missing from first date's returns
        rows = []
        for inst in ("B", "C", "D", "E", "F"):
            rows.append((dates[0], inst))
        for inst in ("A", "B", "C", "D", "E", "F"):
            rows.append((dates[1], inst))
            rows.append((dates[2], inst))
        values = [0.05, 0.03, 0.01, -0.01, -0.03]
        values += [0.08, 0.05, 0.03, 0.01, -0.01, -0.03]
        values += [0.08, 0.05, 0.03, 0.01, -0.01, -0.03]
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        returns_missing = pd.DataFrame({"return": values}, index=index)
        returns_missing.attrs["provenance"] = "raw_forward_return"
        returns_missing.attrs["horizon"] = 10

        spec = RiskVariantSpec(
            variant_id=VARIANT_TOP3_BENCHMARK_TREND,
            top_n=3,
            construction="equal_weight_with_benchmark_trend_filter",
            negative_benchmark_trend_exposure=0.5,
        )
        with pytest.raises(ValueError, match="no return data"):
            evaluate_risk_control_variant(
                _scores(), returns_missing, _benchmark(),
                spec=spec, benchmark_trend=_benchmark_trend(),
                rebalance_days=1, cost_bps=20.0,
            )

    def test_nan_return_raises_value_error(self) -> None:
        """NaN return for a selected symbol raises ValueError."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
        instruments = ["A", "B", "C", "D", "E", "F"]
        values_by_nan = {"A": np.nan, "B": 0.05, "C": 0.03,
                         "D": 0.01, "E": -0.01, "F": -0.03}
        rows = []
        values = []
        for date in dates:
            for instrument in instruments:
                rows.append((date, instrument))
                values.append(values_by_nan[instrument])
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        returns_nan = pd.DataFrame({"return": values}, index=index)
        returns_nan.attrs["provenance"] = "raw_forward_return"
        returns_nan.attrs["horizon"] = 10

        spec = RiskVariantSpec(
            variant_id=VARIANT_TOP3_BENCHMARK_TREND,
            top_n=3,
            construction="equal_weight_with_benchmark_trend_filter",
            negative_benchmark_trend_exposure=0.5,
        )
        with pytest.raises(ValueError, match="no return data"):
            evaluate_risk_control_variant(
                _scores(), returns_nan, _benchmark(),
                spec=spec, benchmark_trend=_benchmark_trend(),
                rebalance_days=1, cost_bps=20.0,
            )


# ══════════════════════════════════════════════════════════════════════════
# Fail-closed: insufficient 2*top_n cross-section
# ══════════════════════════════════════════════════════════════════════════


class TestFailClosedInsufficientCrossSection:
    """_compute_period_diagnostics fails closed when cross-section < 2*top_n."""

    def test_insufficient_common_symbols_raises(self) -> None:
        """With top_n=3 and only 5 common symbols (need 6), raises ValueError."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
        instruments = ["A", "B", "C", "D", "E"]  # only 5 symbols
        rows = []
        values = []
        for date in dates:
            for rank, instrument in enumerate(instruments):
                rows.append((date, instrument))
                values.append(float(10 - rank))
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        small_scores = pd.DataFrame({"score": values}, index=index)

        # Returns matching only the 5 symbols
        values_by_instrument = {
            "A": 0.08, "B": 0.05, "C": 0.03, "D": 0.01, "E": -0.01,
        }
        rrows = []
        rvalues = []
        for date in dates:
            for instrument in instruments:
                rrows.append((date, instrument))
                rvalues.append(values_by_instrument[instrument])
        rindex = pd.MultiIndex.from_tuples(rrows, names=["datetime", "instrument"])
        small_returns = pd.DataFrame({"return": rvalues}, index=rindex)
        small_returns.attrs["provenance"] = "raw_forward_return"
        small_returns.attrs["horizon"] = 10

        with pytest.raises(ValueError, match="insufficient scored symbols"):
            compute_selection_tail_diagnostics(
                small_scores, small_returns, _report(), top_n=3,
            )

    def test_missing_bottom_tail_return_does_not_rerank_from_future_availability(
        self,
    ) -> None:
        """Bottom-K is chosen from scores first, then missing returns fail closed."""
        scores = _scores()
        extra_index = pd.MultiIndex.from_tuples(
            [
                (date, "G")
                for date in scores.index.get_level_values("datetime").unique()
            ],
            names=["datetime", "instrument"],
        )
        scores = pd.concat(
            [
                scores,
                pd.DataFrame({"score": [-100.0] * len(extra_index)}, index=extra_index),
            ]
        ).sort_index()

        # G is the lowest-scored name but has no realized return.  The old
        # intersection-first implementation silently replaced it with D.
        with pytest.raises(ValueError, match="tail selections.*no finite raw returns"):
            compute_selection_tail_diagnostics(
                scores,
                _returns(),
                _report(),
                top_n=3,
            )


# ══════════════════════════════════════════════════════════════════════════
# Tail behavior: perfect / inverted
# ══════════════════════════════════════════════════════════════════════════


class TestTailBehavior:
    """Diagnostic spread and percentile reflect score-return relationship."""

    def test_perfect_tail_spread_positive(self) -> None:
        """With positively-correlated scores/returns, spread > 0 and selected percentiles high."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)
        agg = diag["aggregate"]

        assert agg["mean_spread"] > 0.0
        assert agg["positive_spread_count"] == 3  # all periods
        assert agg["positive_spread_ratio"] == 1.0

        # Every selected holding (A, B, C) has return above median
        for period in diag["periods"]:
            for h in period["selected_holdings"]:
                pct = h["realized_return_percentile"]
                assert pct is not None, f"{h['symbol']} missing percentile"
                assert pct > 0.5, f"{h['symbol']} percentile {pct} not above median"

        assert agg["mean_selected_realized_percentile"] > 0.5

    def test_inverted_tail_spread_negative(self) -> None:
        """With inversely-correlated scores/returns, spread < 0."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
        instruments = ["A", "B", "C", "D", "E", "F"]
        inv_returns_map = {
            "A": -0.08, "B": -0.05, "C": -0.03,
            "D": -0.01, "E": 0.01, "F": 0.03,
        }
        rows = []
        values = []
        for date in dates:
            for instrument in instruments:
                rows.append((date, instrument))
                values.append(inv_returns_map[instrument])
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        inv_returns = pd.DataFrame({"return": values}, index=index)
        inv_returns.attrs["provenance"] = "raw_forward_return"
        inv_returns.attrs["horizon"] = 10

        report = evaluate_risk_control_variant(
            _scores(), inv_returns, _benchmark(),
            spec=RiskVariantSpec(
                variant_id=VARIANT_TOP3_BENCHMARK_TREND,
                top_n=3,
                construction="equal_weight_with_benchmark_trend_filter",
                negative_benchmark_trend_exposure=0.5,
            ),
            benchmark_trend=_benchmark_trend(),
            rebalance_days=1, cost_bps=20.0,
        )
        diag = compute_selection_tail_diagnostics(_scores(), inv_returns, report)
        agg = diag["aggregate"]

        # Top-K by score (A, B, C) have worst returns → negative spread
        assert agg["mean_spread"] < 0.0
        # Selected holdings have low realized percentiles
        assert agg["mean_selected_realized_percentile"] < 0.3


# ══════════════════════════════════════════════════════════════════════════
# Worst-period aggregation
# ══════════════════════════════════════════════════════════════════════════


class TestWorstPeriods:
    """Aggregate correctly identifies worst-performing periods."""

    def test_worst_net_return_period(self) -> None:
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)

        net_returns = [detail.net_return for detail in report.period_details]
        expected_net = min(net_returns)
        expected_date = report.period_details[net_returns.index(expected_net)].date

        worst = diag["aggregate"]["worst_net_return_period"]
        assert worst["net_return"] == pytest.approx(expected_net, abs=1e-12)
        assert worst["date"] == expected_date

    def test_worst_relative_excess_period(self) -> None:
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)

        rel_excesses = [detail.relative_excess for detail in report.period_details]
        expected_rel = min(rel_excesses)
        expected_date = report.period_details[rel_excesses.index(expected_rel)].date

        worst = diag["aggregate"]["worst_relative_excess_period"]
        assert worst["relative_excess"] == pytest.approx(expected_rel, abs=1e-12)
        assert worst["date"] == expected_date


# ══════════════════════════════════════════════════════════════════════════
# Symbol attribution with negative contribution tracking
# ══════════════════════════════════════════════════════════════════════════


class TestSymbolAttribution:
    """Per-symbol selection counts, contribution sums, and negative tracking."""

    def test_selection_counts(self) -> None:
        """Each selected symbol appears exactly once per period (total = n_periods)."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)
        sym_data = diag["aggregate"]["symbol_contributions"]

        for sym in ("A", "B", "C"):
            assert sym in sym_data
            assert sym_data[sym]["times_selected"] == len(report.period_details)
        assert len(sym_data) == 3  # only top-3 selected

    def test_gross_contributions_sum_matches_gross_return(self) -> None:
        """Sum of symbol gross_contributions equals portfolio gross_return per period."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)
        for period in diag["periods"]:
            total = sum(h["gross_contribution"] for h in period["selected_holdings"])
            assert total == pytest.approx(period["portfolio"]["gross_return"], abs=1e-12)

    def test_negative_contribution_fields_present(self) -> None:
        """symbol_contributions includes negative_contribution_count and worst_gross_contribution."""
        report = _report()
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), report)
        sym_data = diag["aggregate"]["symbol_contributions"]

        for sym in ("A", "B", "C"):
            entry = sym_data[sym]
            assert "negative_contribution_count" in entry
            assert "worst_gross_contribution" in entry
            # All returns positive -> zero negative contributions
            assert entry["negative_contribution_count"] == 0
            # worst_gross_contribution should be finite (min positive contribution)
            assert entry["worst_gross_contribution"] is not None
            assert np.isfinite(entry["worst_gross_contribution"])

    def test_negative_contributions_counted_when_returns_negative(self) -> None:
        """Symbols with negative gross_contribution increment negative_contribution_count."""
        dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
        instruments = ["A", "B", "C", "D", "E", "F"]
        # A has negative return, B neutral, C positive
        neg_returns_map = {"A": -0.08, "B": 0.0, "C": 0.03,
                           "D": 0.01, "E": -0.01, "F": -0.03}
        rows = []
        values = []
        for date in dates:
            for instrument in instruments:
                rows.append((date, instrument))
                values.append(neg_returns_map[instrument])
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        neg_returns = pd.DataFrame({"return": values}, index=index)
        neg_returns.attrs["provenance"] = "raw_forward_return"
        neg_returns.attrs["horizon"] = 10

        report = evaluate_risk_control_variant(
            _scores(), neg_returns, _benchmark(),
            spec=RiskVariantSpec(
                variant_id=VARIANT_TOP3_BENCHMARK_TREND,
                top_n=3,
                construction="equal_weight_with_benchmark_trend_filter",
                negative_benchmark_trend_exposure=0.5,
            ),
            benchmark_trend=_benchmark_trend(),
            rebalance_days=1, cost_bps=20.0,
        )
        diag = compute_selection_tail_diagnostics(_scores(), neg_returns, report)
        sym_data = diag["aggregate"]["symbol_contributions"]

        # A (negative return) should have negative_contribution_count > 0
        assert sym_data["A"]["negative_contribution_count"] == len(report.period_details)
        # B (zero return) should have non-negative
        assert sym_data["B"]["negative_contribution_count"] == 0
        # worst_gross_contribution for A should be negative
        assert sym_data["A"]["worst_gross_contribution"] < 0


# ══════════════════════════════════════════════════════════════════════════
# Input validation
# ══════════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """compute_selection_tail_diagnostics validates frame structure and provenance."""

    def test_rejects_invalid_score_columns(self) -> None:
        bad_scores = pd.DataFrame({"wrong": [1.0, 2.0]})
        with pytest.raises(ValueError, match="exactly one"):
            compute_selection_tail_diagnostics(bad_scores, _returns(), _report())

    def test_rejects_invalid_returns_provenance(self) -> None:
        bad_returns = _returns().copy()
        bad_returns.attrs["provenance"] = "wrong"
        with pytest.raises(ValueError, match="provenance"):
            compute_selection_tail_diagnostics(_scores(), bad_returns, _report())

    def test_rejects_invalid_returns_horizon(self) -> None:
        bad_returns = _returns().copy()
        bad_returns.attrs["horizon"] = 5
        with pytest.raises(ValueError, match="horizon"):
            compute_selection_tail_diagnostics(_scores(), bad_returns, _report())


# ══════════════════════════════════════════════════════════════════════════
# Summarizer — period-weighted aggregation
# ══════════════════════════════════════════════════════════════════════════


class TestSummarizer:
    """Cross-window summarizer combines diagnostics with period-weighted aggregation."""

    def test_empty_diagnostics(self) -> None:
        summary = summarize_window_diagnostics([])
        assert summary["n_windows"] == 0
        assert summary["research_only"] is True

    def test_duplicate_windows_period_weighted(self) -> None:
        """Same diagnostics repeated produce exact period-weighted aggregates (not mean-of-means)."""
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), _report())
        summary = summarize_window_diagnostics([diag, diag])
        single = diag["aggregate"]

        assert summary["n_windows"] == 2
        assert summary["n_periods_total"] == 6
        # Period-weighted aggregate equals the single-window aggregate when both
        # windows are identical (same mean, same weights)
        assert summary["mean_spread"] == pytest.approx(single["mean_spread"], abs=1e-12)
        assert summary["mean_selected_realized_percentile"] == pytest.approx(
            single["mean_selected_realized_percentile"], abs=1e-12
        )
        assert np.isfinite(summary["mean_spread"])
        assert np.isfinite(summary["mean_selected_realized_percentile"])

        # New enriched fields present
        assert np.isfinite(summary["total_turnover"])
        assert np.isfinite(summary["total_cost"])
        assert "worst_net_return_period" in summary
        assert "worst_relative_excess_period" in summary
        assert "worst_net_return_period_detail" in summary
        assert "worst_relative_excess_period_detail" in summary

        # symbol_contributions key (not legacy symbol_selection_counts)
        assert len(summary["symbol_contributions"]) > 0
        # Verify per-symbol sub-fields
        for sym_data in summary["symbol_contributions"].values():
            assert "times_selected" in sym_data
            assert "sum_gross_contribution" in sym_data
            assert "negative_contribution_count" in sym_data
            assert "worst_gross_contribution" in sym_data

    def test_window_label_preserved(self) -> None:
        """window_label from each diagnostic is preserved on flattened periods."""
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), _report())
        diag["window_label"] = "test_window"
        summary = summarize_window_diagnostics([diag])

        worst_detail = summary["worst_net_return_period_detail"]
        assert worst_detail.get("window_label") == "test_window"
        assert set(summary["window_breakdown"]) == {"test_window"}
        assert (
            summary["window_breakdown"]["test_window"]["n_periods"]
            == len(diag["periods"])
        )

    def test_worst_period_detail_has_full_holdings(self) -> None:
        """Worst period detail includes selected_holdings and portfolio sub-dicts."""
        diag = compute_selection_tail_diagnostics(_scores(), _returns(), _report())
        summary = summarize_window_diagnostics([diag])

        for key in ("worst_net_return_period_detail", "worst_relative_excess_period_detail"):
            detail = summary[key]
            assert "selected_holdings" in detail
            assert len(detail["selected_holdings"]) > 0
            assert "portfolio" in detail
            assert "gross_exposure" in detail["portfolio"]


# ══════════════════════════════════════════════════════════════════════════
# Failure diagnostics helper
# ══════════════════════════════════════════════════════════════════════════


class TestBuildFailureDiagnostics:
    """_build_failure_diagnostics produces correct key mapping and non-null deltas."""

    # Import the function from the runner script
    @staticmethod
    def _build_failure_diagnostics(
        cohort_aggregates: dict,
    ) -> dict:
        from scripts.run_candidate_v2_universe_robustness import (
            _build_failure_diagnostics as fn,
        )
        return fn(cohort_aggregates)

    def test_key_names_match_source(self) -> None:
        """Expanded cohort entries use source key names (not legacy aliases)."""
        # Build minimal mock cohort aggregates
        mock: dict = {}
        for name in ("default_10_symbols", "expanded_50_symbols"):
            mock[name] = {
                "skipped": False,
                "candidate_v2": {
                    "compounded_relative_excess_return": 0.45,
                    "compounded_total_return": 0.80,
                    "compounded_benchmark_return": 0.20,
                    "worst_drawdown": -0.10,
                },
                "selection_tail_diagnostics": {
                    "n_windows": 4,
                    "n_periods_total": 12,
                    "mean_spread": 0.02,
                    "mean_positive_spread_ratio": 0.75,
                    "mean_selected_realized_percentile": 0.60,
                    "mean_selected_above_median_ratio": 0.70,
                    "mean_selected_positive_return_ratio": 0.80,
                    "total_turnover": 4.0,
                    "total_cost": 0.008,
                    "worst_net_return_period": {},
                    "worst_relative_excess_period": {},
                    "symbol_contributions": {},
                },
            }

        result = self._build_failure_diagnostics(mock)

        for name in ("default_10_symbols", "expanded_50_symbols"):
            entry = result["cohorts"][name]
            assert "compounded_relative_excess_return" in entry
            assert "compounded_total_return" in entry  # not compounded_net_return
            assert "compounded_benchmark_return" in entry
            assert "worst_drawdown" in entry

    def test_deltas_non_null_when_finite(self) -> None:
        """Numeric deltas vs default_10_symbols are non-null when both inputs are finite."""
        mock: dict = {}
        for name in ("default_10_symbols", "expanded_50_symbols"):
            mock[name] = {
                "skipped": False,
                "candidate_v2": {
                    "compounded_relative_excess_return": 0.40,
                    "compounded_total_return": 0.75,
                    "compounded_benchmark_return": 0.20,
                    "worst_drawdown": -0.10,
                },
                "selection_tail_diagnostics": {
                    "n_windows": 4,
                    "n_periods_total": 12,
                    "mean_spread": 0.02,
                    "mean_positive_spread_ratio": 0.75,
                    "mean_selected_realized_percentile": 0.60,
                    "mean_selected_above_median_ratio": 0.70,
                    "mean_selected_positive_return_ratio": 0.80,
                    "total_turnover": 4.0,
                    "total_cost": 0.008,
                    "worst_net_return_period": {},
                    "worst_relative_excess_period": {},
                    "symbol_contributions": {},
                },
            }
        # Override expanded with different values
        mock["expanded_50_symbols"]["candidate_v2"]["compounded_relative_excess_return"] = 0.30
        mock["expanded_50_symbols"]["selection_tail_diagnostics"]["mean_spread"] = 0.01

        result = self._build_failure_diagnostics(mock)
        deltas = result["cohorts"]["expanded_50_symbols"]["deltas_vs_default_10_symbols"]

        assert deltas["compounded_relative_excess_return"] == pytest.approx(-0.10, abs=1e-12)
        assert deltas["compounded_total_return"] == 0.0
        assert deltas["mean_spread"] == pytest.approx(-0.01, abs=1e-12)

    def test_deltas_none_when_non_finite(self) -> None:
        """Deltas are None when candidate_v2 values are missing or non-finite."""
        mock: dict = {}
        for name in ("default_10_symbols", "expanded_50_symbols"):
            mock[name] = {
                "skipped": False,
                "candidate_v2": {
                    "compounded_relative_excess_return": float("nan"),
                    "compounded_total_return": float("inf"),
                    "compounded_benchmark_return": float("-inf"),
                    "worst_drawdown": None,
                },
                "selection_tail_diagnostics": {
                    "n_windows": 4,
                    "n_periods_total": 12,
                    "mean_spread": 0.02,
                    "mean_positive_spread_ratio": 0.75,
                    "mean_selected_realized_percentile": 0.60,
                    "mean_selected_above_median_ratio": 0.70,
                    "mean_selected_positive_return_ratio": 0.80,
                    "total_turnover": 4.0,
                    "total_cost": 0.008,
                    "worst_net_return_period": {},
                    "worst_relative_excess_period": {},
                    "symbol_contributions": {},
                },
            }

        result = self._build_failure_diagnostics(mock)
        deltas = result["cohorts"]["expanded_50_symbols"]["deltas_vs_default_10_symbols"]

        for key in ("compounded_relative_excess_return", "compounded_total_return",
                     "compounded_benchmark_return", "worst_drawdown"):
            assert deltas[key] is None, f"{key} should be None, got {deltas[key]}"


# ══════════════════════════════════════════════════════════════════════════
# No silent diagnostic skip
# ══════════════════════════════════════════════════════════════════════════


class TestNoSilentSkip:
    """Selection diagnostic errors must not be silently swallowed by the summarizer."""

    def test_skipped_diag_fails_summary(self) -> None:
        """A skipped diagnostic fails closed with its reason."""
        skipped = {"skipped": True, "skip_reason": "diagnostic failure: test"}
        with pytest.raises(ValueError, match="diagnostic failure: test"):
            summarize_window_diagnostics([skipped])

    def test_partial_skip_fails_summary(self) -> None:
        """One failed window prevents a partial cohort summary."""
        valid = compute_selection_tail_diagnostics(_scores(), _returns(), _report())
        skipped = {
            "skipped": True,
            "skip_reason": "compute_selection_tail_diagnostics failed: test error",
        }
        with pytest.raises(ValueError, match="failed: test error"):
            summarize_window_diagnostics([valid, skipped])
