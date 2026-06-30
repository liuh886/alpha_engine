"""Cross-sectional training utilities for LightGBM stock-selection pipelines.

Target metric: mean daily cross-sectional Pearson IC.  All functions operate
on ``pd.MultiIndex`` of ``(datetime, instrument)`` and never pool dates.

Public API
----------
- :func:`compute_mean_daily_cs_ic` -- per-feature mean daily CS Pearson IC.
- :func:`select_stable_features` -- stable-sign feature selector (train + valid only).
- :func:`make_daily_cs_ic_eval` -- LightGBM custom evaluation callable factory.
- :func:`compute_relevance_labels` -- per-date integer relevance bins for lambdarank.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

CURATED_US_MOMENTUM_EXPRESSIONS = [
    "$close/Ref($close, 5)-1",
    "$close/Ref($close, 10)-1",
    "$close/Ref($close, 20)-1",
    "$close/Ref($close, 60)-1",
    "Std($close/Ref($close, 1)-1, 20)",
    "Std($close/Ref($close, 1)-1, 60)",
    "$volume/(Mean($volume, 20)+1e-12)-1",
    "$close/Mean($close, 20)-1",
    "$close/Mean($close, 60)-1",
    "($close-Max($high, 60))/(Max($high, 60)+1e-12)",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_multiindex(
    obj: pd.Series | pd.DataFrame,
    label: str,
    *,
    require_unique: bool = True,
) -> None:
    """Fail closed on malformed or missing ``(datetime, instrument)`` MultiIndex."""
    if not hasattr(obj, "index"):
        raise TypeError(f"{label} argument has no index attribute")
    idx = obj.index
    if not isinstance(idx, pd.MultiIndex):
        raise TypeError(
            f"{label} index must be pd.MultiIndex, got {type(idx).__name__}"
        )
    for level_name in ("datetime", "instrument"):
        if level_name not in idx.names:
            raise ValueError(f"{label} index missing level {level_name!r}")
    if require_unique and not idx.is_unique:
        raise ValueError(
            f"{label} index contains duplicate (datetime, instrument) entries"
        )


# ---------------------------------------------------------------------------
# Public: feature-level mean daily cross-sectional IC
# ---------------------------------------------------------------------------


def compute_mean_daily_cs_ic(
    X: pd.DataFrame,
    y: pd.Series,
    min_instruments_per_day: int = 3,
) -> pd.DataFrame:
    """Compute mean daily cross-sectional Pearson IC for every feature in *X*.

    Groups by the ``datetime`` level of the ``(datetime, instrument)``
    MultiIndex, computes cross-sectional Pearson correlation of each feature
    against *y* per trading day, then returns the mean across days.  Dates
    are **never** pooled -- the function averages per-day ICs.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix indexed by ``(datetime, instrument)`` MultiIndex.
    y : pd.Series
        Target labels with the same MultiIndex structure.
    min_instruments_per_day : int, default 3
        Minimum number of instruments required on a single date for its
        cross-sectional IC to contribute to the mean (must be >= 2).

    Returns
    -------
    pd.DataFrame
        Indexed by feature name with columns ``mean_daily_ic`` and ``n_days``.
    """
    if min_instruments_per_day < 2:
        raise ValueError(
            f"min_instruments_per_day must be >= 2, got {min_instruments_per_day}"
        )

    _validate_multiindex(X, "X")
    _validate_multiindex(y, "y")

    # Reject duplicate feature names.
    if len(X.columns) != len(set(X.columns)):
        dupes = X.columns[X.columns.duplicated()].tolist()
        raise ValueError(f"X contains duplicate feature names: {dupes}")

    # Fail closed on any index-label mismatch (including partial overlap).
    x_labels = set(X.index)
    y_labels = set(y.index)
    if x_labels != y_labels:
        raise ValueError(
            f"X and y index label sets differ: "
            f"X has {len(x_labels)} labels, y has {len(y_labels)} labels"
        )

    # Reindex y to match X row order (labels identical, order may differ).
    y = y.reindex(X.index)
    y_vals = pd.to_numeric(y, errors="coerce").values.astype(float)

    dates = X.index.get_level_values("datetime")
    feature_names = X.columns.tolist()
    results: dict[str, list[float]] = {f: [] for f in feature_names}

    for date in pd.unique(dates):
        mask = dates == date
        if mask.sum() < min_instruments_per_day:
            continue

        y_day = y_vals[mask]
        if np.std(y_day) <= 1e-12:
            continue

        for feat in feature_names:
            x_day = pd.to_numeric(
                X[feat].values[mask], errors="coerce"
            ).astype(float)

            # Filter non-finite (x, y) pairs *pairwise*.
            fin = np.isfinite(x_day) & np.isfinite(y_day)
            if fin.sum() < min_instruments_per_day:
                continue

            x_f = x_day[fin]
            y_f = y_day[fin]

            if np.std(x_f) <= 1e-12 or np.std(y_f) <= 1e-12:
                continue

            r = float(np.corrcoef(x_f, y_f)[0, 1])
            if np.isfinite(r):
                results[feat].append(r)

    records = []
    for feat in feature_names:
        ics = results[feat]
        if not ics:
            records.append({"mean_daily_ic": 0.0, "n_days": 0})
        else:
            records.append(
                {"mean_daily_ic": float(np.mean(ics)), "n_days": len(ics)}
            )

    return pd.DataFrame(records, index=pd.Index(feature_names, name="feature"))


# ---------------------------------------------------------------------------
# Public: stable-sign feature selector
# ---------------------------------------------------------------------------


def select_stable_features(
    train_X: pd.DataFrame,
    train_y: pd.Series,
    valid_X: pd.DataFrame,
    valid_y: pd.Series,
    max_features: int = 50,
    min_instruments_per_day: int = 3,
) -> pd.DataFrame:
    """Select features whose cross-sectional IC sign is stable across train/valid.

    For each feature, computes the mean daily cross-sectional IC independently
    on *train_X*/*train_y* and *valid_X*/*valid_y* (never pools dates across
    periods or features).

    The **score** is::

        score = min(|train_ic|, |valid_ic|)  if sign(train_ic) == sign(valid_ic)
                                              AND both ICs are nonzero
              = 0.0                           otherwise

    Features with score zero are excluded.  The top *max_features* are
    returned ordered by descending score, then ascending feature name for
    deterministic tie-breaking.

    If fewer than *max_features* features qualify, all qualifying features are
    returned without error.

    **This function never inspects test data.**  It fails closed on malformed
    or misaligned indexes and on train/valid feature-name mismatch.

    Parameters
    ----------
    train_X : pd.DataFrame
        Training features with ``(datetime, instrument)`` MultiIndex.
    train_y : pd.Series
        Training labels with the same MultiIndex structure.
    valid_X : pd.DataFrame
        Validation features with ``(datetime, instrument)`` MultiIndex.
    valid_y : pd.Series
        Validation labels with the same MultiIndex structure.
    max_features : int, default 50
        Maximum number of features to return (must be >= 1).
    min_instruments_per_day : int, default 3
        Forwarded to :func:`compute_mean_daily_cs_ic`.

    Returns
    -------
    pd.DataFrame
        Indexed by feature name with columns ``train_ic``, ``valid_ic``,
        ``score``, and ``rank``.
    """
    if max_features < 1:
        raise ValueError(f"max_features must be positive, got {max_features}")

    # Fail closed on train/valid feature-name mismatch (do not silently intersect).
    train_cols = set(train_X.columns)
    valid_cols = set(valid_X.columns)
    if train_cols != valid_cols:
        only_train = train_cols - valid_cols
        only_valid = valid_cols - train_cols
        detail = []
        if only_train:
            detail.append(f"only in train: {sorted(only_train)}")
        if only_valid:
            detail.append(f"only in valid: {sorted(only_valid)}")
        raise ValueError(f"Feature name mismatch: {'; '.join(detail)}")

    train_ic_df = compute_mean_daily_cs_ic(
        train_X, train_y, min_instruments_per_day=min_instruments_per_day
    )
    valid_ic_df = compute_mean_daily_cs_ic(
        valid_X, valid_y, min_instruments_per_day=min_instruments_per_day
    )

    t_arr = train_ic_df["mean_daily_ic"].values
    # Reindex valid ICs by train feature name so features pair correctly even
    # when train_X and valid_X have identical feature sets in different order.
    v_arr = valid_ic_df.reindex(train_ic_df.index)["mean_daily_ic"].values

    # Score: min(|train_ic|, |valid_ic|) only when both nonzero AND signs agree.
    same_sign = np.sign(t_arr) == np.sign(v_arr)
    both_nonzero = (np.abs(t_arr) > 1e-15) & (np.abs(v_arr) > 1e-15)
    qualifies = same_sign & both_nonzero

    scores = np.where(qualifies, np.minimum(np.abs(t_arr), np.abs(v_arr)), 0.0)

    result = pd.DataFrame(
        {"train_ic": t_arr, "valid_ic": v_arr, "score": scores},
        index=train_ic_df.index,
    )
    result.index.name = "feature"

    # Exclude zero-score features entirely.
    result = result[result["score"] > 0].copy()

    # Deterministic sort: descending score, ascending feature name.
    result["_name"] = result.index.astype(str)
    result = result.sort_values(["score", "_name"], ascending=[False, True])
    result = result.drop(columns=["_name"])

    # Take top max_features.
    result = result.iloc[:max_features]
    result["rank"] = range(1, len(result) + 1)

    return result[["train_ic", "valid_ic", "score", "rank"]]


# ---------------------------------------------------------------------------
# Public: relevance labels for lambdarank training
# ---------------------------------------------------------------------------


def compute_relevance_labels(
    y: pd.Series,
    n_bins: int = 5,
) -> tuple[pd.Series, np.ndarray]:
    """Convert continuous *y* into per-date integer relevance bins.

    For each unique date in the ``(datetime, instrument)`` MultiIndex,
    rows are rank-binned into ``0 … n_bins - 1`` where ``n_bins - 1`` is
    the highest forward return (most relevant).  Returns a **labels**
    Series with the same index as *y* (so callers cannot misalign data)
    and a **groups** array of per-date instrument counts suitable for
    ``lgb.Dataset(…, group=…)`` or ``dataset.set_group(…)``.

    The returned labels and groups satisfy::

        sum(groups) == len(labels) == len(y)
        groups[i] == number of instruments on the i-th unique date
                     (in date-contiguous order)

    Parameters
    ----------
    y : pd.Series
        Continuous target values indexed by ``(datetime, instrument)``
        MultiIndex.  The index must be unique and sorted in date-contiguous
        order (the sort order of the MultiIndex is preserved).
    n_bins : int, default 5
        Number of integer relevance labels (must be ``>= 2``).
    Returns
    -------
    labels : pd.Series
        Integer relevance labels ``0 … n_bins - 1`` for every row, with
        the same index as *y*.
    groups : np.ndarray
        1-D array of group sizes, one element per unique date in
        date-contiguous order.

    Raises
    ------
    TypeError
        If *y* is not a ``pd.Series`` or its index is not a ``pd.MultiIndex``.
    ValueError
        If the index is missing required levels, is not unique,
        *n_bins* < 2, dates are not row-contiguous, or *y* contains
        non-finite values.
    """
    if not isinstance(y, pd.Series):
        raise TypeError(f"y must be a pd.Series, got {type(y).__name__}")
    _validate_multiindex(y, "y")
    if not isinstance(n_bins, int) or n_bins < 2:
        raise ValueError(
            f"n_bins must be an integer >= 2, got {n_bins!r}"
        )

    values = pd.to_numeric(y, errors="coerce").values.astype(float)

    if np.any(~np.isfinite(values)):
        raise ValueError(
            "y contains NaN or non-finite values; filter them before binning"
        )

    dates = y.index.get_level_values("datetime")
    unique_dates = pd.unique(dates)
    seen_dates: set[Any] = set()
    previous_date: Any = object()
    for date in dates:
        if date != previous_date:
            if date in seen_dates:
                raise ValueError(
                    "y rows must be date-contiguous for LightGBM group alignment"
                )
            seen_dates.add(date)
            previous_date = date
    n_dates = len(unique_dates)

    labels = np.zeros(len(y), dtype=int)
    groups = np.zeros(n_dates, dtype=int)

    for i, date in enumerate(unique_dates):
        mask = dates == date
        groups[i] = int(np.sum(mask))
        date_vals = values[mask]

        dense_ranks = pd.Series(date_vals).rank(method="dense").to_numpy() - 1
        max_rank = int(dense_ranks.max())
        if max_rank > 0:
            labels[mask] = np.floor(
                dense_ranks * (n_bins - 1) / max_rank
            ).astype(int)

    return pd.Series(labels, index=y.index, name="relevance"), groups


def monotone_constraints_from_selection(selection: pd.DataFrame) -> list[int]:
    """Map stable feature IC signs to LightGBM constraints in row order."""
    required = {"train_ic", "valid_ic"}
    if not required.issubset(selection.columns):
        raise ValueError("Selection must contain train_ic and valid_ic columns")
    if not selection.index.is_unique:
        raise ValueError("Selection feature index must be unique")

    constraints: list[int] = []
    for feature, row in selection.iterrows():
        train_ic = float(row["train_ic"])
        valid_ic = float(row["valid_ic"])
        if (
            not np.isfinite(train_ic)
            or not np.isfinite(valid_ic)
            or train_ic == 0.0
            or valid_ic == 0.0
            or np.sign(train_ic) != np.sign(valid_ic)
        ):
            raise ValueError(
                f"Feature {feature!r} must have a stable non-zero train/valid IC sign"
            )
        constraints.append(1 if train_ic > 0 else -1)
    return constraints


# ---------------------------------------------------------------------------
# Public: LightGBM custom evaluation callable factory
# ---------------------------------------------------------------------------


def make_daily_cs_ic_eval(
    validation_index: pd.MultiIndex,
    min_instruments_per_day: int = 3,
    continuous_labels: pd.Series | None = None,
) -> Callable[[np.ndarray, Any], tuple[str, float, bool]]:
    """Return a LightGBM-compatible custom evaluation callable.

    The returned callable computes **mean daily cross-sectional Pearson IC**
    between the model's predictions and the ground-truth labels.  When
    *continuous_labels* is ``None`` (default), labels are obtained from the
    LightGBM ``Dataset`` via ``get_label()``.  When provided, the array is
    used **instead** — this is essential in ``lambdarank`` training where
    ``Dataset`` labels are integer relevance bins and IC must be measured
    against the original continuous returns.

    It groups by the ``datetime`` level of *validation_index*, computes
    cross-sectional IC per day, and returns the mean.

    Parameters
    ----------
    validation_index : pd.MultiIndex
        The ``(datetime, instrument)`` MultiIndex defining the validation
        period.  Must be unique with levels ``datetime`` and ``instrument``.
    min_instruments_per_day : int, default 3
        Minimum instruments per date for a day's CS IC to be included.
    continuous_labels : pd.Series, optional
        Explicit continuous labels with an index exactly matching
        *validation_index*.
        When provided, these are used instead of ``dataset.get_label()``.

    Returns
    -------
    callable
        A function ``f(preds, dataset) -> (name, value, higher_is_better)``
        suitable for ``lgb.train(..., feval=f)``.

    Raises
    ------
    TypeError
        If *validation_index* is not a ``pd.MultiIndex``.
    ValueError
        If *validation_index* is malformed (missing levels, duplicates),
        *min_instruments_per_day* < 2, or *continuous_labels* is not exactly
        index-aligned.
    """
    if min_instruments_per_day < 2:
        raise ValueError(
            f"min_instruments_per_day must be >= 2, got {min_instruments_per_day}"
        )

    if not isinstance(validation_index, pd.MultiIndex):
        raise TypeError(
            f"validation_index must be pd.MultiIndex, "
            f"got {type(validation_index).__name__}"
        )

    for level_name in ("datetime", "instrument"):
        if level_name not in validation_index.names:
            raise ValueError(
                f"validation_index missing level {level_name!r}"
            )

    if not validation_index.is_unique:
        raise ValueError("validation_index contains duplicate entries")

    dates = validation_index.get_level_values("datetime")
    unique_dates = pd.unique(dates)

    # Pre-compute date boolean masks.
    date_masks: dict[pd.Timestamp, np.ndarray] = {}
    for date in unique_dates:
        date_masks[date] = (dates == date)

    n_total = len(validation_index)

    # Pre-validate continuous_labels length once.
    if continuous_labels is not None:
        if not isinstance(continuous_labels, pd.Series):
            raise TypeError("continuous_labels must be a pd.Series")
        if not continuous_labels.index.equals(validation_index):
            raise ValueError(
                "continuous_labels index must exactly match validation_index"
            )
        _external_labels = continuous_labels.to_numpy(dtype=float)
    else:
        _external_labels = None

    def _eval(
        preds: np.ndarray,
        dataset: Any,
    ) -> tuple[str, float, bool]:
        preds = np.asarray(preds, dtype=float)

        if _external_labels is not None:
            labels = _external_labels
        else:
            if not hasattr(dataset, "get_label"):
                raise ValueError("dataset must have a get_label() method")
            labels = np.asarray(dataset.get_label(), dtype=float)

        # Fail closed on any length mismatch.
        if len(preds) != n_total or len(labels) != n_total:
            raise ValueError(
                f"Length mismatch: index has {n_total} entries, "
                f"predictions have {len(preds)}, labels have {len(labels)}"
            )

        daily_ics: list[float] = []
        for date_mask in date_masks.values():
            if date_mask.sum() < min_instruments_per_day:
                continue

            p_day = preds[date_mask]
            l_day = labels[date_mask]

            # Filter non-finite pairs.
            fin = np.isfinite(p_day) & np.isfinite(l_day)
            if fin.sum() < min_instruments_per_day:
                continue

            p_f = p_day[fin]
            l_f = l_day[fin]

            if np.std(p_f) <= 1e-12 or np.std(l_f) <= 1e-12:
                continue

            r = float(np.corrcoef(p_f, l_f)[0, 1])
            if np.isfinite(r):
                daily_ics.append(r)

        if not daily_ics:
            return ("mean_daily_cs_ic", 0.0, True)

        return ("mean_daily_cs_ic", float(np.mean(daily_ics)), True)

    return _eval
