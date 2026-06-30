"""Focused tests for the three public APIs of cross_sectional_training.

Covers daily-vs-pooled, finite/constant/insufficient filtering, MultiIndex
validation, stable-sign selection (column-order-agnostic pairing),
determinism, fewer-than-max, and LGBM custom eval edge cases.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.cross_sectional_training import (
    compute_mean_daily_cs_ic,
    compute_relevance_labels,
    make_daily_cs_ic_eval,
    monotone_constraints_from_selection,
    select_stable_features,
)

# -- helpers -------------------------------------------------------------------

def _idx(dates, instruments):
    return pd.MultiIndex.from_arrays(
        [pd.to_datetime(dates), instruments], names=["datetime", "instrument"])

def _X(data, dates, instruments, features=None):
    if features is None:
        features = [f"f{i}" for i in range(data.shape[1])]
    return pd.DataFrame(data, index=_idx(dates, instruments), columns=features)

def _y(values, dates, instruments):
    return pd.Series(np.asarray(values, dtype=float),
                     index=_idx(dates, instruments), name="label")

class _MockDS:
    def __init__(self, labels):
        self._labels = np.asarray(labels, dtype=float)
    def get_label(self):
        return self._labels.copy()


# -- compute_mean_daily_cs_ic --------------------------------------------------

class TestComputeMeanDailyCSIC:
    def test_daily_vs_pooled_differs(self):
        """Day 1 IC~-1, day 2 IC~+1 -> mean~0; pooled materially different."""
        d = ["2024-01-02"] * 5 + ["2024-01-03"] * 5
        inst = list("ABCDEFGHIJ")
        X = _X([[5], [4], [3], [2], [1], [101], [102], [103], [104], [105]],
               d, inst, ["feat"])
        y = _y([1, 2, 3, 4, 5, 202, 204, 206, 208, 210], d, inst)
        res = compute_mean_daily_cs_ic(X, y)
        assert res.loc["feat", "mean_daily_ic"] == pytest.approx(0.0, abs=0.01)
        assert res.loc["feat", "n_days"] == 2
        pooled = float(np.corrcoef(X["feat"].values, y.values)[0, 1])
        assert abs(pooled) > 0.1
        assert abs(pooled - res.loc["feat", "mean_daily_ic"]) > 0.1
    def test_single_day_perfect(self):
        X = _X([[1], [2], [3], [4], [5]], ["2024-01-02"] * 5, list("ABCDE"), ["feat"])
        y = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        res = compute_mean_daily_cs_ic(X, y)
        assert res.loc["feat", "mean_daily_ic"] == pytest.approx(1.0)
        assert res.loc["feat", "n_days"] == 1
    def test_filters_insufficient_constant_nan(self):
        """Days with <min_instruments, NaN/Inf, or constant y/x skipped."""
        # Day 1: 2 instruments (<3) skipped. Day 2: 5 instruments, 3 finite.
        X = _X([[1], [2], [3], [np.nan], [np.inf], [6], [7]],
               ["2024-01-02", "2024-01-02"] + ["2024-01-03"] * 5,
               list("ABCDEFG"), ["feat"])
        y = _y([2, 4, 6, 8, 10, 12, 14],
               ["2024-01-02", "2024-01-02"] + ["2024-01-03"] * 5,
               list("ABCDEFG"))
        res = compute_mean_daily_cs_ic(X, y, min_instruments_per_day=3)
        assert res.loc["feat", "n_days"] == 1
        assert res.loc["feat", "mean_daily_ic"] == pytest.approx(1.0)
        # Constant y -> zero std -> n_days=0.
        X2 = _X([[1], [2], [3], [4], [5]], ["2024-01-02"] * 5, list("ABCDE"), ["feat"])
        y2 = _y([7] * 5, ["2024-01-02"] * 5, list("ABCDE"))
        res2 = compute_mean_daily_cs_ic(X2, y2)
        assert res2.loc["feat", "n_days"] == 0
        assert res2.loc["feat", "mean_daily_ic"] == 0.0
    def test_same_labels_different_order(self):
        """y with same labels but reversed row order -> reindexed by X order."""
        X = _X([[1], [2], [3], [4], [5]], ["2024-01-02"] * 5, list("ABCDE"), ["feat"])
        y = _y([10, 8, 6, 4, 2], ["2024-01-02"] * 5, list("EDCBA"))
        res = compute_mean_daily_cs_ic(X, y)
        assert res.loc["feat", "mean_daily_ic"] == pytest.approx(1.0)
    @pytest.mark.parametrize("label, mk, match, exc, min_inst", [
        ("flat index",
         lambda: (pd.DataFrame({"feat": [1.0, 2.0]}),
                  _y([2.0, 4.0], ["2024-01-02", "2024-01-03"], ["A", "B"])),
         None, (TypeError, ValueError), 3),
        ("duplicate index",
         lambda: (pd.DataFrame({"feat": [1.0, 2.0]},
                               index=_idx(["2024-01-02"] * 2, ["A", "A"])),
                  pd.Series([2.0, 4.0],
                            index=_idx(["2024-01-02"] * 2, ["A", "A"]), name="label")),
         r"(?i)duplicate", ValueError, 3),
        ("missing datetime level",
         lambda: (pd.DataFrame(
             {"feat": [1.0, 2.0]},
             index=pd.MultiIndex.from_arrays([["A", "B"], [1, 2]], names=["x", "y"])),
                  pd.Series([2.0, 4.0],
                            index=pd.MultiIndex.from_arrays([["A", "B"], [1, 2]], names=["x", "y"]),
                            name="label")),
         r"(?i)datetime", ValueError, 3),
        ("partial overlap",
         lambda: (_X([[1], [2], [3]], ["2024-01-02"] * 3, ["A", "B", "C"], ["feat"]),
                  _y([2, 4], ["2024-01-02", "2024-01-02"], ["A", "B"])),
         r"(?i)differ", ValueError, 3),
        ("duplicate feature names",
         lambda: (pd.DataFrame(
             [[1.0, 3.0], [2.0, 4.0]], columns=["a", "a"],
             index=_idx(["2024-01-02", "2024-01-03"], ["A", "B"])),
                  _y([2.0, 4.0], ["2024-01-02", "2024-01-03"], ["A", "B"])),
         r"(?i)duplicate", ValueError, 3),
        ("min_instruments < 2",
         lambda: (_X([[1]], ["2024-01-02"], ["A"], ["feat"]),
                  _y([2], ["2024-01-02"], ["A"])),
         r"(?i)min_instruments", ValueError, 1),
    ])
    def test_validation_errors(self, label, mk, match, exc, min_inst):
        X, y = mk()
        with pytest.raises(exc, match=match):
            compute_mean_daily_cs_ic(X, y, min_instruments_per_day=min_inst)
    def test_zero_ic_feature_still_returned(self):
        """Constant-x feature -> 0 IC -> still in output with n_days=0."""
        X = _X(np.column_stack([[1, 2, 3, 4, 5], [3, 3, 3, 3, 3]]),
               ["2024-01-02"] * 5, list("ABCDE"), ["f1", "f_const"])
        y = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        res = compute_mean_daily_cs_ic(X, y)
        assert set(res.index) == {"f1", "f_const"}
        assert res.loc["f_const", "n_days"] == 0
        assert res.loc["f_const", "mean_daily_ic"] == 0.0


# -- select_stable_features ----------------------------------------------------

class TestSelectStableFeatures:
    def test_same_sign_scored_opposite_excluded(self):
        """Same-sign features scored; opposite-sign excluded entirely."""
        # f_same: IC~+1 train+valid -> qualifies; f_opp: IC~+1 train, ~-1 valid.
        X_tr = _X(np.column_stack([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]),
                  ["2024-01-02"] * 5, list("ABCDE"), ["f_same", "f_opp"])
        y_tr = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        X_va = _X(np.column_stack([[1, 2, 3, 4, 5], [5, 4, 3, 2, 1]]),
                  ["2024-02-02"] * 5, list("FGHIJ"), ["f_same", "f_opp"])
        y_va = _y([2, 4, 6, 8, 10], ["2024-02-02"] * 5, list("FGHIJ"))
        res = select_stable_features(X_tr, y_tr, X_va, y_va, max_features=10,
                                     min_instruments_per_day=3)
        assert "f_same" in res.index and res.loc["f_same", "score"] > 0
        assert "f_opp" not in res.index
    def test_deterministic_tie_and_fewer_than_max(self):
        """Equal-score ties -> alphabetical; only stable features (may be < max)."""
        X_tr = _X(np.column_stack([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5],
                                   [1, 2, 3, 4, 5]]),
                  ["2024-01-02"] * 5, list("ABCDE"), ["f_b", "f_a", "f_c"])
        y_tr = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        # f_c reversed in valid -> opposite sign -> excluded.
        X_va = _X(np.column_stack([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5],
                                   [5, 4, 3, 2, 1]]),
                  ["2024-02-02"] * 5, list("FGHIJ"), ["f_b", "f_a", "f_c"])
        y_va = _y([2, 4, 6, 8, 10], ["2024-02-02"] * 5, list("FGHIJ"))
        res = select_stable_features(X_tr, y_tr, X_va, y_va, max_features=10,
                                     min_instruments_per_day=3)
        assert res.index.tolist() == ["f_a", "f_b"]  # alpha on tie; f_c excluded
        assert len(res) == 2  # fewer than max_features=10

    def test_different_column_order_pairs_by_name(self):
        """Valid X columns reordered -> paired by name (not position)."""
        X_tr = _X(np.column_stack([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5],
                                   [1, 2, 3, 4, 5]]),
                  ["2024-01-02"] * 5, list("ABCDE"), ["f_a", "f_b", "f_c"])
        y_tr = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        # Valid: columns [f_c, f_b, f_a]; f_c negated -> IC~-1; f_a, f_b IC~+1.
        X_va = _X(np.column_stack([[5, 4, 3, 2, 1], [1, 2, 3, 4, 5],
                                   [1, 2, 3, 4, 5]]),
                  ["2024-02-02"] * 5, list("FGHIJ"), ["f_c", "f_b", "f_a"])
        y_va = _y([2, 4, 6, 8, 10], ["2024-02-02"] * 5, list("FGHIJ"))
        res = select_stable_features(X_tr, y_tr, X_va, y_va, max_features=10,
                                     min_instruments_per_day=3)
        assert "f_a" in res.index and res.loc["f_a", "score"] > 0
        assert "f_c" not in res.index
    def test_zero_ic_excluded(self):
        """Feature with zero IC (constant) in either period -> excluded."""
        X_tr = _X(np.column_stack([[1, 2, 3, 4, 5], [3, 3, 3, 3, 3]]),
                  ["2024-01-02"] * 5, list("ABCDE"), ["f_good", "f_const"])
        y_tr = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        X_va = _X(np.column_stack([[1, 2, 3, 4, 5], [3, 3, 3, 3, 3]]),
                  ["2024-02-02"] * 5, list("FGHIJ"), ["f_good", "f_const"])
        y_va = _y([2, 4, 6, 8, 10], ["2024-02-02"] * 5, list("FGHIJ"))
        res = select_stable_features(X_tr, y_tr, X_va, y_va, max_features=10,
                                     min_instruments_per_day=3)
        assert "f_good" in res.index
        assert "f_const" not in res.index
    def test_output_columns_and_truncation(self):
        """Columns [train_ic, valid_ic, score, rank]; max_features truncates."""
        d = np.column_stack([[1, 2, 3, 4, 5], [1.1, 2.1, 3.1, 4.1, 5.1],
                             [1.2, 2.2, 3.2, 4.2, 5.2]])
        X_tr = _X(d, ["2024-01-02"] * 5, list("ABCDE"), ["f0", "f1", "f2"])
        y_tr = _y([2, 4, 6, 8, 10], ["2024-01-02"] * 5, list("ABCDE"))
        X_va = _X(d, ["2024-02-02"] * 5, list("FGHIJ"), ["f0", "f1", "f2"])
        y_va = _y([2, 4, 6, 8, 10], ["2024-02-02"] * 5, list("FGHIJ"))
        res = select_stable_features(X_tr, y_tr, X_va, y_va, max_features=2,
                                     min_instruments_per_day=3)
        assert list(res.columns) == ["train_ic", "valid_ic", "score", "rank"]
        assert res.index.name == "feature"
        assert len(res) == 2
        assert list(res["rank"]) == [1, 2]

    @pytest.mark.parametrize("label, mk, match", [
        ("feature mismatch",
         lambda: (_X([[1]], ["2024-01-02"], ["A"], ["feat_a"]),
                  _y([2], ["2024-01-02"], ["A"]),
                  _X([[1]], ["2024-02-02"], ["B"], ["feat_b"]),
                  _y([3], ["2024-02-02"], ["B"])),
         r"(?i)mismatch"),
        ("max_features <= 0",
         lambda: (_X([[1]], ["2024-01-02"], ["A"], ["feat"]),
                  _y([2], ["2024-01-02"], ["A"]),
                  _X([[1]], ["2024-02-02"], ["B"], ["feat"]),
                  _y([2], ["2024-02-02"], ["B"])),
         "positive"),
    ])
    def test_validation_errors(self, label, mk, match):
        X_tr, y_tr, X_va, y_va = mk()
        maxf = 0 if "max_features" in label else 50
        with pytest.raises(ValueError, match=match):
            select_stable_features(X_tr, y_tr, X_va, y_va, max_features=maxf)


# -- monotone constraints ------------------------------------------------------

class TestMonotoneConstraints:
    """..."""

    def test_uses_selected_feature_order_and_ic_sign(self):
        selection = pd.DataFrame(
            {"train_ic": [0.10, -0.20], "valid_ic": [0.05, -0.10]},
            index=pd.Index(["positive", "negative"], name="feature"),
        )
        assert monotone_constraints_from_selection(selection) == [1, -1]

    @pytest.mark.parametrize(("train_ic", "valid_ic"), [(0.1, -0.1), (0.0, 0.1), (np.nan, 0.1)])
    def test_fails_closed_for_invalid_selection_signs(self, train_ic, valid_ic):
        selection = pd.DataFrame({"train_ic": [train_ic], "valid_ic": [valid_ic]}, index=["feature"])
        with pytest.raises(ValueError, match="stable non-zero"):
            monotone_constraints_from_selection(selection)


# -- relevance labels ----------------------------------------------------------


class TestComputeRelevanceLabels:
    """Tests for compute_relevance_labels — per-date integer bins + groups."""

    @staticmethod
    def _idx(dates, instruments):
        return pd.MultiIndex.from_arrays(
            [pd.to_datetime(dates), instruments], names=["datetime", "instrument"]
        )

    @staticmethod
    def _y(values, dates, instruments):
        return pd.Series(np.asarray(values, dtype=float), index=TestComputeRelevanceLabels._idx(dates, instruments), name="ret")

    def test_three_dates_each_five_instruments(self):
        """3 dates × 5 instruments → 3 groups of size 5, labels 0..4 per date."""
        d = ["2024-01-02"] * 5 + ["2024-01-03"] * 5 + ["2024-01-04"] * 5
        inst = list("ABCDE") * 3
        # Monotonic increasing within each date
        y = self._y([1, 2, 3, 4, 5] * 3, d, inst)
        labels, groups = compute_relevance_labels(y, n_bins=5)
        assert list(groups) == [5, 5, 5]
        assert groups.sum() == len(y)
        assert labels.name == "relevance"
        assert labels.index.equals(y.index)
        # Within each date: bins 0,1,2,3,4
        for date_start in range(0, 15, 5):
            chunk = labels.iloc[date_start : date_start + 5]
            assert list(chunk) == [0, 1, 2, 3, 4], f"chunk at {date_start}: {list(chunk)}"

    def test_single_date_single_group(self):
        """1 date → 1 group; binning into 3 buckets."""
        y = self._y([10, 20, 30], ["2024-01-02"] * 3, ["A", "B", "C"])
        labels, groups = compute_relevance_labels(y, n_bins=3)
        assert list(groups) == [3]
        assert list(labels) == [0, 1, 2]

    def test_preserves_date_contiguous_order(self):
        """Row order of y is preserved in the output labels index."""
        y = self._y([3, 1, 2, 6, 4, 5], ["2024-01-02", "2024-01-02", "2024-01-02",
                                           "2024-01-03", "2024-01-03", "2024-01-03"],
                     ["C", "A", "B", "F", "D", "E"])
        labels, groups = compute_relevance_labels(y, n_bins=3)
        assert list(groups) == [3, 3]
        assert labels.index.equals(y.index)

    def test_fewer_instruments_than_bins(self):
        """A day with < n_bins instruments still produces valid labels (not all 0)."""
        y = self._y([1.0, 0.5, 0.0], ["2024-01-02"] * 3, ["A", "B", "C"])
        labels, groups = compute_relevance_labels(y, n_bins=5)
        assert list(groups) == [3]
        # With 3 stocks and 5 bins, labels should differentiate ranks
        assert len(set(labels)) <= 3
        assert labels.iloc[0] >= labels.iloc[2]  # highest return → highest label

    def test_all_identical_values_ties(self):
        """All identical y values → ties → all label 0."""
        y = self._y([5.0, 5.0, 5.0], ["2024-01-02"] * 3, ["A", "B", "C"])
        labels, groups = compute_relevance_labels(y, n_bins=5)
        assert list(groups) == [3]
        assert list(labels) == [0, 0, 0]

    def test_nan_raises(self):
        y = self._y([1.0, np.nan, 3.0], ["2024-01-02"] * 3, ["A", "B", "C"])
        with pytest.raises(ValueError, match=r"(?i)nan|non-finite"):
            compute_relevance_labels(y)

    def test_inf_raises(self):
        y = self._y([1.0, np.inf, 3.0], ["2024-01-02"] * 3, ["A", "B", "C"])
        with pytest.raises(ValueError, match=r"(?i)non-finite"):
            compute_relevance_labels(y)

    def test_caller_can_filter_nan_before_binning(self):
        y = self._y([1.0, np.nan, 3.0, 1.0, np.nan, 3.0],
                     ["2024-01-02"] * 3 + ["2024-01-03"] * 3,
                     ["A", "B", "C", "D", "E", "F"])
        filtered = y.dropna()
        labels, groups = compute_relevance_labels(filtered, n_bins=3)
        assert labels.index.equals(filtered.index)
        assert list(groups) == [2, 2]

    def test_interleaved_dates_raise(self):
        y = self._y(
            [1.0, 2.0, 3.0],
            ["2024-01-02", "2024-01-03", "2024-01-02"],
            ["A", "B", "C"],
        )
        with pytest.raises(ValueError, match=r"(?i)date-contiguous"):
            compute_relevance_labels(y)

    def test_n_bins_less_than_two_raises(self):
        y = self._y([1.0, 2.0], ["2024-01-02"] * 2, ["A", "B"])
        with pytest.raises(ValueError, match=r"(?i)n_bins"):
            compute_relevance_labels(y, n_bins=1)
        with pytest.raises(ValueError, match=r"(?i)n_bins"):
            compute_relevance_labels(y, n_bins=0)
        with pytest.raises(ValueError, match=r"(?i)n_bins"):
            compute_relevance_labels(y, n_bins=-1)

    def test_n_bins_non_integer_raises(self):
        y = self._y([1.0, 2.0], ["2024-01-02"] * 2, ["A", "B"])
        with pytest.raises(ValueError, match=r"(?i)n_bins"):
            compute_relevance_labels(y, n_bins=2.5)

    @pytest.mark.parametrize("exc_type, match", [
        (TypeError, r"(?i)Series"),
        (TypeError, r"(?i)MultiIndex"),
        (ValueError, r"(?i)datetime"),
        (ValueError, r"(?i)duplicate"),
    ])
    def test_malformed_index_raises(self, exc_type, match):
        # flat non-Series
        if "Series" in match:
            with pytest.raises(exc_type, match=match):
                compute_relevance_labels(np.array([1.0, 2.0]))
            return
        # non-MultiIndex
        y = pd.Series([1.0, 2.0], index=pd.Index(["A", "B"]))
        with pytest.raises(TypeError, match=r"(?i)MultiIndex"):
            compute_relevance_labels(y)
        # missing level
        y2 = pd.Series([1.0, 2.0], index=pd.MultiIndex.from_arrays(
            [["2024-01-02", "2024-01-03"], [1, 2]], names=["datetime", "other"]))
        with pytest.raises(ValueError, match=r"(?i)instrument"):
            compute_relevance_labels(y2)
        # duplicate
        y3 = pd.Series([1.0, 2.0], index=self._idx(["2024-01-02"] * 2, ["A", "A"]))
        with pytest.raises(ValueError, match=r"(?i)duplicate"):
            compute_relevance_labels(y3)

    def test_sum_groups_equals_len_y(self):
        """Prove sum(groups) == len(labels) == len(y) invariant."""
        d = (["2024-01-02"] * 4 + ["2024-01-03"] * 3 + ["2024-01-04"] * 6)
        inst = (["A", "B", "C", "D"] + ["E", "F", "G"] + ["H", "I", "J", "K", "L", "M"])
        y = self._y(list(range(len(d))), d, inst)
        labels, groups = compute_relevance_labels(y, n_bins=5)
        assert int(groups.sum()) == len(labels) == len(y)
        assert len(groups) == 3  # 3 unique dates

    def test_group_sizes_reflect_per_date_counts(self):
        """groups[i] equals the number of instruments on the i-th unique date."""
        d = ["2024-01-02"] * 3 + ["2024-01-03"] * 7 + ["2024-01-04"] * 2
        inst = list("ABC") + list("DEFGHIJ") + list("KL")
        y = self._y(list(range(len(d))), d, inst)
        _, groups = compute_relevance_labels(y, n_bins=5)
        assert list(groups) == [3, 7, 2]


# -- make_daily_cs_ic_eval -----------------------------------------------------

class TestMakeDailyCSICEval:
    def test_perfect_and_negative_ic(self):
        """Monotonic -> IC=+1; reversed -> IC=-1; uses dataset.get_label()."""
        idx = _idx(["2024-01-02"] * 5, list("ABCDE"))
        feval = make_daily_cs_ic_eval(idx)
        ds = _MockDS([2, 4, 6, 8, 10])
        name, v1, hib = feval(np.array([1, 2, 3, 4, 5]), ds)
        assert name == "mean_daily_cs_ic"
        assert v1 == pytest.approx(1.0)
        assert hib is True
        _, v2, _ = feval(np.array([5, 4, 3, 2, 1]), ds)
        assert v2 == pytest.approx(-1.0)

    def test_daily_averaging_and_filtering(self):
        """Multi-day averaging; insufficient / constant -> skipped -> 0.0."""
        # Day 1 IC=+1, day 2 IC=-1 -> mean ~0.
        idx = _idx(["2024-01-02"] * 5 + ["2024-01-03"] * 5, list("ABCDEFGHIJ"))
        feval = make_daily_cs_ic_eval(idx)
        ds = _MockDS([2, 4, 6, 8, 10, 10, 8, 6, 4, 2])
        _, v, _ = feval(np.array([1, 2, 3, 4, 5, 1, 2, 3, 4, 5]), ds)
        assert abs(v) < 0.01
        # Day with < min_instruments skipped -> only day 2 counts (IC=+1).
        idx2 = _idx(["2024-01-02", "2024-01-02"] + ["2024-01-03"] * 4,
                    list("ABCDEF"))
        feval2 = make_daily_cs_ic_eval(idx2, min_instruments_per_day=3)
        ds2 = _MockDS([2, 4, 6, 8, 10, 12])
        _, v2, _ = feval2(np.array([1, 2, 3, 4, 5, 6]), ds2)
        assert v2 == pytest.approx(1.0)
        # All days filtered -> 0.0; constant preds -> 0.0.
        feval3 = make_daily_cs_ic_eval(
            _idx(["2024-01-02", "2024-01-02"], ["A", "B"]),
            min_instruments_per_day=5)
        _, v3, _ = feval3(np.array([1, 2]), _MockDS([3, 4]))
        assert v3 == 0.0
        feval4 = make_daily_cs_ic_eval(_idx(["2024-01-02"] * 5, list("ABCDE")))
        _, v4, _ = feval4(np.array([3] * 5), _MockDS([2, 4, 6, 8, 10]))
        assert v4 == 0.0

    @pytest.mark.parametrize("label, preds, labels", [
        ("preds shorter", [1, 2], [2, 4, 6, 8, 10]),
        ("preds longer", [1, 2, 3, 4, 5], [2, 4, 6]),
        ("labels shorter", [1, 2, 3], [1, 2]),
    ])
    def test_length_mismatch_raises(self, label, preds, labels):
        idx = _idx(["2024-01-02"] * 3, list("ABC"))
        feval = make_daily_cs_ic_eval(idx)
        ds = _MockDS(np.array(labels))
        with pytest.raises(ValueError, match="(?i)length mismatch"):
            feval(np.array(preds), ds)

    @pytest.mark.parametrize("label, idx, match, exc", [
        ("flat index", pd.Index([1, 2, 3]), "(?i)MultiIndex", TypeError),
        ("duplicate", _idx(["2024-01-02", "2024-01-02"], ["A", "A"]),
         "(?i)duplicate", ValueError),
        ("missing datetime", pd.MultiIndex.from_arrays(
            [["A", "B"], [1, 2]], names=["instrument", "other"]),
         "(?i)datetime", ValueError),
    ])
    def test_malformed_index_raises(self, label, idx, match, exc):
        with pytest.raises(exc, match=match):
            make_daily_cs_ic_eval(idx)

    def test_dataset_without_get_label_raises(self):
        idx = _idx(["2024-01-02"] * 3, list("ABC"))
        feval = make_daily_cs_ic_eval(idx)
        with pytest.raises(ValueError, match="(?i)get_label"):
            feval(np.array([1, 2, 3]), "not_a_dataset")

    def test_continuous_labels_used_when_provided(self):
        """When continuous_labels is provided, feval uses it instead of get_label()."""
        idx = _idx(["2024-01-02"] * 5, list("ABCDE"))
        continuous = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0], index=idx)
        feval = make_daily_cs_ic_eval(idx, continuous_labels=continuous)
        # Dataset has opposite labels (relevance bins), but feval uses continuous → IC=+1
        ds = _MockDS([0, 0, 1, 4, 4])
        name, v, hib = feval(np.array([1, 2, 3, 4, 5]), ds)
        assert name == "mean_daily_cs_ic"
        assert v == pytest.approx(1.0)
        assert hib is True

    def test_continuous_labels_index_mismatch_raises(self):
        idx = _idx(["2024-01-02"] * 3, list("ABC"))
        continuous = pd.Series([1.0, 2.0], index=idx[:2])
        with pytest.raises(ValueError, match=r"(?i)index"):
            make_daily_cs_ic_eval(idx, continuous_labels=continuous)

    def test_continuous_labels_relaxes_get_label_requirement(self):
        """With continuous_labels, Dataset does not need get_label()."""
        idx = _idx(["2024-01-02"] * 5, list("ABCDE"))
        continuous = pd.Series([10.0, 8.0, 6.0, 4.0, 2.0], index=idx)
        feval = make_daily_cs_ic_eval(idx, continuous_labels=continuous)
        # Dataset has no get_label
        name, v, _ = feval(np.array([1, 2, 3, 4, 5]), "no_get_label")
        assert name == "mean_daily_cs_ic"
        assert v == pytest.approx(-1.0)  # reversed continuous labels → -1 IC
