"""Framework-neutral walk-forward research contracts.

The former file mixed hundreds of domain checks with FastAPI/TestClient cases.
HTTP adapter coverage was retired; this suite now protects split generation,
calendar integrity, IC semantics, index alignment, benchmark subtraction and
native-estimator detection. Broader stability and execution coverage remains in
`test_walk_forward_stability.py`, `test_spec_bound_execution.py`,
`test_vectorized_backtest.py` and the Qlib integration suites.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.research.walk_forward import (
    SplitResult,
    WalkForwardResult,
    _add_months,
    _align_multiindex,
    _compute_ic,
    _compute_mean_daily_ic,
    _forward_return_expression,
    _is_native_estimator_config,
    _subtract_benchmark_by_date,
    _validate_calendar,
    generate_splits,
)


class TestDateAndSplitContracts:
    def test_add_months_clamps_end_of_month(self):
        assert _add_months(datetime(2024, 1, 31), 1) == datetime(2024, 2, 29)
        assert _add_months(datetime(2023, 1, 31), 1) == datetime(2023, 2, 28)

    def test_generate_splits_is_expanding_and_chronological(self):
        splits = generate_splits(
            train_start="2021-01-01",
            train_end="2025-12-31",
            test_window_months=6,
            step_months=3,
            min_train_months=12,
        )
        assert splits
        assert all(split[0] == "2021-01-01" for split in splits)
        for index, (_train_start, train_end, test_start, test_end) in enumerate(splits):
            assert train_end == test_start
            assert test_start < test_end
            if index:
                assert train_end > splits[index - 1][1]

    def test_generate_splits_rejects_invalid_minimum(self):
        with pytest.raises(ValueError, match="min_train_months"):
            generate_splits(min_train_months=0)

    def test_short_range_produces_no_split(self):
        assert generate_splits(
            train_start="2025-01-01",
            train_end="2025-06-01",
            min_train_months=12,
        ) == []


class TestAggregationContract:
    def test_aggregate_uses_only_successful_non_null_ic(self):
        result = WalkForwardResult(market="us", model_type="lgbm")
        result.splits = [
            SplitResult(0, "2021-01-01", "2022-01-01", "2022-01-01", "2022-07-01", 0.05, 0.04),
            SplitResult(1, "2021-01-01", "2022-04-01", "2022-04-01", "2022-10-01", -0.01, -0.02),
            SplitResult(2, "2021-01-01", "2022-07-01", "2022-07-01", "2023-01-01", None, None, status="failed", error_message="fixture"),
            SplitResult(3, "2021-01-01", "2022-10-01", "2022-10-01", "2023-04-01", None, None, status="skipped"),
        ]

        result.aggregate()

        assert result.n_success == 2
        assert result.n_failed == 1
        assert result.n_skipped == 1
        assert result.mean_ic == pytest.approx(0.02)
        assert result.consistency_score == pytest.approx(0.5)
        assert result.std_ic > 0
        assert result.ic_ir == pytest.approx(result.mean_ic / result.std_ic)

    def test_empty_aggregate_remains_zero(self):
        result = WalkForwardResult(market="cn", model_type="xgb")
        result.aggregate()
        assert result.mean_ic == 0.0
        assert result.n_success == 0


class TestICContract:
    def test_perfect_and_inverse_correlation(self):
        values = np.arange(10, dtype=float)
        assert _compute_ic(values, values)[0] == pytest.approx(1.0)
        assert _compute_ic(values, -values)[0] == pytest.approx(-1.0)

    def test_constant_and_too_small_samples_fail_closed_to_zero(self):
        assert _compute_ic(np.ones(10), np.arange(10, dtype=float)) == (0.0, 0.0)
        assert _compute_ic(np.arange(4, dtype=float), np.arange(4, dtype=float)) == (0.0, 0.0)

    def test_nan_rows_are_filtered(self):
        pearson, rank = _compute_ic(
            np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0]),
            np.array([2.0, 4.0, 6.0, np.nan, 10.0, 12.0, 14.0]),
        )
        assert pearson == pytest.approx(1.0)
        assert rank == pytest.approx(1.0)

    def test_mean_daily_ic_uses_cross_sections(self):
        index = pd.MultiIndex.from_product(
            [pd.to_datetime(["2024-01-02", "2024-01-03"]), list("ABCDE")],
            names=["datetime", "instrument"],
        )
        predictions = np.array([1, 2, 3, 4, 5, 1, 2, 3, 4, 5], dtype=float)
        actuals = pd.Series([5, 4, 3, 2, 1, 1, 2, 3, 4, 5], index=index, dtype=float)

        pearson, rank = _compute_mean_daily_ic(predictions, actuals)

        assert pearson == pytest.approx(0.0)
        assert rank == pytest.approx(0.0)


class TestIndexAndBenchmarkContracts:
    @staticmethod
    def _series(rows):
        index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
        return pd.Series(np.arange(len(rows), dtype=float), index=index)

    def test_alignment_uses_label_intersection(self):
        first = self._series([
            (pd.Timestamp("2024-01-02"), "A"),
            (pd.Timestamp("2024-01-02"), "B"),
        ])
        second = self._series([
            (pd.Timestamp("2024-01-02"), "B"),
            (pd.Timestamp("2024-01-03"), "C"),
        ])

        aligned_first, aligned_second = _align_multiindex(first, second)

        expected = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02"), "B")],
            names=["datetime", "instrument"],
        )
        assert aligned_first.index.equals(expected)
        assert aligned_second.index.equals(expected)

    def test_alignment_rejects_flat_or_disjoint_indexes(self):
        with pytest.raises(TypeError):
            _align_multiindex(pd.Series([1, 2]), pd.Series([1, 2]))

        first = self._series([(pd.Timestamp("2024-01-02"), "A")])
        second = self._series([(pd.Timestamp("2024-01-03"), "B")])
        with pytest.raises(ValueError, match="No common"):
            _align_multiindex(first, second)

    def test_benchmark_is_subtracted_by_date(self):
        index = pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2024-01-02"), "A"),
                (pd.Timestamp("2024-01-02"), "B"),
                (pd.Timestamp("2024-01-03"), "A"),
            ],
            names=["datetime", "instrument"],
        )
        stock = pd.Series([0.10, 0.04, -0.02], index=index)
        benchmark = pd.Series(
            [0.03, -0.01],
            index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="datetime"),
        )

        excess = _subtract_benchmark_by_date(stock, benchmark)

        assert excess.index.equals(stock.index)
        assert excess.to_numpy() == pytest.approx([0.07, 0.01, -0.01])


class TestCalendarContract:
    def test_valid_calendar_accepts_holiday_boundary_gap(self):
        calendar = pd.bdate_range("2024-01-02", "2024-01-31")
        _validate_calendar(calendar, "2024-01-01", "2024-02-01")

    @pytest.mark.parametrize(
        "calendar, message",
        [
            (pd.DatetimeIndex([]), "empty"),
            (pd.DatetimeIndex(["2024-01-02", "2024-01-02"]), "duplicate"),
            (pd.DatetimeIndex(["2024-01-03", "2024-01-02"]), "monotonically"),
        ],
    )
    def test_invalid_calendars_fail_closed(self, calendar, message):
        with pytest.raises(RuntimeError, match=message):
            _validate_calendar(calendar, "2024-01-01", "2024-01-31")

    def test_incomplete_boundary_coverage_fails(self):
        calendar = pd.bdate_range("2024-02-01", "2024-02-29")
        with pytest.raises(RuntimeError, match="after required start"):
            _validate_calendar(calendar, "2024-01-01", "2024-02-29")


class TestConfigurationContract:
    def test_forward_return_expression_defaults_to_ten_days(self):
        assert _forward_return_expression(0) == "Ref($close, -10) / Ref($close, -1) - 1"
        assert _forward_return_expression(5) == "Ref($close, -5) / Ref($close, -1) - 1"

    def test_native_estimator_detection_is_explicit(self):
        native = {"task": {"model": {"module_path": "lightgbm", "class": "LGBMRegressor"}}}
        qlib = {"task": {"model": {"module_path": "qlib.contrib.model.gbdt"}}}
        assert _is_native_estimator_config(native) is True
        assert _is_native_estimator_config(qlib) is False
        assert _is_native_estimator_config({}) is False
