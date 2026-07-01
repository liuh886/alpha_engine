"""Walk-forward validation for expanding-window model evaluation.

Provides two implementations:

1. **Qlib-based** (``walk_forward_validate``) — uses Qlib's DataHandlerLP +
   LGBModel pipeline.  Slow (~4 min / 6 splits) but matches production config.

2. **Vectorized** (``walk_forward_vectorized``) — pre-loads Alpha158 features
   once, trains LightGBM directly per split.  ~3.5× faster because it avoids
   per-split DataHandlerLP initialization.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import structlog
import yaml
from qlib.data import D
from qlib.utils import init_instance_by_config

log = structlog.get_logger()

_MAX_CALENDAR_BOUNDARY_GAP_DAYS = 14


def _add_months(dt: datetime, months: int) -> datetime:
    """Add *months* calendar months to *dt*, clamping the day to end-of-month."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    import calendar

    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Trading-calendar helpers for label-horizon gap
# ---------------------------------------------------------------------------


def _get_trading_calendar(start: str | None = None, end: str | None = None) -> pd.DatetimeIndex:
    """Return sorted unique trading dates from the active Qlib calendar.

    Args:
        start: Optional start date filter (YYYY-MM-DD).
        end: Optional end date filter (YYYY-MM-DD).

    Returns:
        A ``pd.DatetimeIndex`` of trading-day timestamps.  Returns an empty
        index if Qlib is not initialized or the calendar is unavailable.
    """
    try:
        from qlib.data import D

        kwargs: dict = {}
        if start is not None:
            kwargs["start_time"] = start
        if end is not None:
            kwargs["end_time"] = end
        cal = D.calendar(**kwargs)
        return pd.DatetimeIndex([pd.Timestamp(str(c)) for c in cal])
    except Exception:
        log.debug("Cannot access Qlib trading calendar", exc_info=True)
        return pd.DatetimeIndex([])


def _validate_calendar(
    cal: pd.DatetimeIndex,
    required_start: str,
    required_end: str,
) -> None:
    """Fail closed on calendar integrity or coverage problems.

    Raises ``RuntimeError`` for: empty, NaT, duplicate, unordered
    (non-monotonic), or incomplete boundary coverage. Requested boundaries
    may be exchange holidays, so the first or last observed session may be
    up to 14 calendar days inside the requested range.
    """
    if len(cal) == 0:
        raise RuntimeError(
            "Trading calendar is empty — Qlib may not be initialized"
        )
    if cal.hasnans:
        raise RuntimeError("Trading calendar contains NaT values")
    if not cal.is_unique:
        raise RuntimeError("Trading calendar contains duplicate dates")
    if not cal.is_monotonic_increasing:
        raise RuntimeError(
            "Trading calendar is not monotonically increasing (unordered)"
        )
    req_start_ts = pd.Timestamp(required_start)
    req_end_ts = pd.Timestamp(required_end)
    if (
        cal[0] > req_start_ts
        and (cal[0] - req_start_ts).days > _MAX_CALENDAR_BOUNDARY_GAP_DAYS
    ):
        raise RuntimeError(
            f"Trading calendar starts at {cal[0].date()}, "
            f"after required start {required_start}"
        )
    if (
        cal[-1] < req_end_ts
        and (req_end_ts - cal[-1]).days > _MAX_CALENDAR_BOUNDARY_GAP_DAYS
    ):
        raise RuntimeError(
            f"Trading calendar ends at {cal[-1].date()}, "
            f"before required end {required_end}"
        )


def _safe_end_date(
    calendar: pd.DatetimeIndex,
    boundary: pd.Timestamp,
    label_horizon: int,
) -> pd.Timestamp:
    """Return the latest date whose label cannot peek into *boundary* or later.

    The hardcoded label ``Ref($close, -10) / Ref($close, -1) - 1`` uses
    ``Ref($close, -10)`` which shifts 10 observations **forward**.  For a
    segment whose next boundary is *boundary*, the last safe date is the
    one whose ``T + label_horizon`` is still **before** *boundary*.

    The returned date leaves exactly *label_horizon* trading days
    strictly between itself and *boundary*.  When *boundary* is a
    non-trading day the first trading session at or after *boundary* is
    used as the anchor, so the gap is measured to the boundary itself and
    the result is never over-purged.
    """
    if label_horizon <= 0 or len(calendar) == 0:
        return boundary
    # Anchor: first trading session at or after boundary.  Using
    # side="left" avoids over-purging when boundary is non-trading
    # (the old code used nearest <=, which subtracted horizon+1 from
    # the last trading day *before* the boundary and lost an extra day).
    anchor_pos = calendar.searchsorted(boundary, side="left")
    if anchor_pos >= len(calendar):
        raise RuntimeError(
            f"Boundary {boundary.date()} is beyond the last trading session "
            f"({calendar[-1].date()}). Calendar coverage is incomplete."
        )
    if anchor_pos <= label_horizon:
        raise RuntimeError(
            f"Insufficient trading sessions before boundary {boundary.date()}: "
            f"need at least {label_horizon} prior sessions, "
            f"but only {anchor_pos} are available in the calendar."
        )
    target_pos = anchor_pos - (label_horizon + 1)
    return calendar[target_pos]


@dataclass
class SplitResult:
    """Metrics for a single walk-forward split."""

    split_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    ic: float | None  # Pearson IC (None if split failed/skipped)
    rank_ic: float | None  # Spearman rank IC (None if split failed/skipped)
    status: str = "success"  # "success", "failed", "skipped"
    error_message: str | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    annual_return: float | None = None


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward validation results."""

    market: str
    model_type: str
    splits: list[SplitResult] = field(default_factory=list)
    mean_ic: float = 0.0
    std_ic: float = 0.0
    ic_ir: float = 0.0  # mean_ic / std_ic
    consistency_score: float = 0.0  # % of splits with positive IC
    n_success: int = 0
    n_failed: int = 0
    n_skipped: int = 0

    def aggregate(self) -> None:
        """Compute summary statistics from split IC values.

        Only splits with valid (non-None) IC values are included in the
        aggregation.  Failed or skipped splits are excluded so they do
        not pollute the summary statistics with zero values.
        """
        if not self.splits:
            return

        # Count split statuses
        self.n_success = sum(1 for s in self.splits if s.status == "success" and s.ic is not None)
        self.n_failed = sum(1 for s in self.splits if s.status == "failed")
        self.n_skipped = sum(1 for s in self.splits if s.status == "skipped")

        # Filter to only successful splits with valid IC values
        valid_ics = [s.ic for s in self.splits if s.ic is not None and s.status == "success"]
        if not valid_ics:
            log.warning(
                "No splits with valid IC values for aggregation",
                n_success=self.n_success,
                n_failed=self.n_failed,
                n_skipped=self.n_skipped,
            )
            return
        self.mean_ic = float(np.mean(valid_ics))
        self.std_ic = float(np.std(valid_ics, ddof=1)) if len(valid_ics) > 1 else 0.0
        self.ic_ir = self.mean_ic / self.std_ic if self.std_ic > 1e-12 else 0.0
        self.consistency_score = float(np.mean([1.0 if ic > 0 else 0.0 for ic in valid_ics]))


def generate_splits(
    train_start: str = "2021-01-01",
    train_end: str = None,
    test_window_months: int = 6,
    step_months: int = 3,
    min_train_months: int = 12,
) -> list[tuple[str, str, str, str]]:
    """Generate expanding-window splits.

    Each split trains from ``train_start`` to a moving ``train_end``,
    then tests on the following ``test_window_months`` period.  The
    ``train_end`` advances by ``step_months`` each iteration.

    The first candidate test window begins at
    ``train_start + min_train_months``, but this is a **nominal**
    boundary — the label-horizon purge and validation hold-out reduce
    the actual training window.  Callers such as
    ``walk_forward_vectorized`` re-check the actual training duration
    before each split and skip candidates that fall short.

    Args:
        min_train_months: Minimum calendar months of training data
            (nominal candidate boundary).  The actual training data
            provided to the model may be shorter after purging.
            ``walk_forward_vectorized`` enforces actual-fit >= this
            value.  Default 12.  Must be >= 1.

    Returns:
        List of (train_start, train_end, test_start, test_end) tuples.
    """
    from src.common.dates import default_train_end

    if min_train_months < 1:
        raise ValueError(
            f"min_train_months must be >= 1, got {min_train_months}"
        )

    train_end = train_end or default_train_end()
    start = datetime.strptime(train_start, "%Y-%m-%d")
    end = datetime.strptime(train_end, "%Y-%m-%d")

    # First train_end is at least min_train_months from start so the model
    # has enough data to learn.
    min_train_end = _add_months(start, min_train_months)

    splits: list[tuple[str, str, str, str]] = []
    current_end = min_train_end

    while True:
        test_start_dt = current_end
        test_end_dt = _add_months(test_start_dt, test_window_months)

        # Do not create a split whose test window is entirely in the past
        # of the overall training range -- we need test data.
        if test_start_dt >= end:
            break

        # Clip test_end to overall range.
        actual_test_end = min(test_end_dt, end)
        if actual_test_end <= test_start_dt:
            break

        splits.append(
            (
                train_start,
                current_end.strftime("%Y-%m-%d"),
                test_start_dt.strftime("%Y-%m-%d"),
                actual_test_end.strftime("%Y-%m-%d"),
            )
        )

        current_end = _add_months(current_end, step_months)

        # Stop if the next train_end would push test_start past end.
        next_test_start = current_end
        if next_test_start >= end:
            break

    log.info(
        "Generated walk-forward splits",
        n_splits=len(splits),
        train_start=train_start,
        train_end=train_end,
        test_window_months=test_window_months,
        step_months=step_months,
        min_train_months=min_train_months,
    )
    return splits


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Return ranks (0-based, averaged for ties) — avoids scipy dependency."""
    return pd.Series(a).rank(method="average").to_numpy(dtype=float) - 1.0


def _compute_ic(predictions: np.ndarray, actuals: np.ndarray) -> tuple[float, float]:
    """Compute Pearson and Spearman rank IC between predictions and actuals.

    Returns:
        (pearson_ic, rank_ic) tuple.
    """
    mask = np.isfinite(predictions) & np.isfinite(actuals)
    if mask.sum() < 5:
        return 0.0, 0.0

    pred = predictions[mask]
    act = actuals[mask]

    pearson_ic = float(np.corrcoef(pred, act)[0, 1]) if np.std(pred) > 1e-12 else 0.0

    rank_ic = 0.0
    if np.std(pred) > 1e-12:
        r_pred = _rankdata(pred)
        r_act = _rankdata(act)
        corr = np.corrcoef(r_pred, r_act)[0, 1]
        rank_ic = float(corr) if np.isfinite(corr) else 0.0

    if np.isnan(pearson_ic):
        pearson_ic = 0.0
    if np.isnan(rank_ic):
        rank_ic = 0.0

    return pearson_ic, rank_ic


def _compute_mean_daily_ic(
    predictions: np.ndarray,
    actuals: pd.Series,
    min_stocks_per_day: int = 3,
) -> tuple[float, float]:
    """Compute index-aligned mean daily cross-sectional Pearson and rank IC.

    Groups by the ``datetime`` level of *actuals* MultiIndex, computes
    cross-sectional Pearson and rank IC per trading day, and returns the
    mean across days.  This replaces the old pooled/global IC which could
    be dominated by dates with many stocks and was sensitive to the order
    of predictions and actuals arrays.

    Falls back to single pooled ``_compute_ic`` when *actuals* lacks a
    ``pd.MultiIndex`` with a ``datetime`` level (e.g. flat-index test
    fixtures).

    Args:
        predictions: 1-D array of predicted values, same length as *actuals*.
        actuals: Series whose index is a ``(datetime, instrument)``
            ``pd.MultiIndex`` holding the ground-truth labels.
        min_stocks_per_day: Minimum number of stocks required on a single
            date for its cross-sectional IC to be included in the mean.

    Returns:
        (mean_daily_pearson_ic, mean_daily_rank_ic).
    """
    if len(predictions) != len(actuals):
        return 0.0, 0.0

    idx = actuals.index if hasattr(actuals, "index") else None
    if idx is None or not isinstance(idx, pd.MultiIndex) or "datetime" not in idx.names:
        # Fall back to pooled IC for backward compat (flat-index test fixtures)
        act_vals = actuals.values if hasattr(actuals, "values") else np.asarray(actuals)
        return _compute_ic(np.asarray(predictions), act_vals)

    df = pd.DataFrame({"pred": np.asarray(predictions), "act": actuals.values}, index=idx)
    df = df[np.isfinite(df["pred"]) & np.isfinite(df["act"])]
    if len(df) < 5:
        return 0.0, 0.0

    daily_p: list[float] = []
    daily_r: list[float] = []
    for _date, group in df.groupby(level="datetime"):
        if len(group) < min_stocks_per_day:
            continue
        pred = group["pred"].values
        act = group["act"].values

        std_p, std_a = np.std(pred), np.std(act)
        if std_p <= 1e-12 or std_a <= 1e-12:
            continue

        p = float(np.corrcoef(pred, act)[0, 1])
        r_pred = _rankdata(pred)
        r_act = _rankdata(act)
        r = float(np.corrcoef(r_pred, r_act)[0, 1])
        if np.isfinite(p) and np.isfinite(r):
            daily_p.append(p)
            daily_r.append(r)

    if not daily_p:
        return 0.0, 0.0
    return float(np.mean(daily_p)), float(np.mean(daily_r))


def _align_multiindex(
    a: pd.Series | pd.DataFrame,
    b: pd.Series | pd.DataFrame,
) -> tuple:
    """Label-align two pandas objects by intersecting (datetime, instrument) MultiIndex.

    Never falls back to positional alignment.  Raises ``TypeError`` /
    ``ValueError`` for unusable or duplicate indexes so callers fail
    closed instead of silently producing wrong matches.

    Returns:
        ``(a_aligned, b_aligned)`` — both indexed by the intersection.
    """
    for obj, label in ((a, "first"), (b, "second")):
        if not hasattr(obj, "index"):
            raise TypeError(f"{label} argument has no index attribute")
        idx = obj.index
        if not isinstance(idx, pd.MultiIndex):
            raise TypeError(
                f"{label} argument index must be pd.MultiIndex, "
                f"got {type(idx).__name__}"
            )
        for level_name in ("datetime", "instrument"):
            if level_name not in idx.names:
                raise ValueError(
                    f"{label} argument index missing level {level_name!r}"
                )
        if not idx.is_unique:
            raise ValueError(
                f"{label} argument index contains duplicate "
                "(datetime, instrument) entries"
            )

    common = a.index.intersection(b.index).sort_values()
    if len(common) == 0:
        raise ValueError(
            "No common (datetime, instrument) pairs between the two arguments"
        )
    return a.loc[common], b.loc[common]


def _subtract_benchmark_by_date(
    stock_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> pd.Series:
    """Subtract one benchmark return from every stock on the same date."""
    if not isinstance(stock_returns.index, pd.MultiIndex):
        raise TypeError("Stock returns must use a MultiIndex")
    if "datetime" not in stock_returns.index.names:
        raise ValueError("Stock return index must contain a 'datetime' level")
    if not benchmark_returns.index.is_unique:
        raise ValueError("Benchmark returns must contain one value per date")

    benchmark = benchmark_returns.copy()
    benchmark.index = pd.DatetimeIndex(pd.to_datetime(benchmark.index), name="datetime")
    dates = pd.DatetimeIndex(stock_returns.index.get_level_values("datetime"))
    aligned = benchmark.reindex(dates).to_numpy(dtype=float)
    return pd.Series(
        stock_returns.to_numpy(dtype=float) - aligned,
        index=stock_returns.index,
        name=stock_returns.name,
    )


def _normalize_qlib_index(data: pd.Series | pd.DataFrame):
    """Return Qlib data sorted with ``datetime`` as the first index level."""
    if not isinstance(data.index, pd.MultiIndex):
        return data
    if set(data.index.names) != {"datetime", "instrument"}:
        raise ValueError(
            "Qlib data must use exactly the 'datetime' and 'instrument' index levels"
        )
    return data.reorder_levels(["datetime", "instrument"]).sort_index()


def _forward_return_expression(label_horizon: int) -> str:
    """Build the Qlib forward-return target used by vectorized training."""
    target_horizon = label_horizon if label_horizon > 0 else 10
    return f"Ref($close, -{target_horizon}) / Ref($close, -1) - 1"


def _load_raw_labels(
    config: dict,
    test_start: str,
    test_end: str,
) -> pd.Series:
    """Load raw forward returns for the test period directly from Qlib data.

    Reads the exact configured label expression (e.g.
    ``Ref($close, -10) / $close - 1``) from Qlib data without applying any
    learn processors.  Instruments are resolved from the handler kwargs, not
    from the top-level config key.

    Args:
        config: Workflow config dict.
        test_start: Test period start date (YYYY-MM-DD).
        test_end: Test period end date (YYYY-MM-DD).

    Returns:
        ``pd.Series`` with raw forward returns, indexed by ``(datetime, instrument)``.

    Raises:
        RuntimeError: If the label expression is missing or data loading fails.
    """
    handler_kwargs = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    label_exprs: list[str] = list(handler_kwargs.get("label", []))
    if not label_exprs:
        raise RuntimeError(
            "No label expression in handler kwargs. "
            "Cannot load raw forward returns."
        )
    label_expr = label_exprs[0]
    instr_key = handler_kwargs.get("instruments", "us")
    symbols = D.list_instruments(D.instruments(instr_key), as_list=True)
    raw = D.features(symbols, [label_expr], start_time=test_start, end_time=test_end)
    # Normalize to canonical (datetime, instrument) order — D.features
    # may return MultiIndex ordered as (instrument, datetime).
    raw = _normalize_qlib_index(raw)
    if raw.empty:
        raise RuntimeError(
            f"Raw labels DataFrame is empty for expression {label_expr!r} "
            f"over period {test_start} to {test_end}. "
            "No data available — check Qlib data coverage."
        )
    if raw.shape[1] == 0:
        raise RuntimeError(
            f"Raw labels DataFrame has no columns for expression {label_expr!r}."
        )
    col = raw.iloc[:, 0]
    # Replace inf with NaN, then drop non-finite rows
    col = col.replace([np.inf, -np.inf], np.nan)
    n_raw = len(col)
    n_finite = int(col.notna().sum())
    if n_finite == 0:
        raise RuntimeError(
            f"Raw labels contain zero finite values for expression {label_expr!r} "
            f"over period {test_start} to {test_end}. "
            "All values are NaN, inf, or missing."
        )
    col = col.dropna()
    col.attrs["n_raw_rows"] = n_raw
    col.attrs["n_dropped_non_finite"] = n_raw - n_finite
    col.attrs["n_valid_rows"] = n_finite
    return col


# ---------------------------------------------------------------------------
# Native estimator adapter (lightgbm.LGBMRegressor etc.)
# ---------------------------------------------------------------------------


def _is_native_estimator_config(cfg: dict) -> bool:
    """Return True if the model config creates a native sklearn estimator (e.g.
    ``lightgbm.LGBMRegressor``) rather than a Qlib model wrapper (e.g.
    ``qlib.contrib.model.gbdt.LGBModel``).

    The check inspects ``module_path``: native if it contains ``lightgbm``
    without a ``qlib`` prefix.
    """
    model_cfg = cfg.get("task", {}).get("model", {})
    module_path: str = model_cfg.get("module_path", "")
    return bool(module_path and "lightgbm" in module_path and "qlib" not in module_path)


def _prepare_native_dataset(
    dataset,
    segments: dict[str, list[str]],
) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    """Extract aligned features (X) and learning labels (y) from a DatasetH
    for native sklearn-style estimators.

    For each of ``"train"``, ``"valid"``, ``"test"`` in *segments* the returned
    dict has an entry whose value is ``(X_df, y_series)`` with:

    - A common ``(datetime, instrument)`` MultiIndex (intersection of feature
      and label rows).
    - Only fully-finite rows — non-finite values in either X or y are dropped
      and counted.

    Args:
        dataset: A Qlib ``DatasetH`` instance that has already been configured
            and can respond to ``.prepare()``.
        segments: Dict mapping segment name to ``[start, end]`` date lists,
            e.g. ``{"train": ["2021-01-01", "2023-12-31"], ...}``.  The
            format matches what ``DatasetH.prepare(segments=...)`` accepts
            as an explicit date range.

    Returns:
        Dict with keys ``"train"``, ``"valid"``, ``"test"`` (when present).
        Segments missing from *segments* are omitted from the result.
    """
    from qlib.data.dataset.handler import DataHandler

    result: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    for seg_name in ("train", "valid", "test"):
        seg = segments.get(seg_name)
        if not seg or not isinstance(seg, (list, tuple)) or len(seg) != 2:
            continue

        try:
            X = dataset.prepare(segments=seg_name, col_set="feature")
            y = dataset.prepare(
                segments=seg_name, col_set="label", data_key=DataHandler.DK_L
            )
        except Exception:
            log.warning("Cannot prepare native dataset segment", segment=seg_name)
            continue

        if X is None or y is None or X.empty or y.empty:
            log.warning(
                "Empty native dataset segment",
                segment=seg_name,
                X_empty=X.empty if X is not None else True,
                y_empty=y.empty if y is not None else True,
            )
            continue

        # y may be a DataFrame with one column — squeeze to Series
        if isinstance(y, pd.DataFrame):
            y = y.iloc[:, 0]

        # Align by common (datetime, instrument) MultiIndex
        try:
            X, y = _align_multiindex(X, y)  # type: ignore[assignment]
        except (TypeError, ValueError) as exc:
            log.warning(
                "Native dataset segment index alignment failed",
                segment=seg_name,
                error=str(exc),
            )
            continue

        # Drop rows where any feature or label is non-finite
        X_vals = X.values
        y_vals = y.values
        if not np.issubdtype(X_vals.dtype, np.floating):
            X_vals = X_vals.astype(np.float64)
        if not np.issubdtype(y_vals.dtype, np.floating):
            y_vals = y_vals.astype(np.float64)

        finite_X = np.isfinite(X_vals).all(axis=1)
        finite_y = np.isfinite(y_vals)
        both_finite = finite_X & finite_y
        n_dropped = len(both_finite) - int(both_finite.sum())
        if n_dropped > 0:
            log.debug(
                "Dropped non-finite rows in native dataset",
                segment=seg_name,
                n_dropped=n_dropped,
            )

        X = X.loc[both_finite]
        y = y.loc[both_finite]

        if X.empty or y.empty:
            log.warning("Empty after finite check in native dataset", segment=seg_name)
            continue

        result[seg_name] = (X, y)

    return result


def _fit_native_estimator(
    model,
    dataset,
    segments: dict[str, list[str]],
) -> tuple:
    """Fit a native sklearn-style estimator with features/labels from a DatasetH.

    Steps:
    1. Extract train/valid/test features and labels via
       ``_prepare_native_dataset``.
    2. Fit the model on ``(X_train, y_train)``, optionally passing
       ``eval_set=[(X_valid, y_valid)]`` for early-stopping / monitoring.
    3. Predict on ``X_test``, returning predictions as a ``pd.Series``
       with the test MultiIndex.

    Args:
        model: A native sklearn-style estimator (e.g. ``lightgbm.LGBMRegressor``)
            that implements ``fit(X, y)`` and optionally supports
            ``eval_set=``.
        dataset: A Qlib ``DatasetH`` instance with configured segments.
        segments: Dict mapping segment name to ``[start, end]`` date lists.

    Returns:
        ``(fitted_model, predictions_series)`` where *predictions_series*
        is a ``pd.Series`` with ``(datetime, instrument)`` MultiIndex and
        name ``"prediction"``.

    Raises:
        RuntimeError: If train or test data is unavailable after preparation.
    """
    data = _prepare_native_dataset(dataset, segments)

    train_entry = data.get("train")
    test_entry = data.get("test")
    valid_entry = data.get("valid")

    if train_entry is None:
        raise RuntimeError("No training data available for native estimator fit")
    if test_entry is None:
        raise RuntimeError("No test data available for native estimator prediction")

    X_tr, y_tr = train_entry
    X_te, y_te = test_entry

    fit_kw: dict = {}
    if valid_entry is not None:
        X_va, y_va = valid_entry
        if len(X_va) > 0:
            fit_kw["eval_set"] = [(X_va, y_va)]

    model.fit(X_tr, y_tr, **fit_kw)

    pred_arr = model.predict(X_te)
    predictions = pd.Series(pred_arr, index=X_te.index, name="prediction")
    return model, predictions


def _run_single_split(
    base_config: dict,
    split_id: int,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    label_horizon: int = 10,
) -> SplitResult:
    """Train on one split and compute IC on the test period.

    This reuses Qlib's ``init_instance_by_config`` pipeline so the
    same feature engineering / preprocessing is applied as in normal
    training.

    Args:
        label_horizon: Trading days the label expression looks forward
            (default 10 for the standard ``Ref($close, -10) / Ref($close, -1) - 1``
            label).  When > 0, a gap of *label_horizon* trading days is inserted
            between label-bearing segments (train/valid) and the following
            segment, preventing forward-label leakage.
    """
    cfg = copy.deepcopy(base_config)

    # Update handler time range
    handler_kw = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    handler_kw["start_time"] = train_start
    handler_kw["end_time"] = test_end

    # Update train/valid/test segments
    segments = cfg["task"]["dataset"]["kwargs"]["segments"]
    # Validation window: proportional to training duration.
    # Short training windows get a smaller validation hold-out to preserve
    # training data. Minimum 3 months, maximum 6 months, ~20% of training.
    train_start_dt = datetime.strptime(train_start, "%Y-%m-%d")
    train_end_dt = datetime.strptime(train_end, "%Y-%m-%d")
    train_months = max(
        1, (train_end_dt.year - train_start_dt.year) * 12
        + (train_end_dt.month - train_start_dt.month)
    )
    val_months = max(3, min(6, int(train_months * 0.2)))
    val_start_dt = _add_months(train_end_dt, -val_months)

    # --- Apply label-horizon gap to prevent forward-label leakage ---
    if label_horizon > 0:
        cal = _get_trading_calendar(train_start, test_end)
        _validate_calendar(cal, train_start, test_end)
        if len(cal) <= label_horizon:
            raise RuntimeError(
                f"Trading calendar too short ({len(cal)} days) "
                f"for label_horizon={label_horizon}. "
                f"Ensure Qlib is initialized with a working calendar covering "
                f"{train_start} to {test_end}."
            )
        # Shift valid_end backward from test_start so validation labels
        # cannot peek into the test period.
        test_start_ts = pd.Timestamp(test_start)
        safe_valid_end = _safe_end_date(cal, test_start_ts, label_horizon)
        val_start_str = val_start_dt.strftime("%Y-%m-%d")
        if safe_valid_end > pd.Timestamp(val_start_str):
            train_end_dt = safe_valid_end.to_pydatetime()
        else:
            raise RuntimeError(
                f"Label horizon {label_horizon} shrinks valid window to zero "
                f"for split {split_id} (valid_start={val_start_str}, "
                f"safe_valid_end={safe_valid_end.date()}). "
                f"Reduce label_horizon or extend the training window."
            )
        # Shift train_end backward from val_start so training labels
        # cannot peek into the validation period.
        val_start_ts = pd.Timestamp(val_start_str)
        safe_train_end = _safe_end_date(cal, val_start_ts, label_horizon)
        train_start_ts = pd.Timestamp(train_start)
        if safe_train_end > train_start_ts:
            train_cutoff_dt = safe_train_end.to_pydatetime()
        else:
            raise RuntimeError(
                f"Label horizon {label_horizon} shrinks train window to zero "
                f"for split {split_id} (train_start={train_start}, "
                f"safe_train_end={safe_train_end.date()}). "
                f"Reduce label_horizon or extend the training window."
            )
    else:
        train_cutoff_dt = val_start_dt - timedelta(days=1)

    effective_train_end = train_cutoff_dt.strftime("%Y-%m-%d")
    segments["train"] = [train_start, effective_train_end]
    segments["valid"] = [val_start_dt.strftime("%Y-%m-%d"), train_end_dt.strftime("%Y-%m-%d")]
    segments["test"] = [test_start, test_end]

    log.info(
        "Running walk-forward split",
        split_id=split_id,
        train_end=effective_train_end,
        original_train_end=train_end,
        label_horizon=label_horizon,
        test_start=test_start,
        test_end=test_end,
    )

    dataset = init_instance_by_config(cfg["task"]["dataset"])
    model = init_instance_by_config(cfg["task"]["model"])

    # Native estimators need X/y DataFrames from DatasetH, not DatasetH itself.
    segments = cfg["task"]["dataset"]["kwargs"]["segments"]

    if _is_native_estimator_config(cfg):
        model, predictions = _fit_native_estimator(model, dataset, segments)
    else:
        model.fit(dataset)

        # Qlib model.predict(dataset) -- standard pattern.
        # fit() may mutate the dataset, so handle the case where
        # prepare() is no longer available.
        try:
            predictions = model.predict(dataset, segment="test")
        except (AttributeError, TypeError):
            predictions = model.predict(dataset)

    # IC evaluation uses RAW forward returns (no learn processors).
    # Training still uses processed labels inside the model.
    actuals = _load_raw_labels(cfg, test_start, test_end)

    # Align by (datetime, instrument) MultiIndex — never positional.
    try:
        pred_aligned, act_aligned = _align_multiindex(predictions, actuals)
    except (TypeError, ValueError) as e:
        log.warning(
            "Cannot align predictions and actuals by index",
            split_id=split_id,
            error=str(e),
        )
        return SplitResult(
            split_id=split_id,
            train_start=train_start,
            train_end=effective_train_end,
            test_start=test_start,
            test_end=test_end,
            ic=None,
            rank_ic=None,
            status="skipped",
            error_message=f"Index alignment failed: {e}",
        )
    pearson_ic, rank_ic = _compute_mean_daily_ic(
        pred_aligned, act_aligned
    )

    return SplitResult(
        split_id=split_id,
        train_start=train_start,
        train_end=effective_train_end,
        test_start=test_start,
        test_end=test_end,
        ic=pearson_ic,
        rank_ic=rank_ic,
        status="success",
    )


def walk_forward_validate(
    market: str = "us",
    model_type: str = "lgbm",
    train_start: str = "2021-01-01",
    train_end: str = None,
    test_window_months: int = 6,
    step_months: int = 3,
    config: dict | None = None,
    label_horizon: int = 10,
) -> WalkForwardResult:
    """Run expanding-window walk-forward validation.

    For each generated split the model is trained from scratch on the
    expanding training window and evaluated on the hold-out test window.
    Aggregate IC metrics are computed at the end.

    Args:
        market: ``"us"`` or ``"cn"``.
        model_type: Config suffix (``"lgbm"``, ``"xgb"``, etc.).
        train_start: Start of the first training window.
        config: Optional pre-compiled workflow config dict. When provided,
            used directly instead of loading the raw YAML from disk. This
            ensures walk-forward uses the same compiled features and
            settings as the main training pipeline (e.g. profile-compiled
            feature expressions instead of raw template placeholders).
        label_horizon: Trading days the label expression looks forward
            (default 10 for the standard ``Ref($close, -10) / Ref($close, -1) - 1``
            label).  Set to 0 to disable the gap.

    Note:
        Qlib must be initialized before calling this function. The caller
        is responsible for calling ``safe_qlib_init()`` or ``qlib.init()``
        with the correct ``provider_uri`` and ``region`` for the target
        market.

    Returns:
        WalkForwardResult with per-split and aggregated metrics.
    """
    from src.common.dates import default_train_end

    train_end = train_end or default_train_end()
    # Ensure Qlib is initialized
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    cfg = build_qlib_init_cfg(None, market=market)
    safe_qlib_init(cfg)

    from src.common.paths import CONFIG_DIR

    if config is not None:
        base_config = copy.deepcopy(config)
        log.info("walk_forward_using_passed_config", market=market)
    else:
        config_name = (
            f"{market}_workflow.yaml"
            if model_type == "linear"
            else f"{market}_{model_type}_workflow.yaml"
        )
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with open(config_path) as f:
            base_config = yaml.safe_load(f)
        log.info("walk_forward_loaded_config_from_disk", path=str(config_path))

    splits = generate_splits(
        train_start=train_start,
        train_end=train_end,
        test_window_months=test_window_months,
        step_months=step_months,
    )

    if not splits:
        log.warning("No valid walk-forward splits generated")
        result = WalkForwardResult(market=market, model_type=model_type)
        result.aggregate()
        return result

    log.info(
        "Starting walk-forward validation",
        market=market,
        model_type=model_type,
        n_splits=len(splits),
    )

    result = WalkForwardResult(market=market, model_type=model_type)

    for split_id, (ts, te, vs, ve) in enumerate(splits):
        try:
            sr = _run_single_split(
                base_config=base_config,
                split_id=split_id,
                train_start=ts,
                train_end=te,
                test_start=vs,
                test_end=ve,
                label_horizon=label_horizon,
            )
            result.splits.append(sr)
            log.info(
                "Split complete",
                split_id=split_id,
                ic=sr.ic,
                rank_ic=sr.rank_ic,
                status=sr.status,
            )
        except Exception as exc:
            log.exception("Split failed", split_id=split_id, error=str(exc))
            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=te,
                    test_start=vs,
                    test_end=ve,
                    ic=None,
                    rank_ic=None,
                    status="failed",
                    error_message=str(exc),
                )
            )

    result.aggregate()

    # Count successful vs failed splits
    n_success = sum(1 for s in result.splits if s.status == "success" and s.ic is not None)
    n_failed = sum(1 for s in result.splits if s.status == "failed")
    n_total = len(result.splits)

    # Fail closed when zero splits succeeded — no metrics to report.
    if n_total > 0 and n_success == 0:
        raise RuntimeError(
            f"Walk-forward produced {n_failed} failed splits and zero successful. "
            f"No valid metrics to aggregate. Check data coverage, label horizon, "
            f"and date ranges."
        )

    log.info(
        "Walk-forward validation complete",
        market=market,
        model_type=model_type,
        n_splits=n_total,
        n_success=n_success,
        n_failed=n_failed,
        mean_ic=result.mean_ic,
        std_ic=result.std_ic,
        ic_ir=result.ic_ir,
        consistency_score=result.consistency_score,
    )

    return result


# ---------------------------------------------------------------------------
# Vectorized walk-forward (fast path, ~3.5× faster)
# ---------------------------------------------------------------------------


def walk_forward_vectorized(
    market: str = "cn",
    train_start: str = "2021-01-01",
    train_end: str = None,
    test_window_months: int = 6,
    step_months: int = 3,
    n_estimators: int = 300,
    learning_rate: float = 0.03,
    label_horizon: int = 10,
    benchmark_symbol: str | None = None,
    training_objective: str = "regression",
    min_train_months: int = 12,
    feature_profile: str = "alpha158",
) -> WalkForwardResult:
    """Vectorized walk-forward — pre-loads features once, trains LightGBM directly.

    Avoids per-split ``DataHandlerLP`` initialization (~37s each) by loading
    Alpha158 features for the full period once, then slicing and normalizing
    per split.  ~3.5× faster than ``walk_forward_validate``.

    Args:
        label_horizon: Trading days the label expression looks forward
            (default 10 for the standard ``Ref($close, -10) / Ref($close, -1) - 1``
            label).  Set to 0 to disable the gap.
        benchmark_symbol: When provided, train on same-date benchmark excess
            returns instead of absolute returns.
        training_objective: ``"regression"`` (default) or ``"lambdarank"``.
        min_train_months: Minimum calendar months of actual training data
            provided to the selector/model per split (not just a nominal
            boundary).  After accounting for the validation hold-out and
            label-horizon purges, candidates whose ``safe_train_end`` falls
            before ``_add_months(train_start, min_train_months)`` are
            recorded as ``status='skipped'``.  Default 12.  Must be >= 1.
        feature_profile: ``"alpha158"`` (default) or the predeclared
            ``"curated_us_momentum"`` research profile.
    """
    import lightgbm as lgb
    from qlib.contrib.data.loader import Alpha158DL
    from qlib.data import D

    from src.common.dates import default_train_end
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    if min_train_months < 1:
        raise ValueError(
            f"min_train_months must be >= 1, got {min_train_months}"
        )
    if training_objective not in {"regression", "lambdarank"}:
        raise ValueError(
            "training_objective must be 'regression' or 'lambdarank'"
        )
    if feature_profile not in {"alpha158", "curated_us_momentum"}:
        raise ValueError(
            "feature_profile must be 'alpha158' or 'curated_us_momentum'"
        )

    train_end = train_end or default_train_end()
    safe_qlib_init(build_qlib_init_cfg(None, market=market))

    # --- Load symbols ---
    instr_path = Path("data/watchlist/instruments") / f"{market}.txt"
    symbols = [line.split("\t")[0] for line in instr_path.read_text().splitlines() if line.strip()]
    log.info("Vectorized WF: symbols", n=len(symbols))

    # --- Load all features + labels once ---
    if feature_profile == "curated_us_momentum":
        from src.research.cross_sectional_training import (
            CURATED_US_MOMENTUM_EXPRESSIONS,
        )

        all_exprs = list(CURATED_US_MOMENTUM_EXPRESSIONS)
    else:
        alpha_exprs = Alpha158DL.get_feature_config(
            {
                "kbar": {},
                "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
                "rolling": {},
            }
        )[0]
        extra_exprs = [
            "$close/Ref($close, 5)-1",
            "$close/Ref($close, 10)-1",
            "$close/Ref($close, 20)-1",
            "Std($close, 10)",
            "$volume/Ref($volume, 10)-1",
        ]
        all_exprs = list(alpha_exprs) + extra_exprs
    label_expr = [_forward_return_expression(label_horizon)]

    full_end = _add_months(datetime.strptime(train_end, "%Y-%m-%d"), test_window_months).strftime(
        "%Y-%m-%d"
    )

    log.info("Vectorized WF: loading", n_features=len(all_exprs))
    X_all = D.features(symbols, all_exprs, start_time=train_start, end_time=full_end)
    y_all = D.features(symbols, label_expr, start_time=train_start, end_time=full_end)
    X_all = _normalize_qlib_index(X_all)
    y_all = _normalize_qlib_index(y_all)
    X_all = X_all.fillna(0.0)
    y_series = y_all.iloc[:, 0]
    if benchmark_symbol:
        benchmark_data = D.features(
            [benchmark_symbol],
            label_expr,
            start_time=train_start,
            end_time=full_end,
        )
        if isinstance(benchmark_data.index, pd.MultiIndex):
            benchmark_data = benchmark_data.xs(benchmark_symbol, level="instrument")
        benchmark_returns = benchmark_data.iloc[:, 0]
        y_series = _subtract_benchmark_by_date(y_series, benchmark_returns)
    log.info("Vectorized WF: loaded", X_shape=X_all.shape)

    # Sanitize column names
    def _s(c):
        return (
            str(c)
            .replace("$", "D")
            .replace("/", "_d_")
            .replace("(", "L")
            .replace(")", "R")
            .replace(",", "_")
            .replace(" ", "_")
            .replace("-", "neg")
            .replace("+", "plus")
        )

    X_all.columns = [_s(c) for c in X_all.columns]

    # --- Generate splits ---
    splits = generate_splits(
        train_start=train_start,
        train_end=train_end,
        test_window_months=test_window_months,
        step_months=step_months,
        min_train_months=min_train_months,
    )
    if not splits:
        log.warning("Vectorized WF: no splits")
        r = WalkForwardResult(market=market, model_type="lgbm_vectorized")
        r.aggregate()
        return r

    log.info(
        "Vectorized WF: starting",
        n_splits=len(splits),
        min_train_months=min_train_months,
        training_protocol=(
            f"minimum {min_train_months} months of training "
            f"history before first evaluation"
        ),
    )
    result = WalkForwardResult(market=market, model_type="lgbm_vectorized")

    from src.research.cross_sectional_training import (
        compute_relevance_labels,
        make_daily_cs_ic_eval,
        monotone_constraints_from_selection,
        select_stable_features,
    )

    wf_params = {
        "objective": training_objective,
        "metric": "None",  # disable default L2; daily CS IC comes from feval
        "learning_rate": learning_rate,
        "max_depth": 3 if feature_profile == "curated_us_momentum" else 4,
        "num_leaves": 7 if feature_profile == "curated_us_momentum" else 15,
        "feature_fraction": 1.0,
        "bagging_fraction": 1.0,
        "lambda_l1": 1.0,
        "lambda_l2": 10.0,
        "num_threads": 20,
        "verbosity": -1,
        "min_data_in_leaf": 100,
        "seed": 42,
        "feature_fraction_seed": 42,
        "bagging_seed": 42,
        "data_random_seed": 42,
        "drop_seed": 42,
        "deterministic": True,
        "force_col_wise": True,
    }

    # Pre-compute the trading calendar once for label-horizon shifts
    if label_horizon > 0:
        vec_cal = _get_trading_calendar(train_start, full_end)
        _validate_calendar(vec_cal, train_start, full_end)
        if len(vec_cal) <= label_horizon:
            raise RuntimeError(
                f"Trading calendar too short ({len(vec_cal)} days) "
                f"for label_horizon={label_horizon}. "
                f"Ensure Qlib is initialized with a working calendar covering "
                f"{train_start} to {full_end}."
            )
    else:
        vec_cal = pd.DatetimeIndex([])

    dates_all = X_all.index.get_level_values("datetime")

    for split_id, (ts, te, vs, ve) in enumerate(splits):
        safe_train_end = te  # fallback for exception handler
        # --- Compute safe endpoints for train→valid→test boundaries ---
        if label_horizon > 0:
            # Train→test purge anchor: last train date whose label can't peek into test.
            safe_te_ts = _safe_end_date(vec_cal, pd.Timestamp(vs), label_horizon)
            if safe_te_ts <= pd.Timestamp(ts):
                raise RuntimeError(
                    f"Label horizon {label_horizon} shrinks train window to zero "
                    f"for split {split_id} (train_start={ts}, "
                    f"safe_train_end={safe_te_ts.date()})."
                )

            # Build validation from tail of expanding train (3–6 months, ~20%).
            train_start_dt = datetime.strptime(ts, "%Y-%m-%d")
            safe_te_dt = safe_te_ts.to_pydatetime()
            train_months = max(
                1,
                (safe_te_dt.year - train_start_dt.year) * 12
                + (safe_te_dt.month - train_start_dt.month),
            )
            val_months = max(3, min(6, int(train_months * 0.2)))
            val_start_dt = _add_months(safe_te_dt, -val_months)
            val_start_str = val_start_dt.strftime("%Y-%m-%d")
            val_start_ts = pd.Timestamp(val_start_str)

            # Train→valid purge: last train date whose label can't peek into valid.
            safe_train_end_ts = _safe_end_date(vec_cal, val_start_ts, label_horizon)
            if safe_train_end_ts <= pd.Timestamp(ts):
                raise RuntimeError(
                    f"Label horizon {label_horizon} shrinks train window to zero "
                    f"for split {split_id} (train_start={ts}, "
                    f"safe_train_end={safe_train_end_ts.date()})."
                )
            safe_train_end = safe_train_end_ts.strftime("%Y-%m-%d")

            # Valid→test purge: last valid date whose label can't peek into test.
            safe_valid_end_ts = _safe_end_date(vec_cal, pd.Timestamp(vs), label_horizon)
            if safe_valid_end_ts <= val_start_ts:
                raise RuntimeError(
                    f"Label horizon {label_horizon} shrinks valid window to zero "
                    f"for split {split_id} (valid_start={val_start_str}, "
                    f"safe_valid_end={safe_valid_end_ts.date()})."
                )
            safe_valid_end = safe_valid_end_ts.strftime("%Y-%m-%d")
        else:
            # No label-horizon: simple proportional validation window.
            safe_te = te
            train_start_dt = datetime.strptime(ts, "%Y-%m-%d")
            train_end_dt = datetime.strptime(safe_te, "%Y-%m-%d")
            train_months = max(
                1,
                (train_end_dt.year - train_start_dt.year) * 12
                + (train_end_dt.month - train_start_dt.month),
            )
            val_months = max(3, min(6, int(train_months * 0.2)))
            val_start_dt = _add_months(train_end_dt, -val_months)
            val_start_str = val_start_dt.strftime("%Y-%m-%d")
            safe_train_end = (
                val_start_dt - timedelta(days=1)
            ).strftime("%Y-%m-%d")
            safe_valid_end = min(
                pd.Timestamp(safe_te), pd.Timestamp(vs) - timedelta(days=1)
            ).strftime("%Y-%m-%d")

        # --- Enforce actual training data minimum ---
        # The safe_train_end above accounts for validation hold-out and
        # label-horizon purges.  Compare it against the calendar threshold
        # rather than the nominal train_end from generate_splits.
        min_actual_dt = _add_months(
            datetime.strptime(ts, "%Y-%m-%d"), min_train_months
        )
        if pd.Timestamp(safe_train_end) < pd.Timestamp(min_actual_dt):
            log.info(
                "Vectorized WF split skipped: insufficient actual training",
                split_id=split_id,
                safe_train_end=safe_train_end,
                min_required=str(min_actual_dt.date()),
                test_start=vs,
            )
            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=safe_train_end,
                    test_start=vs,
                    test_end=ve,
                    ic=None,
                    rank_ic=None,
                    status="skipped",
                    error_message=(
                        f"Actual training end {safe_train_end} before "
                        f"min_train_months={min_train_months} threshold "
                        f"{min_actual_dt.date()}. The label-horizon purge "
                        f"and validation hold-out reduce the effective "
                        f"training window below the configured minimum."
                    ),
                )
            )
            continue

        try:
            # Slice train, valid, test separately — NEVER pool or overlap.
            train_mask = (dates_all >= ts) & (dates_all <= safe_train_end)
            valid_mask = (dates_all >= val_start_str) & (dates_all <= safe_valid_end)
            test_mask = (dates_all >= vs) & (dates_all <= ve)

            X_tr = X_all[train_mask].copy()
            y_tr = y_series[train_mask].copy()
            X_va = X_all[valid_mask].copy()
            y_va = y_series[valid_mask].copy()
            X_te = X_all[test_mask].copy()
            y_te = y_series[test_mask].copy()

            # Align features and labels by MultiIndex labels — never positional.
            X_tr, y_tr = _align_multiindex(X_tr, y_tr)  # type: ignore[assignment]
            X_va, y_va = _align_multiindex(X_va, y_va)  # type: ignore[assignment]
            X_te, y_te = _align_multiindex(X_te, y_te)  # type: ignore[assignment]

            if len(X_tr) < 100 or len(X_va) < 50 or len(X_te) < 50:
                result.splits.append(
                    SplitResult(
                        split_id=split_id,
                        train_start=ts,
                        train_end=safe_train_end,
                        test_start=vs,
                        test_end=ve,
                        ic=None,
                        rank_ic=None,
                        status="skipped",
                        error_message="Insufficient data after alignment",
                    )
                )
                continue

            # Select stable features using train+valid ONLY (selector NEVER sees test).
            selection = select_stable_features(
                X_tr, y_tr, X_va, y_va, max_features=10
            )
            if len(selection) == 0:
                result.splits.append(
                    SplitResult(
                        split_id=split_id,
                        train_start=ts,
                        train_end=safe_train_end,
                        test_start=vs,
                        test_end=ve,
                        ic=None,
                        rank_ic=None,
                        status="skipped",
                        error_message="No stable features selected",
                    )
                )
                continue
            selected = selection.index.tolist()
            use_monotone_constraints = feature_profile != "curated_us_momentum"
            monotone_constraints = (
                monotone_constraints_from_selection(selection)
                if use_monotone_constraints
                else None
            )

            # Subset to selected features.
            X_tr = X_tr[selected].copy()
            X_va = X_va[selected].copy()
            X_te = X_te[selected].copy()

            # Z-score fit on train only (on selected columns).
            mu = X_tr.mean()
            sd = X_tr.std().replace(0, 1.0)
            X_tr[:] = (X_tr - mu) / sd
            X_va[:] = (X_va - mu) / sd
            X_te[:] = (X_te - mu) / sd

            # Train based on objective.
            is_rank = training_objective == "lambdarank"
            if is_rank:
                train_mask = np.isfinite(y_tr.to_numpy(dtype=float))
                valid_mask = np.isfinite(y_va.to_numpy(dtype=float))
                rank_X_tr, rank_y_tr = X_tr.loc[train_mask], y_tr.loc[train_mask]
                rank_X_va, rank_y_va = X_va.loc[valid_mask], y_va.loc[valid_mask]
                train_labels, train_groups = compute_relevance_labels(rank_y_tr, n_bins=5)
                valid_labels, valid_groups = compute_relevance_labels(rank_y_va, n_bins=5)
                train_data = lgb.Dataset(rank_X_tr, label=train_labels, group=train_groups)
                valid_data = lgb.Dataset(
                    rank_X_va,
                    label=valid_labels,
                    reference=train_data,
                    group=valid_groups,
                )
                feval = make_daily_cs_ic_eval(
                    rank_X_va.index, continuous_labels=rank_y_va
                )
            else:
                train_data = lgb.Dataset(X_tr, label=y_tr)
                valid_data = lgb.Dataset(X_va, label=y_va, reference=train_data)
                feval = make_daily_cs_ic_eval(X_va.index)

            split_params = dict(wf_params)
            if monotone_constraints is not None:
                split_params.update(
                    monotone_constraints=monotone_constraints,
                    monotone_constraints_method="advanced",
                )
            booster = lgb.train(
                split_params,
                train_data,
                num_boost_round=n_estimators,
                valid_sets=[valid_data],
                feval=feval,
                callbacks=[lgb.early_stopping(50, first_metric_only=True)],
            )

            # Predict on test + index-aligned mean daily IC.
            y_pred_arr = booster.predict(X_te)
            y_pred = pd.Series(y_pred_arr, index=X_te.index, name="prediction")
            pred_aligned, act_aligned = _align_multiindex(y_pred, y_te)
            pearson_ic, rank_ic = _compute_mean_daily_ic(
                pred_aligned.values, act_aligned
            )

            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=safe_train_end,
                    test_start=vs,
                    test_end=ve,
                    ic=pearson_ic,
                    rank_ic=rank_ic,
                    status="success",
                )
            )
            log.info(
                "Vectorized WF split",
                split_id=split_id,
                effective_train_end=safe_train_end,
                valid_start=val_start_str,
                valid_end=safe_valid_end,
                n_selected=len(selected),
                monotone_constraints=monotone_constraints,
                best_iter=booster.best_iteration,
                ic=round(pearson_ic, 4) if pearson_ic else None,
            )

        except Exception as exc:
            log.exception("Vectorized WF split failed", split_id=split_id, error=str(exc))
            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=safe_train_end,
                    test_start=vs,
                    test_end=ve,
                    ic=None,
                    rank_ic=None,
                    status="failed",
                    error_message=str(exc),
                )
            )

    result.aggregate()
    n_ok = sum(1 for s in result.splits if s.status == "success" and s.ic is not None)
    log.info(
        "Vectorized WF done",
        market=market,
        n_splits=len(splits),
        n_ok=n_ok,
        mean_ic=result.mean_ic,
        ic_ir=result.ic_ir,
        consistency=result.consistency_score,
        min_train_months=min_train_months,
        feature_profile=feature_profile,
    )
    return result
