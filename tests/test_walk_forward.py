"""Tests for walk-forward validation logic and API."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import walk_forward as walk_forward_router
from src.api.routers.walk_forward import router as wf_router
from src.research.walk_forward import (
    SplitResult,
    WalkForwardResult,
    _add_months,
    _align_multiindex,
    _compute_ic,
    _compute_mean_daily_ic,
    _fit_native_estimator,
    _forward_return_expression,
    _is_native_estimator_config,
    _load_raw_labels,
    _prepare_native_dataset,
    _run_single_split,
    _subtract_benchmark_by_date,
    _validate_calendar,
    generate_splits,
    walk_forward_validate,
    walk_forward_vectorized,
)

# ---------------------------------------------------------------------------
# Pre-existing tests (preserved from original)
# ---------------------------------------------------------------------------


class TestGenerateSplits:
    """Test the expanding-window split generator."""

    def test_basic_splits_count(self):
        splits = generate_splits(
            train_start="2021-01-01", train_end="2026-04-03",
            test_window_months=6, step_months=3,
        )
        assert len(splits) >= 8
        assert len(splits) <= 20

    def test_splits_are_chronological(self):
        splits = generate_splits()
        for i, (ts, te, vs, ve) in enumerate(splits):
            assert te <= vs, f"Split {i}: train_end {te} must be <= test_start {vs}"
            assert vs < ve, f"Split {i}: test_start {vs} must be < test_end {ve}"
            if i > 0:
                assert te >= splits[i - 1][1]

    def test_train_start_is_fixed(self):
        splits = generate_splits()
        for ts, _te, _vs, _ve in splits:
            assert ts == "2021-01-01"

    def test_test_windows_do_not_overlap_beyond_step(self):
        splits = generate_splits(
            train_start="2021-01-01", train_end="2025-12-31",
            test_window_months=6, step_months=3,
        )
        for i in range(1, len(splits)):
            assert splits[i][2] >= splits[i - 1][2]

    def test_no_splits_when_range_too_short(self):
        splits = generate_splits(
            train_start="2025-01-01", train_end="2025-06-01",
            test_window_months=6, step_months=3,
        )
        assert len(splits) == 0

    def test_custom_params(self):
        short = generate_splits(
            train_start="2021-01-01", train_end="2025-12-31",
            test_window_months=12, step_months=6,
        )
        long = generate_splits(
            train_start="2021-01-01", train_end="2025-12-31",
            test_window_months=6, step_months=3,
        )
        assert len(short) < len(long)


class TestWalkForwardResult:
    """Test aggregation logic on WalkForwardResult."""

    def test_aggregate_single_split(self):
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.splits = [
            SplitResult(split_id=0, train_start="2021-01-01",
                        train_end="2023-01-01", test_start="2023-01-01",
                        test_end="2023-07-01", ic=0.05, rank_ic=0.04)
        ]
        r.aggregate()
        assert r.mean_ic == 0.05
        assert r.std_ic == 0.0
        assert r.ic_ir == 0.0
        assert r.consistency_score == 1.0

    def test_aggregate_multiple_splits(self):
        r = WalkForwardResult(market="us", model_type="lgbm")
        ics = [0.05, 0.03, -0.01, 0.04, 0.02]
        r.splits = [
            SplitResult(split_id=i, train_start="2021-01-01",
                        train_end="2023-01-01", test_start="2023-01-01",
                        test_end="2023-07-01", ic=ic, rank_ic=0.0)
            for i, ic in enumerate(ics)
        ]
        r.aggregate()
        expected_mean = np.mean(ics)
        expected_std = np.std(ics, ddof=1)
        assert abs(r.mean_ic - expected_mean) < 1e-10
        assert abs(r.std_ic - expected_std) < 1e-10
        assert abs(r.ic_ir - expected_mean / expected_std) < 1e-10
        assert r.consistency_score == 0.8

    def test_aggregate_empty(self):
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.aggregate()
        assert r.mean_ic == 0.0
        assert r.std_ic == 0.0

    def test_aggregate_all_negative(self):
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.splits = [
            SplitResult(split_id=i, train_start="2021-01-01",
                        train_end="2023-01-01", test_start="2023-01-01",
                        test_end="2023-07-01", ic=ic, rank_ic=0.0)
            for i, ic in enumerate([-0.02, -0.01, -0.03])
        ]
        r.aggregate()
        assert r.consistency_score == 0.0


class TestComputeIC:
    """Test the IC computation helper."""

    def test_perfect_correlation(self):
        x = np.arange(100, dtype=float)
        pearson, rank = _compute_ic(x, x * 2 + 1)
        assert abs(pearson - 1.0) < 1e-10
        assert abs(rank - 1.0) < 1e-10

    def test_anti_correlation(self):
        x = np.arange(100, dtype=float)
        pearson, rank = _compute_ic(x, -x)
        assert abs(pearson - (-1.0)) < 1e-10
        assert abs(rank - (-1.0)) < 1e-10

    def test_no_correlation(self):
        rng = np.random.default_rng(42)
        pearson, rank = _compute_ic(rng.standard_normal(1000), rng.standard_normal(1000))
        assert abs(pearson) < 0.15
        assert abs(rank) < 0.15

    def test_constant_array(self):
        pearson, rank = _compute_ic(np.ones(50), np.arange(50, dtype=float))
        assert pearson == 0.0
        assert rank == 0.0

    def test_nan_handling(self):
        pearson, rank = _compute_ic(
            np.array([1.0, 2.0, np.nan, 4.0, 5.0]),
            np.array([2.0, 4.0, 6.0, np.nan, 10.0]),
        )
        assert np.isfinite(pearson)
        assert np.isfinite(rank)

    def test_too_few_samples(self):
        pearson, rank = _compute_ic(
            np.array([1.0, 2.0, 3.0]), np.array([2.0, 4.0, 6.0]),
        )
        assert pearson == 0.0
        assert rank == 0.0

    def test_rank_ic_averages_tied_values(self):
        predictions = np.array([1.0, 1.0, 2.0, 3.0, 3.0])
        actuals = np.array([1.0, 2.0, 2.0, 3.0, 3.0])
        prediction_ranks = np.array([0.5, 0.5, 2.0, 3.5, 3.5])
        actual_ranks = np.array([0.0, 1.5, 1.5, 3.5, 3.5])

        _, rank = _compute_ic(predictions, actuals)

        expected = np.corrcoef(prediction_ranks, actual_ranks)[0, 1]
        assert rank == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Mean daily cross-sectional IC (index-aligned, per-day average)
# ---------------------------------------------------------------------------


class TestMeanDailyCrossSectionalIC:
    """Direct unit tests for _compute_mean_daily_ic — proves it returns the
    average of per-day cross-sectional ICs, not a single pooled IC."""

    @staticmethod
    def _mk_series(values, dates, instruments):
        """Build a Series with (datetime, instrument) MultiIndex."""
        idx = pd.MultiIndex.from_arrays(
            [dates, instruments], names=["datetime", "instrument"]
        )
        return pd.Series(values, index=idx)

    def test_differs_from_pooled_ic(self):
        """Mean daily CS IC = 0.0 (average of -1 and +1), but pooled IC is
        materially positive because date-level offsets dominate the single
        pooled regression (Simpson's paradox demonstration)."""
        # Day 1: perfect negative linear correlation (IC = -1.0)
        pred_day1 = [1.0, 2.0, 3.0, 4.0, 5.0]
        act_day1 = [5.0, 4.0, 3.0, 2.0, 1.0]

        # Day 2: perfect positive linear correlation (IC = +1.0)
        pred_day2 = [101.0, 102.0, 103.0, 104.0, 105.0]
        act_day2 = [202.0, 204.0, 206.0, 208.0, 210.0]

        pred = self._mk_series(
            pred_day1 + pred_day2,
            ["2024-01-02"] * 5 + ["2024-01-03"] * 5,
            ["A0", "A1", "A2", "A3", "A4", "B0", "B1", "B2", "B3", "B4"],
        )
        act = self._mk_series(
            act_day1 + act_day2,
            ["2024-01-02"] * 5 + ["2024-01-03"] * 5,
            ["A0", "A1", "A2", "A3", "A4", "B0", "B1", "B2", "B3", "B4"],
        )

        daily_pearson, daily_rank = _compute_mean_daily_ic(pred.values, act)
        pooled_pearson, pooled_rank = _compute_ic(pred.values, act.values)

        # Mean daily IC ≈ 0.0 (average of -1.0 + 1.0)
        assert abs(daily_pearson) < 0.01, (
            f"Expected mean daily Pearson ≈ 0.0, got {daily_pearson}"
        )
        assert abs(daily_rank) < 0.01, (
            f"Expected mean daily rank IC ≈ 0.0, got {daily_rank}"
        )
        # Pooled IC is materially positive (day-2 larger values dominate regression)
        assert pooled_pearson > 0.1, (
            f"Pooled Pearson IC {pooled_pearson} should be materially > 0"
        )
        assert pooled_rank > 0.1, (
            f"Pooled rank IC {pooled_rank} should be materially > 0"
        )
        assert abs(pooled_pearson - daily_pearson) > 0.1, (
            f"Pooled {pooled_pearson} should differ from mean daily {daily_pearson}"
        )
        assert abs(pooled_rank - daily_rank) > 0.1, (
            f"Pooled rank {pooled_rank} should differ from mean daily rank {daily_rank}"
        )

    def test_identical_when_single_day(self):
        """When there is only one date, mean daily CS IC equals pooled IC."""
        pred = self._mk_series(
            [1.0, 2.0, 3.0, 4.0, 5.0],
            ["2024-01-02"] * 5,
            ["A", "B", "C", "D", "E"],
        )
        act = self._mk_series(
            [2.0, 4.0, 6.0, 8.0, 10.0],
            ["2024-01-02"] * 5,
            ["A", "B", "C", "D", "E"],
        )
        daily_p, daily_r = _compute_mean_daily_ic(pred.values, act)
        pooled_p, pooled_r = _compute_ic(pred.values, act.values)
        assert abs(daily_p - pooled_p) < 1e-10
        assert abs(daily_r - pooled_r) < 1e-10

    def test_flat_index_falls_back_to_pooled(self):
        """Series with plain RangeIndex triggers pooled fallback."""
        pred = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        act = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])
        daily_p, daily_r = _compute_mean_daily_ic(pred, act)
        pooled_p, pooled_r = _compute_ic(pred, act.values)
        assert abs(daily_p - pooled_p) < 1e-10
        assert abs(daily_r - pooled_r) < 1e-10

    def test_skips_days_with_fewer_than_min_stocks(self):
        """Days with < min_stocks_per_day stocks are excluded from the mean."""
        pred = self._mk_series(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            ["2024-01-02", "2024-01-02"] + ["2024-01-03"] * 4,
            ["A", "B", "C", "D", "E", "F"],
        )
        act = self._mk_series(
            [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
            ["2024-01-02", "2024-01-02"] + ["2024-01-03"] * 4,
            ["A", "B", "C", "D", "E", "F"],
        )
        # Day 1 has only 2 stocks (< default min 3), so only day 2 contributes
        daily_p, _daily_r = _compute_mean_daily_ic(pred.values, act)
        # Day 2 has perfect IC ≈ 1.0
        assert abs(daily_p - 1.0) < 1e-10


class TestBenchmarkExcessLabel:
    def test_subtracts_same_date_benchmark_and_preserves_index(self):
        index = pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2025-01-02"), "AAPL"),
                (pd.Timestamp("2025-01-02"), "MSFT"),
                (pd.Timestamp("2025-01-03"), "AAPL"),
            ],
            names=["datetime", "instrument"],
        )
        stock_returns = pd.Series([0.10, 0.04, -0.02], index=index)
        benchmark_returns = pd.Series(
            [0.03, -0.01],
            index=pd.DatetimeIndex(["2025-01-02", "2025-01-03"], name="datetime"),
        )

        result = _subtract_benchmark_by_date(stock_returns, benchmark_returns)

        assert result.index.equals(stock_returns.index)
        assert result.to_numpy() == pytest.approx([0.07, 0.01, -0.01])

    def test_missing_benchmark_date_propagates_nan(self):
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2025-01-02"), "AAPL")],
            names=["datetime", "instrument"],
        )

        result = _subtract_benchmark_by_date(
            pd.Series([0.10], index=index), pd.Series(dtype=float)
        )

        assert result.isna().all()


# ---------------------------------------------------------------------------
# Index alignment: predictions matched to actuals by (date, instrument),
# not by array position
# ---------------------------------------------------------------------------


class TestIndexAlignment:
    """Proves that index alignment (as done in ``_run_single_split``) pairs
    predictions with their correct labels regardless of row ordering,
    unlike positional truncation which would silently pair wrong rows."""

    @staticmethod
    def _mk_series(values, dates, instruments):
        idx = pd.MultiIndex.from_arrays(
            [dates, instruments], names=["datetime", "instrument"]
        )
        return pd.Series(values, index=idx)

    def test_alignment_pipeline_corrects_ordering(self):
        """Simulate the alignment step from _run_single_split:
        intersect indices, reindex both, then compute mean daily CS IC."""
        # 5 stocks with row order scrambled between pred and act.
        # True pairs: A=(1,2), B=(2,4), C=(3,6), D=(4,8), E=(5,10).
        pred = self._mk_series(
            [2.0, 1.0, 5.0, 3.0, 4.0],
            ["d1"] * 5, ["B", "A", "E", "C", "D"],
        )
        act = self._mk_series(
            [6.0, 4.0, 2.0, 8.0, 10.0],
            ["d1"] * 5, ["C", "B", "A", "D", "E"],
        )

        # Alignment step (mirrors _run_single_split)
        common = pred.index.intersection(act.index)
        pred_aligned = pred.loc[common].values  # [1,2,3,4,5]  (A,B,C,D,E)
        act_aligned = act.loc[common]  # Series with [2,4,6,8,10]

        aligned_p, _aligned_r = _compute_mean_daily_ic(pred_aligned, act_aligned)
        assert abs(aligned_p - 1.0) < 1e-10, (
            f"Aligned IC should be 1.0 (perfect corr), got {aligned_p}"
        )

        # Without alignment: pred.values=[2,1,5,3,4] vs act.values=[6,4,2,8,10]
        positional_p, _positional_r = _compute_ic(pred.values, act.values)
        assert abs(positional_p - 1.0) > 0.1, (
            f"Positional IC {positional_p} should differ from aligned 1.0"
        )


class TestAlignMultiindex:
    """Unit tests for the shared ``_align_multiindex`` helper."""

    @staticmethod
    def _mk_series(values, dates, instruments):
        idx = pd.MultiIndex.from_arrays(
            [dates, instruments], names=["datetime", "instrument"]
        )
        return pd.Series(values, index=idx)

    def test_duplicate_index_rejected(self):
        """Duplicate (datetime, instrument) pairs must raise ValueError."""
        pred = self._mk_series(
            [1.0, 2.0], ["2024-01-02", "2024-01-02"], ["A", "A"]
        )
        act = self._mk_series(
            [2.0, 4.0], ["2024-01-02", "2024-01-03"], ["A", "B"]
        )

        with pytest.raises(ValueError, match=r"(?i)duplicate"):
            _align_multiindex(pred, act)

    def test_flat_index_rejected(self):
        """Non-MultiIndex must raise TypeError — no positional fallback."""
        pred = pd.Series([1.0, 2.0])
        act = pd.Series([2.0, 4.0])

        with pytest.raises(TypeError, match=r"(?i)MultiIndex"):
            _align_multiindex(pred, act)

    def test_missing_level_rejected(self):
        """MultiIndex without 'datetime' level must raise ValueError."""
        idx = pd.MultiIndex.from_arrays(
            [["A", "B"], ["2024-01-02", "2024-01-03"]],
            names=["instrument", "date"],
        )
        pred = pd.Series([1.0, 2.0], index=idx)
        act = pd.Series([2.0, 4.0], index=idx)

        with pytest.raises(ValueError, match=r"(?i)(datetime|level)"):
            _align_multiindex(pred, act)

    def test_no_common_pairs(self):
        """No common index entries must raise ValueError."""
        pred = self._mk_series(
            [1.0, 2.0], ["2024-01-02", "2024-01-03"], ["A", "B"]
        )
        act = self._mk_series(
            [2.0, 4.0], ["2024-01-04", "2024-01-05"], ["A", "B"]
        )

        with pytest.raises(ValueError, match=r"(?i)common"):
            _align_multiindex(pred, act)

    def test_successful_alignment(self):
        """Well-formed MultiIndex aligns correctly — both outputs share the
        deterministic canonical sorted common MultiIndex and values are
        matched by labels, never by position."""
        pred = self._mk_series(
            [2.0, 1.0], ["2024-01-02", "2024-01-02"], ["B", "A"]
        )
        act = self._mk_series(
            [6.0, 4.0], ["2024-01-02", "2024-01-02"], ["A", "B"]
        )

        aligned_a, aligned_b = _align_multiindex(pred, act)
        # Both aligned objects share identical sorted common MultiIndex
        assert aligned_a.index.equals(aligned_b.index), (
            "Aligned indexes must be identical"
        )
        assert list(aligned_a.index.get_level_values("instrument")) == ["A", "B"]
        assert list(aligned_b.index.get_level_values("instrument")) == ["A", "B"]
        # Values are matched by label: pred["A"]=1.0, pred["B"]=2.0 → [1.0, 2.0]
        assert list(aligned_a.values) == [1.0, 2.0]
        # act["A"]=6.0, act["B"]=4.0 → [6.0, 4.0]
        assert list(aligned_b.values) == [6.0, 4.0]


# ---------------------------------------------------------------------------


class TestRunSingleSplitBackwardCompat:
    """Pre-task edit: train/valid non-overlap via timedelta, preserved for
    label_horizon=0.
    """

    def test_label_horizon_zero_timedelta_gap(self, monkeypatch):
        captured = {}

        class FakeDataset:
            def prepare(self, segments, col_set, data_key):
                return pd.DataFrame(
                    {"label": np.arange(len(_FAKE_IDX), dtype=float)},
                    index=_FAKE_IDX,
                )

        class FakeModel:
            def fit(self, dataset):
                return None

            def predict(self, dataset, segment="test"):
                return pd.Series(
                    np.arange(len(_FAKE_IDX), dtype=float), index=_FAKE_IDX
                )

        def fake_init(config):
            if "handler" in config.get("kwargs", {}):
                captured["config"] = config
                return FakeDataset()
            return FakeModel()

        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config", fake_init)

        monkeypatch.setattr(
            "src.research.walk_forward._load_raw_labels",
            lambda cfg, ts, te: pd.Series(
                np.arange(len(_FAKE_IDX), dtype=float), index=_FAKE_IDX
            ),
        )

        base_config = {
            "task": {
                "dataset": {
                    "kwargs": {
                        "handler": {
                            "kwargs": {
                                "start_time": "2021-01-01",
                                "end_time": "2026-06-25",
                                "label": ["Ref($close, -1) / $close - 1"],
                                "data_loader": {
                                    "kwargs": {"config": {"label": ["Ref($close, -1) / $close - 1"]}}
                                },
                            }
                        },
                        "segments": {
                            "train": ["2021-01-01", "2024-12-31"],
                            "valid": ["2025-01-01", "2025-12-31"],
                            "test": ["2026-01-01", "2026-06-25"],
                        },
                    }
                },
                "model": {"kwargs": {}},
            }
        }

        result = _run_single_split(
            base_config=base_config, split_id=0,
            train_start="2021-01-01", train_end="2025-12-31",
            test_start="2026-01-01", test_end="2026-06-25",
            label_horizon=0,
        )

        segments = captured["config"]["kwargs"]["segments"]
        train_start_ts, train_end_ts = map(pd.Timestamp, segments["train"])
        valid_start_ts, valid_end_ts = map(pd.Timestamp, segments["valid"])
        test_start_ts, test_end_ts = map(pd.Timestamp, segments["test"])

        assert result.status == "success"
        assert (train_start_ts < train_end_ts < valid_start_ts
                < valid_end_ts < test_start_ts < test_end_ts)
        assert segments["train"] == ["2021-01-01", "2025-06-29"]
        assert segments["valid"] == ["2025-06-30", "2025-12-31"]
        assert segments["test"] == ["2026-01-01", "2026-06-25"]
        assert result.train_end == "2025-06-29"


# ---------------------------------------------------------------------------
# Shared fixtures for _run_single_split tests
# ---------------------------------------------------------------------------


def _build_weekday_calendar(start, n_days):
    """Build a DatetimeIndex of weekdays starting from *start*."""
    start_ts = pd.Timestamp(start)
    dates = [start_ts + pd.Timedelta(days=i) for i in range(n_days)
             if (start_ts + pd.Timedelta(days=i)).dayofweek < 5]
    return pd.DatetimeIndex(dates)


def _make_base_config():
    return {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "start_time": "2021-01-01",
                            "end_time": "2026-06-25",
                            "label": ["Ref($close, -1) / $close - 1"],
                            "data_loader": {
                                "kwargs": {"config": {"label": ["Ref($close, -1) / $close - 1"]}}
                            },
                        }
                    },
                    "segments": {
                        "train": ["2021-01-01", "2024-12-31"],
                        "valid": ["2025-01-01", "2025-12-31"],
                        "test": ["2026-01-01", "2026-06-25"],
                    },
                }
            },
            "model": {"kwargs": {}},
        }
    }


# MultiIndex fixture shared by fakes — 10 rows so alignments succeed.
_FAKE_IDX = pd.MultiIndex.from_product(
    [pd.DatetimeIndex(["2026-01-05", "2026-01-06"]), ["A", "B", "C", "D", "E"]],
    names=["datetime", "instrument"],
)


def _fake_init_instance_by_config(captured):
    class FakeDataset:
        def prepare(self, segments, col_set, data_key):
            return pd.DataFrame(
                {"label": np.arange(len(_FAKE_IDX), dtype=float)},
                index=_FAKE_IDX,
            )

    class FakeModel:
        def fit(self, dataset):
            return None

        def predict(self, dataset, segment="test"):
            return pd.Series(
                np.arange(len(_FAKE_IDX), dtype=float), index=_FAKE_IDX
            )

    def fake(config):
        if "handler" in config.get("kwargs", {}):
            captured["config"] = config
            return FakeDataset()
        return FakeModel()

    return fake


# ---------------------------------------------------------------------------
# Focused default-horizon gap test: irregular calendar, boundary absent
# ---------------------------------------------------------------------------


class TestDefaultHorizonGap:
    """Proves label_horizon=10 creates exactly 10 observed-session gaps
    between label-bearing segments and the following segment, even when
    the calendar has holiday gaps and the boundary is non-trading.  Also
    proves SplitResult.train_end equals the effective segment endpoint."""

    def test_irregular_calendar_boundary_absent(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config(captured),
        )
        monkeypatch.setattr(
            "src.research.walk_forward._load_raw_labels",
            lambda cfg, ts, te: pd.Series(
                np.arange(len(_FAKE_IDX), dtype=float), index=_FAKE_IDX
            ),
        )

        # Irregular DatetimeIndex with holiday gaps + boundary absent
        cal_start = pd.Timestamp("2020-06-01")
        all_wd = pd.DatetimeIndex([
            cal_start + pd.Timedelta(days=i)
            for i in range(3200)
            if (cal_start + pd.Timedelta(days=i)).dayofweek < 5
        ])
        holidays = {
            pd.Timestamp("2021-12-24"), pd.Timestamp("2022-12-26"),
            pd.Timestamp("2023-12-25"), pd.Timestamp("2024-12-25"),
            pd.Timestamp("2025-12-25"), pd.Timestamp("2025-12-26"),  # Thu-Fri gap
            # 2026-01-01 (New Year) is absent -- boundary absent scenario
        }
        cal = all_wd[~all_wd.isin(holidays)]
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal,
        )

        # label_horizon=10 (default); test_start=2026-01-01 absent from cal
        result = _run_single_split(
            base_config=_make_base_config(), split_id=0,
            train_start="2021-01-01", train_end="2025-12-31",
            test_start="2026-01-01", test_end="2026-06-25",
            label_horizon=10,
        )

        assert result.status == "success"
        segments = captured["config"]["kwargs"]["segments"]

        train_end_ts = pd.Timestamp(segments["train"][1])
        valid_start_ts = pd.Timestamp(segments["valid"][0])
        valid_end_ts = pd.Timestamp(segments["valid"][1])
        test_start_ts = pd.Timestamp(segments["test"][0])

        # Chronological order holds
        assert train_end_ts < valid_start_ts < valid_end_ts < test_start_ts

        # Exactly 10 observed sessions at BOTH boundaries
        gap_train_valid = cal[(cal > train_end_ts) & (cal < valid_start_ts)]
        assert len(gap_train_valid) == 10, (
            f"Expected 10 sessions train->valid, got {len(gap_train_valid)}: "
            f"{gap_train_valid.tolist()}"
        )
        gap_valid_test = cal[(cal > valid_end_ts) & (cal < test_start_ts)]
        assert len(gap_valid_test) == 10, (
            f"Expected 10 sessions valid->test, got {len(gap_valid_test)}: "
            f"{gap_valid_test.tolist()}"
        )

        # Ref(-10)'s furthest observation from train_end stays before valid_start
        train_end_pos = cal.get_loc(train_end_ts)
        assert cal[train_end_pos + 10] < valid_start_ts, (
            f"Label at {train_end_ts.date()} peeks to "
            f"{cal[train_end_pos + 10].date()}, not before "
            f"valid_start={valid_start_ts.date()}"
        )

        # SplitResult.train_end equals the effective segment endpoint
        assert result.train_end == segments["train"][1]
        assert result.train_end != "2025-12-31"


# ---------------------------------------------------------------------------
# Fail-closed: empty calendar
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Calendar validation must fail closed for every integrity violation."""

    def test_holiday_start_and_weekend_end_are_valid_coverage(self):
        calendar = pd.bdate_range("2021-01-04", "2021-01-08")

        _validate_calendar(calendar, "2021-01-01", "2021-01-10")

    def test_empty_calendar_raises(self, monkeypatch):
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: pd.DatetimeIndex([]),
        )
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config({}),
        )
        with pytest.raises(RuntimeError, match=r"(?i)(calendar|trading)"):
            _run_single_split(
                base_config=_make_base_config(), split_id=0,
                train_start="2021-01-01", train_end="2025-12-31",
                test_start="2026-01-01", test_end="2026-06-25",
                label_horizon=10,
            )

    def test_too_short_calendar_raises(self, monkeypatch):
        """Calendar with fewer days than label_horizon must fail closed."""
        tiny_cal = pd.DatetimeIndex(
            [pd.Timestamp("2021-01-04"), pd.Timestamp("2021-01-05")]
        )
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: tiny_cal,
        )
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config({}),
        )
        with pytest.raises(RuntimeError, match=r"(?i)(calendar|trading|short)"):
            _run_single_split(
                base_config=_make_base_config(), split_id=0,
                train_start="2021-01-01", train_end="2025-12-31",
                test_start="2026-01-01", test_end="2026-06-25",
                label_horizon=10,  # 10 > 2
            )

    def test_unordered_calendar_raises(self, monkeypatch):
        """Non-monotonic calendar must fail closed."""
        cal = pd.DatetimeIndex([
            pd.Timestamp("2021-01-05"),
            pd.Timestamp("2021-01-04"),  # reversed
            pd.Timestamp("2021-01-06"),
        ])
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal,
        )
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config({}),
        )
        with pytest.raises(RuntimeError, match=r"(?i)(monoton|order|unordered)"):
            _run_single_split(
                base_config=_make_base_config(), split_id=0,
                train_start="2021-01-01", train_end="2025-12-31",
                test_start="2026-01-01", test_end="2026-06-25",
                label_horizon=10,
            )

    def test_duplicate_calendar_raises(self, monkeypatch):
        """Duplicate dates in calendar must fail closed."""
        cal = pd.DatetimeIndex([
            pd.Timestamp("2021-01-04"),
            pd.Timestamp("2021-01-04"),  # duplicate
            pd.Timestamp("2021-01-05"),
        ])
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal,
        )
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config({}),
        )
        with pytest.raises(RuntimeError, match=r"(?i)(duplicate)"):
            _run_single_split(
                base_config=_make_base_config(), split_id=0,
                train_start="2021-01-01", train_end="2025-12-31",
                test_start="2026-01-01", test_end="2026-06-25",
                label_horizon=10,
            )

    def test_stale_calendar_coverage_raises(self, monkeypatch):
        """Calendar ending before test_end is incomplete/stale coverage."""
        cal = _build_weekday_calendar("2021-01-01", 200)  # ends ~mid-2021
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal,
        )
        monkeypatch.setattr(
            "src.research.walk_forward.init_instance_by_config",
            _fake_init_instance_by_config({}),
        )
        with pytest.raises(RuntimeError, match=r"(?i)(end|coverage|stale|incomplete)"):
            _run_single_split(
                base_config=_make_base_config(), split_id=0,
                train_start="2021-01-01", train_end="2025-12-31",
                test_start="2026-01-01", test_end="2026-06-25",
                label_horizon=10,
            )


# ---------------------------------------------------------------------------
# Public-path: walk_forward_validate with label_horizon omitted
# ---------------------------------------------------------------------------


class TestWalkForwardValidateDefault:
    def test_omitted_label_horizon_defaults_10(self, monkeypatch, tmp_path):
        captured_horizons = []

        def fake_run_single_split(
            base_config, split_id, train_start, train_end,
            test_start, test_end, label_horizon=10,
        ):
            captured_horizons.append(label_horizon)
            return SplitResult(
                split_id=split_id, train_start=train_start,
                train_end=train_end, test_start=test_start, test_end=test_end,
                ic=0.05, rank_ic=0.04, status="success",
            )

        monkeypatch.setattr(
            "src.research.walk_forward._run_single_split", fake_run_single_split)
        monkeypatch.setattr(
            "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
        monkeypatch.setattr(
            "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})

        config_file = tmp_path / "us_lgbm_workflow.yaml"
        config_file.write_text("task:\n  model:\n    kwargs: {}\n")
        monkeypatch.setattr("src.common.paths.CONFIG_DIR", tmp_path)

        walk_forward_validate(
            market="us", model_type="lgbm",
            train_start="2021-01-01", train_end="2025-12-31",
        )

        assert len(captured_horizons) > 0
        assert all(h == 10 for h in captured_horizons), (
            f"Expected label_horizon=10, got {captured_horizons}")


# ---------------------------------------------------------------------------
# Public-path: walk_forward_vectorized with label_horizon omitted
# ---------------------------------------------------------------------------


class TestWalkForwardVectorizedDefault:
    def test_omitted_label_horizon_purges_train_mask(self, monkeypatch, tmp_path):
        """Public vectorized API defaults label_horizon=10 → 10-session gap
        between the effective train-end mask cutoff and the test-start boundary
        (the train→test purge)."""
        import importlib
        import sys
        from types import ModuleType
        cal = _build_weekday_calendar("2024-01-01", 800)

        monkeypatch.setattr(
            "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
        monkeypatch.setattr(
            "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal)

        # chdir so Path("data/watchlist/...") resolves inside tmp_path
        instr_dir = tmp_path / "data" / "watchlist" / "instruments"
        instr_dir.mkdir(parents=True)
        (instr_dir / "cn.txt").write_text("A\nB\n")
        monkeypatch.chdir(tmp_path)

        # Need ≥3 instruments so select_stable_features (min_instruments_per_day=3)
        # does not filter out all days.
        instruments = ["A", "B", "C"]
        dates = cal[cal >= pd.Timestamp("2024-01-01")]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"])
        rng = np.random.default_rng(42)
        # 3 features with known IC direction so selection returns ≥1 feature.
        base = rng.standard_normal((len(idx), 1))
        X_df = pd.DataFrame(
            np.column_stack([base, base * 0.9 + 0.1, base * 1.1 - 0.1]),
            index=idx, columns=["feat_a", "feat_b", "feat_c"])
        y_df = pd.DataFrame(
            base * 0.5 + 0.05, index=idx, columns=["label"])

        _feat_call = [0]

        class _FakeD:
            @staticmethod
            def features(symbols, expressions, start_time=None, end_time=None):
                _feat_call[0] += 1
                return X_df if _feat_call[0] == 1 else y_df

        loader_module = importlib.import_module("qlib.contrib.data.loader")

        # Provide a mock qlib.data module via sys.modules so the
        # ``from qlib.data import D`` inside walk_forward_vectorized
        # succeeds without requiring a real qlib initialization.
        mock_qlib_data = ModuleType("qlib.data")
        mock_qlib_data.D = _FakeD
        monkeypatch.setitem(sys.modules, "qlib.data", mock_qlib_data)

        class _FakeAlpha:
            @staticmethod
            def get_feature_config(cfg):
                return (["$close"], {})

        monkeypatch.setattr(loader_module, "Alpha158DL", _FakeAlpha)

        class _FakeBooster:
            def predict(self, X):
                return np.zeros(len(X))

        lightgbm_module = importlib.import_module("lightgbm")
        monkeypatch.setattr(
            lightgbm_module, "train",
            lambda params, train_set, num_boost_round: _FakeBooster())

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=1, step_months=1, n_estimators=1,
        )

        assert len(result.splits) > 0
        for sr in result.splits:
            if sr.status == "success":
                te_ts = pd.Timestamp(sr.train_end)
                ts_ts = pd.Timestamp(sr.test_start)
                assert te_ts < ts_ts
                gap = cal[(cal > te_ts) & (cal < ts_ts)]
                # Gap includes validation window + 2×10 session purges (≥20).
                assert len(gap) >= 20, (
                    f"Split {sr.split_id}: gap={len(gap)}, expected ≥20 "
                    f"(train→valid purge + valid window + valid→test purge)")


# ---------------------------------------------------------------------------
# API tests (preserved from original with pre-task _run_wf_job monkeypatch)
# ---------------------------------------------------------------------------


class TestWalkForwardAPI:
    """Test the FastAPI walk-forward endpoints."""

    def test_start_walk_forward_returns_job_id(self, monkeypatch):
        monkeypatch.setattr(walk_forward_router, "_run_wf_job",
                            lambda job_id, payload: None)

        app = FastAPI()
        app.include_router(walk_forward_router.router)
        client = TestClient(app)

        resp = client.post("/walk-forward", json={
            "market": "us", "model_type": "lgbm",
            "train_start": "2021-01-01", "train_end": "2025-12-31",
            "test_window_months": 6, "step_months": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "job_id" in data
        assert len(data["job_id"]) == 12

    def test_get_result_unknown_job(self):
        app = FastAPI()
        app.include_router(wf_router)
        client = TestClient(app)
        resp = client.get("/walk-forward/nonexistent")
        assert resp.status_code == 404

    def test_get_result_after_submit(self, monkeypatch):
        monkeypatch.setattr(walk_forward_router, "_run_wf_job",
                            lambda job_id, payload: None)

        app = FastAPI()
        app.include_router(walk_forward_router.router)
        client = TestClient(app)

        post_resp = client.post(
            "/walk-forward", json={"market": "us", "model_type": "lgbm"})
        job_id = post_resp.json()["job_id"]

        get_resp = client.get(f"/walk-forward/{job_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("pending", "running", "succeeded", "failed")


# ---------------------------------------------------------------------------
# Vectorized WF: per-split feature selection + validation window + dual gaps
# ---------------------------------------------------------------------------


def _build_weekday_calendar_v2(start, n_days):
    """Build a DatetimeIndex of weekdays starting from *start*."""
    start_ts = pd.Timestamp(start)
    dates = [start_ts + pd.Timedelta(days=i) for i in range(n_days)
             if (start_ts + pd.Timedelta(days=i)).dayofweek < 5]
    return pd.DatetimeIndex(dates)


def _setup_vectorized_wf_mocks(monkeypatch, tmp_path, n_instruments=5, n_features=5):
    """Install a complete mock harness for walk_forward_vectorized.

    Returns (calendar, captured) where *captured* is a dict populated with:
      - select_calls: list of (train_X, train_y, valid_X, valid_y) per split
      - train_calls: list of kwarg dicts from lgb.train calls
    """
    import importlib
    import sys
    from types import ModuleType

    cal = _build_weekday_calendar_v2("2024-01-01", 800)

    monkeypatch.setattr(
        "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
    monkeypatch.setattr(
        "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})
    monkeypatch.setattr(
        "src.research.walk_forward._get_trading_calendar",
        lambda start, end: cal)

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    instruments = [f"S{i}" for i in range(n_instruments)]
    (instr_dir / "cn.txt").write_text("\n".join(instruments))
    monkeypatch.chdir(tmp_path)

    dates = cal[cal >= pd.Timestamp("2024-01-01")]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"])
    rng = np.random.default_rng(42)

    # Features: correlated with labels so selection finds stable features.
    base = rng.standard_normal((len(idx), 1))
    feat_cols = {}
    for i in range(n_features):
        feat_cols[f"feat_{i}"] = (base * (0.8 + 0.4 * i / n_features)
                                  + rng.standard_normal((len(idx), 1)) * 0.3).ravel()
    X_df = pd.DataFrame(feat_cols, index=idx)
    y_df = pd.DataFrame(base * 0.6 + 0.02, index=idx, columns=["label"])

    _feat_call = [0]

    class _FakeD:
        @staticmethod
        def features(symbols, expressions, start_time=None, end_time=None):
            _feat_call[0] += 1
            return X_df if _feat_call[0] == 1 else y_df

    loader_module = importlib.import_module("qlib.contrib.data.loader")

    mock_qlib_data = ModuleType("qlib.data")
    mock_qlib_data.D = _FakeD
    monkeypatch.setitem(sys.modules, "qlib.data", mock_qlib_data)

    class _FakeAlpha:
        @staticmethod
        def get_feature_config(cfg):
            return ([f"$close_{i}" for i in range(n_features)], {})

    monkeypatch.setattr(loader_module, "Alpha158DL", _FakeAlpha)

    captured = {"select_calls": [], "train_calls": [], "y_df": y_df}
    lightgbm_module = importlib.import_module("lightgbm")

    def _fake_train(params, train_set, num_boost_round=100,
                    valid_sets=None, feval=None, callbacks=None):
        captured["train_calls"].append({
            "params": dict(params) if params else {},
            "valid_sets": valid_sets,
            "feval": feval,
            "callbacks": callbacks,
        })
        booster = SimpleNamespace()
        booster.best_iteration = 1
        booster.best_score = {"valid_0": {"mean_daily_cs_ic": 0.05}}
        booster.predict = lambda X: np.zeros(len(X))
        return booster

    monkeypatch.setattr(lightgbm_module, "train", _fake_train)
    monkeypatch.setattr(lightgbm_module, "Dataset",
                        lambda data, label=None, reference=None: data)

    return cal, captured


class TestVectorizedWFPerSplitSelection:
    """Prove walk_forward_vectorized reselects features per split and the
    selector NEVER sees test data."""

    def test_selector_called_per_split(self, monkeypatch, tmp_path):
        """select_stable_features must be called once per successful split."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        # Wrap select_stable_features to capture calls AND return valid result.
        from src.research.cross_sectional_training import select_stable_features as _orig_select

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            captured["select_calls"].append({
                "train_dates": set(train_X.index.get_level_values("datetime")),
                "valid_dates": set(valid_X.index.get_level_values("datetime")),
            })
            return _orig_select(train_X, train_y, valid_X, valid_y,
                                max_features=max_features,
                                min_instruments_per_day=min_instruments_per_day)

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        # Each successful split calls select_stable_features exactly once.
        assert len(captured["select_calls"]) == n_success
        assert n_success > 0, "Expected at least one successful split"

    def test_selector_never_sees_test_data(self, monkeypatch, tmp_path):
        """For every split, the test dates must not appear in train or valid
        data passed to select_stable_features."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            captured["select_calls"].append({
                "train_dates": set(train_X.index.get_level_values("datetime")),
                "valid_dates": set(valid_X.index.get_level_values("datetime")),
            })
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        success_idx = 0
        for i, sr in enumerate(result.splits):
            if sr.status != "success":
                continue
            call = captured["select_calls"][success_idx]
            success_idx += 1
            test_dates = set(pd.date_range(sr.test_start, sr.test_end, freq="B"))
            # Test dates must not leak into train or valid.
            train_overlap = call["train_dates"] & test_dates
            valid_overlap = call["valid_dates"] & test_dates
            assert not train_overlap, (
                f"Split {i}: train data contains {len(train_overlap)} test dates"
            )
            assert not valid_overlap, (
                f"Split {i}: valid data contains {len(valid_overlap)} test dates"
            )

    def test_deterministic_params_per_split(self, monkeypatch, tmp_path):
        """Every split must use deterministic regularized LGBM params + feval."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        assert len(captured["train_calls"]) == n_success
        for i, call in enumerate(captured["train_calls"]):
            p = call["params"]
            assert p.get("seed") == 42, f"Split {i}: seed != 42"
            for seed_param in (
                "feature_fraction_seed",
                "bagging_seed",
                "data_random_seed",
                "drop_seed",
            ):
                assert p.get(seed_param) == 42, f"Split {i}: {seed_param} != 42"
            assert p.get("deterministic") is True, f"Split {i}: deterministic != True"
            assert p.get("force_col_wise") is True, f"Split {i}: force_col_wise != True"
            assert p.get("metric") == "None", f"Split {i}: metric not disabled"
            assert p.get("feature_fraction") == 1.0, f"Split {i}: feature_fraction != 1"
            assert p.get("bagging_fraction") == 1.0, f"Split {i}: bagging_fraction != 1"
            assert p.get("learning_rate") == 0.03, f"Split {i}: learning_rate != .03"
            assert "first_metric_only" not in p
            assert call["feval"] is not None, f"Split {i}: feval not passed"
            assert call["valid_sets"] is not None, f"Split {i}: valid_sets not passed"
            assert any(
                getattr(callback, "first_metric_only", False)
                for callback in call["callbacks"]
            )

    def test_both_boundaries_have_10_session_gaps(self, monkeypatch, tmp_path):
        """Prove exactly 10 observed sessions between train→valid and
        valid→test boundaries for every successful split."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        # Intercept lgb.train to read the validation index from feval
        # and also capture the train/valid/test slices via select_stable_features.
        boundary_gaps = []

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            train_dates = sorted(train_X.index.get_level_values("datetime").unique())
            valid_dates = sorted(valid_X.index.get_level_values("datetime").unique())
            boundary_gaps.append({
                "last_train": train_dates[-1] if train_dates else None,
                "first_valid": valid_dates[0] if valid_dates else None,
                "last_valid": valid_dates[-1] if valid_dates else None,
                # first_test will be captured after we know the split's test_start
            })
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        success_idx = 0
        for sr in result.splits:
            if sr.status != "success":
                continue
            bg = boundary_gaps[success_idx]
            bg["first_test"] = pd.Timestamp(sr.test_start)
            success_idx += 1

        for i, bg in enumerate(boundary_gaps):
            last_train = bg["last_train"]
            first_valid = bg["first_valid"]
            last_valid = bg["last_valid"]
            first_test = bg["first_test"]

            assert last_train is not None, f"Split {i}: missing last_train"
            assert first_valid is not None, f"Split {i}: missing first_valid"
            assert last_valid is not None, f"Split {i}: missing last_valid"
            assert first_test is not None, f"Split {i}: missing first_test"

            # Train→valid gap: exactly 10 observed sessions.
            gap_tv = cal[(cal > last_train) & (cal < first_valid)]
            assert len(gap_tv) == 10, (
                f"Split {i}: train→valid gap = {len(gap_tv)}, expected 10. "
                f"last_train={last_train.date()}, first_valid={first_valid.date()}, "
                f"gap_dates={[d.date() for d in gap_tv[:15]]}"
            )

            # Valid→test gap: exactly 10 observed sessions.
            gap_vt = cal[(cal > last_valid) & (cal < first_test)]
            assert len(gap_vt) == 10, (
                f"Split {i}: valid→test gap = {len(gap_vt)}, expected 10. "
                f"last_valid={last_valid.date()}, first_test={first_test.date()}, "
                f"gap_dates={[d.date() for d in gap_vt[:15]]}"
            )

    def test_train_valid_test_chronological_and_disjoint(self, monkeypatch, tmp_path):
        """Train, valid, test date ranges must be chronological and disjoint."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        select_data = []

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            select_data.append({
                "train_dates": set(train_X.index.get_level_values("datetime")),
                "valid_dates": set(valid_X.index.get_level_values("datetime")),
                "train_max": train_X.index.get_level_values("datetime").max(),
                "valid_min": valid_X.index.get_level_values("datetime").min(),
                "valid_max": valid_X.index.get_level_values("datetime").max(),
            })
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        success_idx = 0
        for sr in result.splits:
            if sr.status != "success":
                continue
            sd = select_data[success_idx]
            test_dates = set(pd.date_range(sr.test_start, sr.test_end, freq="B"))

            # Chronological: last_train < first_valid < last_valid < first_test
            assert sd["train_max"] < sd["valid_min"], (
                f"Split {sr.split_id}: train_max {sd['train_max'].date()} "
                f">= valid_min {sd['valid_min'].date()}"
            )
            assert sd["valid_max"] < pd.Timestamp(sr.test_start), (
                f"Split {sr.split_id}: valid_max {sd['valid_max'].date()} "
                f">= test_start {sr.test_start}"
            )

            # Disjoint
            assert not sd["train_dates"] & sd["valid_dates"], (
                f"Split {sr.split_id}: train/valid overlap"
            )
            assert not sd["valid_dates"] & test_dates, (
                f"Split {sr.split_id}: valid/test overlap"
            )
            assert not sd["train_dates"] & test_dates, (
                f"Split {sr.split_id}: train/test overlap"
            )

            success_idx += 1

        assert success_idx > 0, "Expected at least one successful split"

    def test_effective_train_end_reported_truthfully(self, monkeypatch, tmp_path):
        """SplitResult.train_end must be safe_train_end (the purged endpoint),
        not the original nominal train_end."""
        cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        for sr in result.splits:
            if sr.status == "success":
                # train_end must be strictly before test_start
                te_ts = pd.Timestamp(sr.train_end)
                ts_ts = pd.Timestamp(sr.test_start)
                assert te_ts < ts_ts, (
                    f"Split {sr.split_id}: train_end={sr.train_end} "
                    f"not before test_start={sr.test_start}"
                )
                # train_end must not equal the nominal train_end for the split
                # (it must be purged back for the validation window + label horizon)
                assert sr.train_end != sr.test_start, (
                    f"Split {sr.split_id}: train_end should differ from test_start"
                )

    def test_zero_horizon_keeps_validation_before_test(self, monkeypatch, tmp_path):
        """Zero horizon removes only the extra purge, not segment isolation."""
        _cal, captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)
        validation_ends = []

        def _capture_select(train_X, train_y, valid_X, valid_y, **kwargs):
            validation_ends.append(valid_X.index.get_level_values("datetime").max())
            feature = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feature], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )
        result = walk_forward_vectorized(
            market="cn",
            train_start="2024-01-01",
            train_end="2025-12-15",
            test_window_months=3,
            step_months=3,
            n_estimators=1,
            label_horizon=0,
        )

        successful = [split for split in result.splits if split.status == "success"]
        assert len(validation_ends) == len(successful) > 0
        for valid_end, split in zip(validation_ends, successful):
            assert valid_end < pd.Timestamp(split.test_start)


# ---------------------------------------------------------------------------
# Vectorized WF: lambdarank mode
# ---------------------------------------------------------------------------


def _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path, n_instruments=10, n_features=5):
    """Like _setup_vectorized_wf_mocks but also captures Dataset(group=...) calls.

    Returns (calendar, captured) where *captured* additionally contains
    ``dataset_calls`` (list of dicts with data, label, group keys).
    """
    cal, captured = _setup_vectorized_wf_mocks(
        monkeypatch, tmp_path, n_instruments=n_instruments, n_features=n_features
    )
    lightgbm_module = __import__("lightgbm")

    dataset_calls = []

    def _fake_dataset(data, label=None, reference=None, group=None):
        dataset_calls.append({"data": data, "label": label, "group": group})
        return data

    monkeypatch.setattr(lightgbm_module, "Dataset", _fake_dataset)
    captured["dataset_calls"] = dataset_calls
    return cal, captured


class TestVectorizedWFLambdarank:
    """Prove walk_forward_vectorized(training_objective='lambdarank') uses
    lambdarank objective, group-aware Datasets, and continuous feval per split."""

    def test_lambdarank_objective_per_split(self, monkeypatch, tmp_path):
        """Every successful split must have objective='lambdarank' in params."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        assert n_success > 0, "Expected at least one successful split"
        assert len(captured["train_calls"]) == n_success
        for i, tc in enumerate(captured["train_calls"]):
            assert tc["params"].get("objective") == "lambdarank", (
                f"Split {i}: objective must be lambdarank"
            )

    def test_dataset_groups_set_per_split(self, monkeypatch, tmp_path):
        """Every split must pass group to Dataset (two calls per split: train+valid)."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        expected_ds_calls = n_success * 2  # train + valid per split
        assert len(captured["dataset_calls"]) == expected_ds_calls, (
            f"Expected {expected_ds_calls} Dataset calls, got {len(captured['dataset_calls'])}"
        )
        for i, dc in enumerate(captured["dataset_calls"]):
            assert dc["group"] is not None, f"Dataset call {i}: group must not be None"
            assert isinstance(dc["group"], (list, np.ndarray)), (
                f"Dataset call {i}: group must be array-like, got {type(dc['group'])}"
            )

    def test_labels_are_integer_relevance(self, monkeypatch, tmp_path):
        """Dataset labels in lambdarank mode must be integer bins 0..4."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        for i, dc in enumerate(captured["dataset_calls"]):
            label_arr = np.asarray(dc["label"])
            assert np.issubdtype(label_arr.dtype, np.integer) or np.all(label_arr == label_arr.astype(int)), (
                f"Dataset call {i}: labels not integer"
            )
            assert label_arr.min() >= 0, f"Dataset call {i}: label min < 0"
            assert label_arr.max() <= 4, f"Dataset call {i}: label max > 4"

    def test_non_finite_labels_are_filtered_before_grouping(self, monkeypatch, tmp_path):
        """NaN targets must be removed from X/y before relevance grouping."""
        _cal, captured = _setup_vectorized_wf_lambdarank_mocks(
            monkeypatch, tmp_path
        )
        captured["y_df"].iloc[::97, 0] = np.nan

        from src.research.cross_sectional_training import (
            compute_relevance_labels as original_compute_relevance_labels,
        )

        observed_lengths = []

        def _capture_finite_labels(y, n_bins=5):
            assert np.isfinite(y.to_numpy(dtype=float)).all()
            labels, groups = original_compute_relevance_labels(y, n_bins=n_bins)
            assert int(groups.sum()) == len(labels) == len(y)
            observed_lengths.append(len(y))
            return labels, groups

        monkeypatch.setattr(
            "src.research.cross_sectional_training.compute_relevance_labels",
            _capture_finite_labels,
        )

        result = walk_forward_vectorized(
            market="cn",
            train_start="2024-01-01",
            train_end="2025-12-15",
            test_window_months=3,
            step_months=3,
            n_estimators=1,
            training_objective="lambdarank",
        )

        n_success = sum(split.status == "success" for split in result.splits)
        assert n_success > 0
        assert len(observed_lengths) == n_success * 2

    def test_feval_passed_per_split(self, monkeypatch, tmp_path):
        """feval must be passed in lambdarank mode for every split."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        assert len(captured["train_calls"]) == n_success
        for i, tc in enumerate(captured["train_calls"]):
            assert tc["feval"] is not None, f"Split {i}: feval must be passed"

    def test_deterministic_params_preserved(self, monkeypatch, tmp_path):
        """Deterministic + regularized params must be preserved in lambdarank mode."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        for i, tc in enumerate(captured["train_calls"]):
            p = tc["params"]
            assert p.get("seed") == 42, f"Split {i}: seed"
            assert p.get("deterministic") is True, f"Split {i}: deterministic"
            assert p.get("force_col_wise") is True, f"Split {i}: force_col_wise"
            assert p.get("lambda_l2") == 10.0, f"Split {i}: lambda_l2"
            assert p.get("num_leaves") == 15, f"Split {i}: num_leaves"
            assert p.get("metric") == "None", f"Split {i}: metric"

    def test_default_regression_mode_not_affected(self, monkeypatch, tmp_path):
        """Default training_objective must remain 'regression' (no groups)."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            # training_objective NOT passed → default 'regression'
        )

        # Regression: Dataset should have group=None
        for i, dc in enumerate(captured["dataset_calls"]):
            assert dc["group"] is None, f"Dataset call {i}: regression must not set group"
        # Objective must be 'regression'
        for i, tc in enumerate(captured["train_calls"]):
            assert tc["params"].get("objective") == "regression", f"Split {i}: objective"

    def test_no_test_leakage(self, monkeypatch, tmp_path):
        """Test data must not appear in train or valid DataFrames (same as regression)."""
        cal, captured = _setup_vectorized_wf_lambdarank_mocks(monkeypatch, tmp_path)

        # Wrap select_stable_features to capture dates
        select_dates = []

        def _capture_select(train_X, train_y, valid_X, valid_y, **kwargs):
            select_dates.append({
                "train_dates": set(train_X.index.get_level_values("datetime")),
                "valid_dates": set(valid_X.index.get_level_values("datetime")),
            })
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            training_objective="lambdarank",
        )

        success_idx = 0
        for sr in result.splits:
            if sr.status != "success":
                continue
            sd = select_dates[success_idx]
            test_dates = set(pd.date_range(sr.test_start, sr.test_end, freq="B"))
            assert not sd["train_dates"] & test_dates, (
                f"Split {sr.split_id}: train overlaps test"
            )
            assert not sd["valid_dates"] & test_dates, (
                f"Split {sr.split_id}: valid overlaps test"
            )
            success_idx += 1

    def test_curated_profile_uses_small_unconstrained_ranker(
        self, monkeypatch, tmp_path
    ):
        _cal, captured = _setup_vectorized_wf_lambdarank_mocks(
            monkeypatch, tmp_path
        )

        result = walk_forward_vectorized(
            market="cn",
            train_start="2024-01-01",
            train_end="2025-12-15",
            test_window_months=3,
            step_months=3,
            n_estimators=1,
            training_objective="lambdarank",
            feature_profile="curated_us_momentum",
        )

        assert any(split.status == "success" for split in result.splits)
        for call in captured["train_calls"]:
            params = call["params"]
            assert params["max_depth"] == 3
            assert params["num_leaves"] == 7
            assert "monotone_constraints" not in params


def test_forward_return_expression_tracks_positive_horizon():
    assert _forward_return_expression(20) == (
        "Ref($close, -20) / Ref($close, -1) - 1"
    )
    assert _forward_return_expression(10) == (
        "Ref($close, -10) / Ref($close, -1) - 1"
    )


# ---------------------------------------------------------------------------
# Minimum training history (min_train_months) protocol
# ---------------------------------------------------------------------------


class TestMinTrainMonths:
    """min_train_months must be enforced in split generation and fail closed.

    The first test_start must be exactly train_start + min_train_months.
    Default is 12 for backward compatibility.
    """

    def test_default_12_month_first_boundary(self):
        """Default min_train_months=12: first test_start = train_start + 12mo."""
        splits = generate_splits(
            train_start="2021-01-01", train_end="2025-12-31",
            test_window_months=6, step_months=3,
        )
        assert len(splits) > 0
        _, _, test_start, _ = splits[0]
        assert test_start == "2022-01-01"

    def test_explicit_36_month_first_boundary(self):
        """min_train_months=36: first test_start = train_start + 36mo."""
        splits = generate_splits(
            train_start="2021-01-01", train_end="2025-12-31",
            test_window_months=6, step_months=3,
            min_train_months=36,
        )
        assert len(splits) > 0
        _, _, test_start, _ = splits[0]
        assert test_start == "2024-01-01"

    def test_explicit_6_month_first_boundary(self):
        """min_train_months=6: first test_start = train_start + 6mo."""
        splits = generate_splits(
            train_start="2021-01-01", train_end="2023-06-30",
            test_window_months=3, step_months=3,
            min_train_months=6,
        )
        assert len(splits) > 0
        _, _, test_start, _ = splits[0]
        assert test_start == "2021-07-01"

    def test_no_splits_when_range_below_minimum(self):
        """When train_start + min_train_months > train_end, 0 splits."""
        splits = generate_splits(
            train_start="2025-01-01", train_end="2025-12-01",
            test_window_months=6, step_months=3,
            min_train_months=36,
        )
        assert len(splits) == 0

    def test_invalid_zero_raises(self):
        """min_train_months=0 must raise ValueError."""
        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            generate_splits(min_train_months=0)

    def test_invalid_negative_raises(self):
        """min_train_months=-1 must raise ValueError."""
        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            generate_splits(min_train_months=-1)

    def test_vectorized_default_first_test_start(self, monkeypatch, tmp_path):
        """Default min_train_months=12 in vectorized WF produces correct
        first test_start (train_start + 12mo)."""
        cal, _captured = _setup_vectorized_wf_mocks(monkeypatch, tmp_path)

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2025-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
        )

        assert len(result.splits) > 0
        first_ts = result.splits[0].test_start
        # train_start=2024-01-01 + 12mo(min_train_months default) = 2025-01-01
        assert first_ts == "2025-01-01", (
            f"Expected first test_start=2025-01-01, got {first_ts}"
        )

    def test_vectorized_invalid_min_train_months_raises(self, monkeypatch):
        """walk_forward_vectorized must validate min_train_months >= 1."""
        import src.research.walk_forward as wf_mod

        monkeypatch.setattr(
            "src.common.qlib_init.safe_qlib_init", lambda cfg: None,
        )
        monkeypatch.setattr(
            "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {},
        )
        # Stub generate_splits to avoid needing full data mocks for this
        # validation-before-data-loading test.
        monkeypatch.setattr(wf_mod, "generate_splits", lambda **kw: [])

        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            walk_forward_vectorized(min_train_months=0)
        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            walk_forward_vectorized(min_train_months=-5)


# ---------------------------------------------------------------------------
# Actual-fit enforcement for min_train_months
# ---------------------------------------------------------------------------


class _DefaultMockCalendar:
    """Build a weekday DatetimeIndex from *start* with *n_days* weekdays."""
    @staticmethod
    def build(start: str, n_days: int) -> pd.DatetimeIndex:
        start_ts = pd.Timestamp(start)
        dates = [start_ts + pd.Timedelta(days=i) for i in range(n_days)
                 if (start_ts + pd.Timedelta(days=i)).dayofweek < 5]
        return pd.DatetimeIndex(dates)


def _setup_custom_calendar_mocks(
    monkeypatch, tmp_path,
    cal_start: str = "2020-01-01",
    cal_n_days: int = 3000,
    n_instruments: int = 5,
    n_features: int = 5,
) -> tuple[pd.DatetimeIndex, dict]:
    """Install mock harness for walk_forward_vectorized with custom calendar.

    Returns (calendar, captured) where *captured* includes:
      - select_calls: list of (train_X, train_y, valid_X, valid_y) args
      - train_calls: list of kwarg dicts from lgb.train calls
      - y_df: the label DataFrame used by the mock

    The calendar spans *cal_n_days* weekdays starting from *cal_start*.
    """
    import importlib
    import sys
    from types import ModuleType

    cal = _DefaultMockCalendar.build(cal_start, cal_n_days)

    monkeypatch.setattr(
        "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
    monkeypatch.setattr(
        "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})
    monkeypatch.setattr(
        "src.research.walk_forward._get_trading_calendar",
        lambda start, end: cal)

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    instruments = [f"S{i}" for i in range(n_instruments)]
    (instr_dir / "cn.txt").write_text("\n".join(instruments))
    monkeypatch.chdir(tmp_path)

    # Use the full calendar for the mock data (covers all possible dates)
    dates = cal
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"])
    rng = np.random.default_rng(42)

    base = rng.standard_normal((len(idx), 1))
    feat_cols = {}
    for i in range(n_features):
        feat_cols[f"feat_{i}"] = (base * (0.8 + 0.4 * i / n_features)
                                  + rng.standard_normal((len(idx), 1)) * 0.3).ravel()
    X_df = pd.DataFrame(feat_cols, index=idx)
    y_df = pd.DataFrame(base * 0.6 + 0.02, index=idx, columns=["label"])

    _feat_call = [0]

    class _FakeD:
        @staticmethod
        def features(symbols, expressions, start_time=None, end_time=None):
            _feat_call[0] += 1
            return X_df if _feat_call[0] == 1 else y_df

    loader_module = importlib.import_module("qlib.contrib.data.loader")

    mock_qlib_data = ModuleType("qlib.data")
    mock_qlib_data.D = _FakeD
    monkeypatch.setitem(sys.modules, "qlib.data", mock_qlib_data)

    class _FakeAlpha:
        @staticmethod
        def get_feature_config(cfg):
            return ([f"$close_{i}" for i in range(n_features)], {})

    monkeypatch.setattr(loader_module, "Alpha158DL", _FakeAlpha)

    captured = {"select_calls": [], "train_calls": [], "y_df": y_df}
    lightgbm_module = importlib.import_module("lightgbm")

    def _fake_train(params, train_set, num_boost_round=100,
                    valid_sets=None, feval=None, callbacks=None):
        captured["train_calls"].append({
            "params": dict(params) if params else {},
            "valid_sets": valid_sets,
            "feval": feval,
            "callbacks": callbacks,
        })
        booster = SimpleNamespace()
        booster.best_iteration = 1
        booster.best_score = {"valid_0": {"mean_daily_cs_ic": 0.05}}
        booster.predict = lambda X: np.zeros(len(X))
        return booster

    monkeypatch.setattr(lightgbm_module, "train", _fake_train)
    monkeypatch.setattr(lightgbm_module, "Dataset",
                        lambda data, label=None, reference=None: data)

    return cal, captured


# ===================================================================


class TestMinTrainMonthsActualFit:
    """min_train_months constrains the ACTUAL fit/selector training segment,
    not just the nominal test_start boundary from generate_splits.

    After computing safe_train_end (which accounts for validation hold-out
    and label-horizon purges), candidates whose data falls short of
    _add_months(train_start, min_train_months) are recorded as
    status='skipped' with a clear protocol reason.  No selector/model
    is called for these candidates.
    """

    def test_default_12_skips_early_candidates(self, monkeypatch, tmp_path):
        """With min_train_months=12 (default), the first candidate(s) are
        skipped because safe_train_end < threshold.  The first successful
        split has train_max >= threshold, and skipped candidates are visible
        with status='skipped' and error_message."""
        _cal, captured = _setup_custom_calendar_mocks(monkeypatch, tmp_path)

        train_start = "2024-01-01"
        threshold_dt = _add_months(
            datetime.strptime(train_start, "%Y-%m-%d"), 12
        )
        threshold_str = threshold_dt.strftime("%Y-%m-%d")

        # Wrap select_stable_features to capture train_X max dates
        select_train_maxes = []

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            tmax = train_X.index.get_level_values("datetime").max()
            select_train_maxes.append(tmax)
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start=train_start, train_end="2026-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            min_train_months=12,
        )

        n_total = len(result.splits)
        n_skipped = sum(1 for s in result.splits if s.status == "skipped")
        n_success = sum(1 for s in result.splits if s.status == "success")

        # At least one candidate should be skipped before the first success
        assert n_skipped >= 1, (
            f"Expected >= 1 skipped splits, got {n_skipped} "
            f"(total={n_total}, success={n_success})"
        )
        assert n_success >= 1, (
            f"Expected >= 1 successful splits, got {n_success}"
        )

        # Skipped splits must have error_message explaining why
        for sr in result.splits:
            if sr.status == "skipped":
                assert sr.error_message is not None, (
                    f"Skipped split {sr.split_id} must have error_message"
                )
                assert "min_train_months" in sr.error_message.lower(), (
                    f"Skipped split {sr.split_id} error must mention min_train_months: "
                    f"{sr.error_message}"
                )

        # First successful split's train_X max >= threshold
        first_success_train_max = select_train_maxes[0]
        assert first_success_train_max >= pd.Timestamp(threshold_str), (
            f"First successful split train_max={first_success_train_max.date()} "
            f"is before threshold={threshold_str}. "
            f"All successful train maxes: {[d.date() for d in select_train_maxes]}"
        )

        # Number of select calls equals number of successful splits
        assert len(select_train_maxes) == n_success, (
            f"select_stable_features called {len(select_train_maxes)} times "
            f"but only {n_success} splits succeeded. "
            f"No selector call should occur for skipped candidates."
        )

    def test_skipped_no_selector_call(self, monkeypatch, tmp_path):
        """No select_stable_features calls for skipped candidates."""
        _cal, captured = _setup_custom_calendar_mocks(monkeypatch, tmp_path)

        select_call_count = [0]

        def _counting_select(*args, **kwargs):
            select_call_count[0] += 1
            feat_name = args[0].columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _counting_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start="2024-01-01", train_end="2026-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            min_train_months=12,
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        assert select_call_count[0] == n_success, (
            f"Select called {select_call_count[0]} times but {n_success} "
            f"splits succeeded (should be equal)"
        )

    def test_min_36_eligibility(self, monkeypatch, tmp_path):
        """With train_start=2021-01-01 and min_train_months=36, the first
        eligible split's train_X max >= 2024-01-01.  Candidates whose
        safe_train_end is before the threshold are skipped.  The first
        evaluated test_start reflects the actual candidate cadence."""
        import importlib
        import sys
        from types import ModuleType

        train_start = "2021-01-01"
        min_mo = 36
        threshold_dt = _add_months(
            datetime.strptime(train_start, "%Y-%m-%d"), min_mo
        )
        threshold_str = threshold_dt.strftime("%Y-%m-%d")

        # Use a long calendar covering 2020-2027
        cal_start = "2020-01-01"
        cal_n_days = 3000  # ~8 years of calendar days, filtered to weekdays
        cal = _DefaultMockCalendar.build(cal_start, cal_n_days)

        monkeypatch.setattr(
            "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
        monkeypatch.setattr(
            "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})
        monkeypatch.setattr(
            "src.research.walk_forward._get_trading_calendar",
            lambda start, end: cal)

        instr_dir = tmp_path / "data" / "watchlist" / "instruments"
        instr_dir.mkdir(parents=True)
        instruments = [f"S{i}" for i in range(5)]
        (instr_dir / "cn.txt").write_text("\n".join(instruments))
        monkeypatch.chdir(tmp_path)

        # Generate synthetic features spanning the full calendar
        dates = cal
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"])
        rng = np.random.default_rng(42)
        base = rng.standard_normal((len(idx), 1))
        feat_cols = {}
        for i in range(5):
            feat_cols[f"feat_{i}"] = (base * (0.8 + 0.4 * i / 5)
                                      + rng.standard_normal((len(idx), 1)) * 0.3).ravel()
        X_df = pd.DataFrame(feat_cols, index=idx)
        y_df = pd.DataFrame(base * 0.6 + 0.02, index=idx, columns=["label"])

        _feat_call = [0]

        class _FakeD:
            @staticmethod
            def features(symbols, expressions, start_time=None, end_time=None):
                _feat_call[0] += 1
                return X_df if _feat_call[0] == 1 else y_df

        loader_module = importlib.import_module("qlib.contrib.data.loader")
        mock_qlib_data = ModuleType("qlib.data")
        mock_qlib_data.D = _FakeD
        monkeypatch.setitem(sys.modules, "qlib.data", mock_qlib_data)

        class _FakeAlpha:
            @staticmethod
            def get_feature_config(cfg):
                return (["$close_0"], {})

        monkeypatch.setattr(loader_module, "Alpha158DL", _FakeAlpha)

        select_train_maxes = []

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=10,
                            min_instruments_per_day=3):
            tmax = train_X.index.get_level_values("datetime").max()
            select_train_maxes.append(tmax)
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )
        lightgbm_module = importlib.import_module("lightgbm")

        def _fake_train(params, train_set, num_boost_round=100,
                        valid_sets=None, feval=None, callbacks=None):
            booster = SimpleNamespace()
            booster.best_iteration = 1
            booster.best_score = {"valid_0": {"mean_daily_cs_ic": 0.05}}
            booster.predict = lambda X: np.zeros(len(X))
            return booster

        monkeypatch.setattr(lightgbm_module, "train", _fake_train)
        monkeypatch.setattr(lightgbm_module, "Dataset",
                            lambda data, label=None, reference=None: data)

        result = walk_forward_vectorized(
            market="cn", train_start=train_start, train_end="2026-12-31",
            test_window_months=3, step_months=3, n_estimators=1,
            min_train_months=min_mo,
        )

        n_total = len(result.splits)
        n_skipped = sum(1 for s in result.splits if s.status == "skipped")
        n_success = sum(1 for s in result.splits if s.status == "success")

        skipped_reasons = [
            s.error_message for s in result.splits if s.status == "skipped"
        ]

        # There MUST be skipped candidates (first candidates are insufficient)
        assert n_skipped >= 1, (
            f"Expected >= 1 skipped split for min_train_months=36, "
            f"got {n_skipped}. Total splits: {n_total}. "
            f"Skipped reasons: {skipped_reasons}"
        )

        assert n_success > 0, "Expected at least one model-eligible split"

        # The first successful split must have train_max >= threshold.
        first_train_max = select_train_maxes[0]
        assert first_train_max >= pd.Timestamp(threshold_str), (
            f"First successful split train_max={first_train_max.date()} "
            f"is before threshold={threshold_str}"
        )

        first_evaluated = next(
            split for split in result.splits if split.status == "success"
        )
        assert first_evaluated.test_start == "2024-10-01"

        # No selector call for skipped candidates
        assert len(select_train_maxes) == n_success, (
            f"Select called {len(select_train_maxes)} times but "
            f"{n_success} splits succeeded (should be equal)"
        )

        # Skipped candidates have proper error messages
        for sr in result.splits:
            if sr.status == "skipped":
                assert sr.error_message is not None, (
                    f"Skipped split {sr.split_id} must have error_message"
                )
                assert "min_train_months" in sr.error_message.lower(), (
                    f"Skipped split {sr.split_id} error must mention "
                    f"min_train_months: {sr.error_message}"
                )

    def test_default_12_first_evaluated_test_start(self, monkeypatch, tmp_path):
        """With default min_train_months=12, the first evaluated
        (non-skipped) test_start is later than the nominal first boundary
        (train_start+12mo), proving the actual-fit check shifts evaluation
        forward."""
        train_start = "2024-01-01"
        _cal, captured = _setup_custom_calendar_mocks(monkeypatch, tmp_path)

        def _fake_select(*args, **kwargs):
            feat = args[0].columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat], name="feature"),
            )

        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _fake_select,
        )

        result = walk_forward_vectorized(
            market="cn", train_start=train_start, train_end="2026-12-15",
            test_window_months=3, step_months=3, n_estimators=1,
            min_train_months=12,
        )

        n_skipped = sum(1 for s in result.splits if s.status == "skipped")
        n_success = sum(1 for s in result.splits if s.status == "success")
        assert n_success >= 1, (
            f"Expected >= 1 successful splits, got {n_success}"
        )
        assert n_skipped >= 1, (
            f"Expected >= 1 skipped splits, got {n_skipped}"
        )

        nominal_first = _add_months(
            datetime.strptime(train_start, "%Y-%m-%d"), 12
        ).strftime("%Y-%m-%d")
        first_actual = next(
            s.test_start for s in result.splits if s.status == "success"
        )
        assert first_actual == "2025-07-01", (
            f"First evaluated test_start ({first_actual}) must reflect the "
            f"validation and purge delay after nominal boundary ({nominal_first})"
        )

    def test_preserves_existing_coverage(self, monkeypatch, tmp_path):
        """Existing TestMinTrainMonths coverage must still pass:
        invalid values, no-split case, and basic split generation."""
        # Invalid
        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            generate_splits(min_train_months=0)
        with pytest.raises(ValueError, match=r"(?i)min_train_months"):
            generate_splits(min_train_months=-1)

        # No splits when range below minimum
        no_splits = generate_splits(
            train_start="2025-01-01", train_end="2025-12-01",
            test_window_months=6, step_months=3, min_train_months=36,
        )
        assert len(no_splits) == 0

        # generate_splits docstring mentions nominal boundaries
        doc = generate_splits.__doc__ or ""
        assert "nominal" in doc.lower() or "candidate" in doc.lower(), (
            "generate_splits docstring should clarify nominal boundaries"
        )


# ===================================================================
# WF≥8 splits from 2018-01-01 start with min_train_months=36
# ===================================================================


class TestWFEightPlusSplits:
    """Prove that using WF_TRAIN_START=2018-01-01 with min_train_months=36
    and train_end=2024-12-31 yields >= 8 evaluable splits after accounting
    for label-horizon purge + validation hold-out.

    This test uses the same mock harness as TestMinTrainMonthsActualFit to
    prove the calendar boundary, not the qlib integration.
    """

    def test_generate_splits_candidates_geq_8(self):
        """generate_splits alone must produce at least 9 nominal splits
        (so after purging at least 8 survive)."""
        splits = generate_splits(
            train_start="2018-01-01",
            train_end="2024-12-31",
            test_window_months=6,
            step_months=3,
            min_train_months=36,
        )
        assert len(splits) >= 9, (
            f"Need >= 9 nominal splits to expect 8 after purge, got {len(splits)}"
        )

    def test_actual_evaluable_splits_geq_8(self, monkeypatch, tmp_path):
        """In the mock vectorized WF harness, using WF_TRAIN_START=2018-01-01
        and default params (36mo min fit, 3mo step, 6mo test window) produces
        at least 8 successful (non-skipped) splits."""
        _cal, captured = _setup_custom_calendar_mocks(
            monkeypatch, tmp_path,
            cal_start="2016-01-01",
            cal_n_days=4000,
        )
        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            lambda train_X, train_y, valid_X, valid_y, max_features=10, min_instruments_per_day=3: (
                pd.DataFrame(
                    {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                    index=pd.Index([train_X.columns[0]], name="feature"),
                )
            ),
        )

        result = walk_forward_vectorized(
            market="cn",
            train_start="2018-01-01",
            train_end="2024-12-31",
            test_window_months=6,
            step_months=3,
            n_estimators=1,
            min_train_months=36,
            label_horizon=10,
            training_objective="regression",
            feature_profile="alpha158",
        )

        n_success = sum(1 for s in result.splits if s.status == "success")
        n_skipped = sum(1 for s in result.splits if s.status == "skipped")
        n_total = len(result.splits)

        assert n_success >= 8, (
            f"WF_TRAIN_START=2018-01-01 should yield >= 8 successful splits, "
            f"got {n_success} (total={n_total}, skipped={n_skipped}). "
            f"Split statuses: {[(s.split_id, s.status, s.train_end, s.test_start) for s in result.splits]}"
        )


# ===================================================================
# Native estimator adapter tests
# ===================================================================


class TestIsNativeEstimatorConfig:
    """Prove ``_is_native_estimator_config`` correctly detects native
    sklearn-style estimators vs Qlib model wrappers."""

    def test_native_lightgbm_detected(self):
        cfg = {
            "task": {
                "model": {
                    "class": "LGBMRegressor",
                    "module_path": "lightgbm",
                    "kwargs": {},
                },
            },
        }
        assert _is_native_estimator_config(cfg) is True

    def test_qlib_wrapper_not_detected(self):
        cfg = {
            "task": {
                "model": {
                    "class": "LGBModel",
                    "module_path": "qlib.contrib.model.gbdt",
                    "kwargs": {},
                },
            },
        }
        assert _is_native_estimator_config(cfg) is False

    def test_missing_module_path(self):
        cfg = {"task": {"model": {"class": "LGBMRegressor"}}}
        assert _is_native_estimator_config(cfg) is False

    def test_empty_task(self):
        assert _is_native_estimator_config({}) is False


class TestPrepareNativeDataset:
    """Prove ``_prepare_native_dataset`` extracts aligned X/y from a mock
    DatasetH, drops non-finite rows, and handles missing segments."""

    @staticmethod
    def _make_idx(dates, instruments):
        return pd.MultiIndex.from_product(
            [pd.DatetimeIndex(dates), instruments],
            names=["datetime", "instrument"],
        )

    def test_extracts_all_segments(self):
        """All three segments (train/valid/test) are extracted and aligned."""
        idx_train = self._make_idx(["2024-01-02", "2024-01-03"], ["A", "B"])
        idx_valid = self._make_idx(["2024-04-01", "2024-04-02"], ["A", "B"])
        idx_test = self._make_idx(["2024-07-01", "2024-07-02"], ["A", "B"])

        class FakeDataset:
            def prepare(self, segments, col_set, data_key=None):
                if col_set == "feature":
                    if segments == ["2024-01-01", "2024-06-30"]:
                        return pd.DataFrame(
                            {"feat1": [1.0, 2.0, 3.0, 4.0]}, index=idx_train,
                        )
                    if segments == ["2024-04-01", "2024-06-30"]:
                        return pd.DataFrame(
                            {"feat1": [5.0, 6.0, 7.0, 8.0]}, index=idx_valid,
                        )
                    return pd.DataFrame(
                        {"feat1": [9.0, 10.0, 11.0, 12.0]}, index=idx_test,
                    )
                # label
                if segments == ["2024-01-01", "2024-06-30"]:
                    return pd.DataFrame({"label": [0.1, 0.2, 0.3, 0.4]}, index=idx_train)
                if segments == ["2024-04-01", "2024-06-30"]:
                    return pd.DataFrame({"label": [0.5, 0.6, 0.7, 0.8]}, index=idx_valid)
                return pd.DataFrame({"label": [0.9, 1.0, 1.1, 1.2]}, index=idx_test)

        segments = {
            "train": ["2024-01-01", "2024-06-30"],
            "valid": ["2024-04-01", "2024-06-30"],
            "test": ["2024-07-01", "2024-12-31"],
        }

        result = _prepare_native_dataset(FakeDataset(), segments)

        assert "train" in result
        assert "valid" in result
        assert "test" in result
        assert result["train"][0].shape == (4, 1)
        assert result["test"][1].iloc[0] == pytest.approx(0.9)

    def test_drops_non_finite_rows(self):
        """Rows with NaN in X or y are dropped."""
        idx = self._make_idx(["2024-01-02"], ["A", "B", "C", "D"])

        class FakeDataset:
            def prepare(self, segments, col_set, data_key=None):
                if col_set == "feature":
                    return pd.DataFrame(
                        {"f1": [1.0, 2.0, float("nan"), 4.0]}, index=idx,
                    )
                return pd.DataFrame(
                    {"label": [0.1, 0.2, 0.3, float("nan")]}, index=idx,
                )

        segments = {"train": ["2024-01-01", "2024-06-30"]}
        result = _prepare_native_dataset(FakeDataset(), segments)

        assert "train" in result
        X, y = result["train"]
        assert len(X) == 2  # only rows 0, 1 are fully finite
        assert list(X.index.get_level_values("instrument")) == ["A", "B"]
        assert list(y.values) == [0.1, 0.2]

    def test_missing_segment_omitted(self):
        """Segment not in the dict is simply omitted from the result."""
        result = _prepare_native_dataset(object(), {"train": ["2024-01-01", "2024-06-30"]})
        assert "train" not in result  # No data, object() raises on .prepare
        assert "valid" not in result
        assert "test" not in result


class TestFitNativeEstimator:
    """Prove ``_fit_native_estimator`` calls fit(X,y) and predict(X) on a
    sklearn-style estimator using data extracted from a mock DatasetH."""

    @staticmethod
    def _make_idx(dates, instruments):
        return pd.MultiIndex.from_product(
            [pd.DatetimeIndex(dates), instruments],
            names=["datetime", "instrument"],
        )

    def test_fits_and_predicts(self):
        """Model is fitted on X/y and predicts on test data."""
        idx_train = self._make_idx(["2024-01-02"], ["A", "B", "C"])
        idx_valid = self._make_idx(["2024-04-01"], ["A", "B", "C"])
        idx_test = self._make_idx(["2024-07-01"], ["A", "B", "C"])

        class FakeDataset:
            def prepare(self, segments, col_set, data_key=None):
                if col_set == "feature":
                    if "01-01" in str(segments[0]):
                        return pd.DataFrame(
                            {"f1": [1.0, 2.0, 3.0]}, index=idx_train,
                        )
                    if "04" in str(segments[0]):
                        return pd.DataFrame(
                            {"f1": [4.0, 5.0, 6.0]}, index=idx_valid,
                        )
                    return pd.DataFrame(
                        {"f1": [7.0, 8.0, 9.0]}, index=idx_test,
                    )
                if "01-01" in str(segments[0]):
                    return pd.DataFrame({"label": [0.1, 0.2, 0.3]}, index=idx_train)
                if "04" in str(segments[0]):
                    return pd.DataFrame({"label": [0.4, 0.5, 0.6]}, index=idx_valid)
                return pd.DataFrame({"label": [0.7, 0.8, 0.9]}, index=idx_test)

        segments = {
            "train": ["2024-01-01", "2024-03-31"],
            "valid": ["2024-04-01", "2024-06-30"],
            "test": ["2024-07-01", "2024-12-31"],
        }

        class FakeEstimator:
            def __init__(self):
                self.fitted_X = None
                self.fitted_y = None
                self.eval_set = None

            def fit(self, X, y, eval_set=None):
                self.fitted_X = X
                self.fitted_y = y
                self.eval_set = eval_set
                return self

            def predict(self, X):
                return np.ones(len(X)) * 0.5

        model = FakeEstimator()
        fitted, predictions = _fit_native_estimator(model, FakeDataset(), segments)

        assert fitted is model
        assert len(predictions) == 3
        assert list(predictions.values) == [0.5, 0.5, 0.5]
        assert fitted.fitted_X is not None
        assert len(fitted.fitted_X) == 3
        # eval_set should contain valid as monitoring
        assert fitted.eval_set is not None
        X_va, y_va = fitted.eval_set[0]
        assert len(X_va) == 3

    def test_raises_on_no_train(self):
        """RuntimeError when train data unavailable."""
        with pytest.raises(RuntimeError, match=r"(?i)no training data"):
            _fit_native_estimator(
                object(), object(), {"test": ["2024-07-01", "2024-12-31"]},
            )


class TestWalkForwardZeroSuccess:
    """Prove walk_forward_validate / _stage_walk_forward fail when no splits
    succeed."""

    def test_validate_raises_on_all_failed(self, monkeypatch, tmp_path):
        """walk_forward_validate raises RuntimeError when all splits fail."""
        monkeypatch.setattr(
            "src.common.qlib_init.safe_qlib_init", lambda cfg: None,
        )
        monkeypatch.setattr(
            "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {},
        )

        def _fail_all(*args, **kwargs):
            raise RuntimeError("Simulated split failure")

        monkeypatch.setattr(
            "src.research.walk_forward._run_single_split", _fail_all,
        )

        config_path = tmp_path / "us_lgbm_workflow.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("task:\n  model:\n    kwargs: {}\n", encoding="utf-8")
        monkeypatch.setattr("src.common.paths.CONFIG_DIR", config_path.parent)

        with pytest.raises(RuntimeError, match=r"(?i)zero successful"):
            walk_forward_validate(
                market="us", model_type="lgbm",
                train_start="2021-01-01", train_end="2022-06-30",
            )


class TestStageWalkForwardConfigWindows:
    """Prove _stage_walk_forward passes config-derived training windows to
    walk_forward_validate."""

    def test_uses_config_end_time(self, monkeypatch):
        """The end_time from config is used as train_end for walk-forward,
        preventing evaluation beyond the configured range."""
        from scripts.generate_release_candidate import _stage_walk_forward

        captured = {}

        def fake_validate(market, model_type, train_start, train_end,
                          config, label_horizon):
            captured["train_start"] = train_start
            captured["train_end"] = train_end
            result = WalkForwardResult(market="us", model_type="lgbm_regressor")
            # Add a placeholder split so _stage_walk_forward doesn't abort
            result.splits.append(
                SplitResult(
                    split_id=0, train_start="2018-01-01", train_end="2023-12-31",
                    test_start="2024-01-01", test_end="2024-06-30",
                    ic=0.05, rank_ic=0.04,
                )
            )
            return result

        monkeypatch.setattr(
            "src.research.walk_forward.walk_forward_validate",
            fake_validate,
        )

        config = {
            "fit_start_time": "2018-01-01",
            "start_time": "2018-01-01",
            "end_time": "2024-12-31",
            "task": {
                "dataset": {
                    "kwargs": {
                        "segments": {
                            "train": ["2018-01-01", "2023-12-31"],
                        },
                    },
                },
                "model": {"kwargs": {}},
            },
        }

        _stage_walk_forward(config, "us", Path("."))

        assert captured["train_start"] == "2018-01-01"
        assert captured["train_end"] == "2024-12-31"

    def test_uses_config_start_time_fallback(self, monkeypatch):
        """When fit_start_time is missing, uses start_time as train_start."""
        from scripts.generate_release_candidate import _stage_walk_forward

        captured = {}

        def fake_validate(market, model_type, train_start, train_end,
                          config, label_horizon):
            captured["train_start"] = train_start
            result = WalkForwardResult(market="us", model_type="lgbm_regressor")
            result.splits.append(
                SplitResult(
                    split_id=0, train_start="2019-06-01", train_end="2023-12-31",
                    test_start="2024-01-01", test_end="2024-06-30",
                    ic=0.05, rank_ic=0.04,
                )
            )
            return result

        monkeypatch.setattr(
            "src.research.walk_forward.walk_forward_validate",
            fake_validate,
        )

        config = {
            "start_time": "2019-06-01",
            "end_time": "2024-12-31",
            "task": {
                "dataset": {
                    "kwargs": {
                        "segments": {
                            "train": ["2019-06-01", "2023-12-31"],
                        },
                    },
                },
                "model": {"kwargs": {}},
            },
        }

        _stage_walk_forward(config, "us", Path("."))

        assert captured["train_start"] == "2019-06-01"


# ---------------------------------------------------------------------------
# Load raw labels index normalization
# ---------------------------------------------------------------------------


class TestLoadRawLabelsIndexOrder:
    """_load_raw_labels must always return a Series with (datetime, instrument)
    MultiIndex order, even when D.features returns the native qlib order
    (instrument, datetime)."""

    def test_normalizes_instrument_datetime_to_datetime_instrument(
        self, monkeypatch,
    ):
        """Simulate D.features returning (instrument, datetime) order and
        assert _load_raw_labels returns (datetime, instrument) order."""
        from src.research.walk_forward import _normalize_qlib_index

        instruments = ["AAPL", "MSFT", "GOOG"]
        dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"], name="datetime")

        # Build the index in Qlib's native order: (instrument, datetime)
        native_idx = pd.MultiIndex.from_product(
            [instruments, dates], names=["instrument", "datetime"],
        )
        raw_df = pd.DataFrame(
            np.array([0.01, 0.02, 0.03, -0.01, -0.02, -0.03, 0.00, 0.01, 0.02],
                     dtype=float),
            index=native_idx,
            columns=["Ref($close, -10) / Ref($close, -1) - 1"],
        )

        class _FakeD:
            @staticmethod
            def list_instruments(inst, as_list=True):
                return instruments

            @staticmethod
            def instruments(key):
                return key

            @staticmethod
            def features(symbols, expressions, start_time=None, end_time=None):
                # Return in qlib native order: (instrument, datetime)
                return raw_df

        monkeypatch.setattr(
            "src.research.walk_forward.D", _FakeD,
        )

        config = {
            "task": {
                "dataset": {
                    "kwargs": {
                        "handler": {
                            "kwargs": {
                                "label": ["Ref($close, -10) / Ref($close, -1) - 1"],
                                "instruments": "us",
                            },
                        },
                    },
                },
            },
        }

        result = _load_raw_labels(config, "2024-01-02", "2024-01-04")

        # Must be a Series
        assert isinstance(result, pd.Series), f"Expected Series, got {type(result)}"
        # Index must be MultiIndex
        assert isinstance(result.index, pd.MultiIndex), (
            f"Expected MultiIndex, got {type(result.index)}"
        )
        # Level order must be (datetime, instrument)
        assert result.index.names == ["datetime", "instrument"], (
            f"Expected names ['datetime', 'instrument'], got {result.index.names}"
        )
        # Must be sorted so datetime is the first level
        first_level = result.index.get_level_values(0)
        assert first_level.is_monotonic_increasing, (
            "Result index must be sorted by (datetime, instrument)"
        )
        # Values preserved: check a specific pair
        aapl_idx = result.index.get_loc(("2024-01-02", "AAPL"))
        assert result.iloc[aapl_idx] == 0.01, (
            f"Expected 0.01 for (2024-01-02, AAPL), got {result.iloc[aapl_idx]}"
        )

    def test_preserves_correct_level_names(self, monkeypatch):
        """Only exact 'datetime'/'instrument' level names accepted."""
        # Build index with wrong level name
        wrong_idx = pd.MultiIndex.from_product(
            [["A", "B"], pd.DatetimeIndex(["2024-01-02", "2024-01-03"])],
            names=["instrument", "date"],  # 'date' not 'datetime'
        )
        raw_df = pd.DataFrame([0.01, 0.02, 0.03, 0.04], index=wrong_idx, columns=["label"])

        class _BadD:
            @staticmethod
            def list_instruments(inst, as_list=True):
                return ["A", "B"]

            @staticmethod
            def instruments(key):
                return key

            @staticmethod
            def features(symbols, expressions, start_time=None, end_time=None):
                return raw_df

        monkeypatch.setattr("src.research.walk_forward.D", _BadD)

        config = {
            "task": {
                "dataset": {
                    "kwargs": {
                        "handler": {
                            "kwargs": {
                                "label": ["label"],
                                "instruments": "us",
                            },
                        },
                    },
                },
            },
        }

        with pytest.raises(ValueError, match=r"(?i)datetime|instrument"):
            _load_raw_labels(config, "2024-01-02", "2024-01-03")


# ---------------------------------------------------------------------------
# Load raw labels NaN filtering
# ---------------------------------------------------------------------------


class TestLoadRawLabelsNanFiltering:
    """_load_raw_labels drops non-finite values and records attrs."""

    def _fake_d(self, raw_series: pd.Series):
        """Return a fake D class whose features returns a DataFrame built from *raw_series*."""
        instruments = list(raw_series.index.get_level_values("instrument").unique())

        class _FakeD:
            @staticmethod
            def list_instruments(inst, as_list=True):
                return instruments

            @staticmethod
            def instruments(key):
                return key

            @staticmethod
            def features(symbols, expressions, start_time=None, end_time=None):
                return raw_series.to_frame(expressions[0])

        return _FakeD

    def test_drops_partial_nan(self, monkeypatch):
        """Partial NaN/inf values are dropped and attrs recorded."""
        dates = pd.bdate_range("2024-01-02", periods=3)
        instruments = ["A", "B"]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"],
        )
        vals = [0.01, np.nan, np.inf, -0.01, -np.inf, 0.02]
        raw = pd.Series(vals, index=idx, name="label")

        monkeypatch.setattr(
            "src.research.walk_forward.D",
            self._fake_d(raw),
        )
        result = _load_raw_labels(
            self._raw_config(),
            "2024-01-02",
            "2024-01-04",
        )

        assert isinstance(result, pd.Series)
        assert len(result) == 3  # 6 - 3 non-finite
        assert result.attrs["n_raw_rows"] == 6
        assert result.attrs["n_dropped_non_finite"] == 3
        assert result.attrs["n_valid_rows"] == 3

    def test_fails_on_all_nan(self, monkeypatch):
        """All-non-finite raises RuntimeError."""
        dates = pd.bdate_range("2024-01-02", periods=2)
        instruments = ["A"]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"],
        )
        raw = pd.Series([np.nan, np.inf], index=idx, name="label")

        monkeypatch.setattr(
            "src.research.walk_forward.D",
            self._fake_d(raw),
        )
        with pytest.raises(RuntimeError, match=r"(?i)zero finite"):
            _load_raw_labels(
                self._raw_config(),
                "2024-01-02",
                "2024-01-03",
            )

    def _raw_config(self) -> dict:
        return {
            "task": {
                "dataset": {
                    "kwargs": {
                        "handler": {
                            "kwargs": {
                                "label": ["Ref($close, -10) / Ref($close, -1) - 1"],
                                "instruments": "us",
                            },
                        },
                    },
                },
            },
        }
