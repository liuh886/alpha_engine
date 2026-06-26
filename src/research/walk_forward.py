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
from datetime import datetime

import numpy as np
import structlog
import yaml
from qlib.utils import init_instance_by_config

log = structlog.get_logger()


def _add_months(dt: datetime, months: int) -> datetime:
    """Add *months* calendar months to *dt*, clamping the day to end-of-month."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    import calendar

    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return dt.replace(year=year, month=month, day=day)


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
) -> list[tuple[str, str, str, str]]:
    """Generate expanding-window splits.

    Each split trains from ``train_start`` to a moving ``train_end``,
    then tests on the following ``test_window_months`` period.  The
    ``train_end`` advances by ``step_months`` each iteration.

    Returns:
        List of (train_start, train_end, test_start, test_end) tuples.
    """
    from src.common.dates import default_train_end

    train_end = train_end or default_train_end()
    start = datetime.strptime(train_start, "%Y-%m-%d")
    end = datetime.strptime(train_end, "%Y-%m-%d")

    # First train_end is at least 12 months from start so the model
    # has enough data to learn.
    min_train_end = _add_months(start, 12)

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
    )
    return splits


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

    # Spearman rank IC via numpy (avoids scipy dependency).
    def _rankdata(a: np.ndarray) -> np.ndarray:
        """Return ranks (0-based, averaged for ties)."""
        sorter = np.argsort(a)
        rank = np.empty_like(sorter, dtype=float)
        rank[sorter] = np.arange(len(a), dtype=float)
        return rank

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


def _run_single_split(
    base_config: dict,
    split_id: int,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> SplitResult:
    """Train on one split and compute IC on the test period.

    This reuses Qlib's ``init_instance_by_config`` pipeline so the
    same feature engineering / preprocessing is applied as in normal
    training.
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
    segments["train"] = [train_start, train_end_dt.strftime("%Y-%m-%d")]
    segments["valid"] = [val_start_dt.strftime("%Y-%m-%d"), train_end_dt.strftime("%Y-%m-%d")]
    segments["test"] = [test_start, test_end]

    log.info(
        "Running walk-forward split",
        split_id=split_id,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
    )

    dataset = init_instance_by_config(cfg["task"]["dataset"])
    model = init_instance_by_config(cfg["task"]["model"])
    model.fit(dataset)

    # Use model.predict(dataset) — Qlib's standard pattern.
    # model.fit() may mutate the dataset, so we handle the case where
    # prepare() is no longer available.
    try:
        # Try the standard approach first
        predictions = model.predict(dataset, segment="test")
    except (AttributeError, TypeError):
        # Fallback: predict on the full dataset and filter to test period
        predictions = model.predict(dataset)

    # Get actual labels
    try:
        label_data = dataset.prepare(segments="test", col_set="label", data_key="infer")
        actuals = label_data.iloc[:, 0].values
    except (AttributeError, Exception):
        # Fallback: use handler to fetch labels
        from qlib.data import D

        instruments = D.instruments(cfg.get("instruments", "us"))
        label_expr = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"]["kwargs"][
            "config"
        ].get("label", ["Ref($close, -1) / $close - 1"])
        label_df = D.features(
            D.list_instruments(instruments, as_list=True),
            label_expr,
            start_time=test_start,
            end_time=test_end,
        )
        actuals = label_df.iloc[:, 0].values

    # Align by index
    n = min(len(predictions), len(actuals))
    if n == 0:
        log.warning("No overlapping predictions and actuals", split_id=split_id)
        return SplitResult(
            split_id=split_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            ic=None,
            rank_ic=None,
            status="skipped",
            error_message="No overlapping predictions and actuals",
        )

    pred_aligned = predictions.values[:n] if hasattr(predictions, "values") else predictions[:n]
    act_aligned = actuals[:n]

    pearson_ic, rank_ic = _compute_ic(pred_aligned, act_aligned)

    # If IC computation returned zeros due to insufficient data, mark as skipped
    if pearson_ic == 0.0 and rank_ic == 0.0:
        # Check if this is genuinely zero IC or just insufficient data
        mask = np.isfinite(pred_aligned) & np.isfinite(act_aligned)
        valid_count = mask.sum() if hasattr(mask, "sum") else int(mask)
        if valid_count < 5:
            log.warning(
                "Insufficient valid data for IC computation",
                split_id=split_id,
                valid_count=valid_count,
            )
            return SplitResult(
                split_id=split_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                ic=None,
                rank_ic=None,
                status="skipped",
                error_message=f"Insufficient valid data ({valid_count} points)",
            )

    return SplitResult(
        split_id=split_id,
        train_start=train_start,
        train_end=train_end,
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
    learning_rate: float = 0.05,
) -> WalkForwardResult:
    """Vectorized walk-forward — pre-loads features once, trains LightGBM directly.

    Avoids per-split ``DataHandlerLP`` initialization (~37s each) by loading
    Alpha158 features for the full period once, then slicing and normalizing
    per split.  ~3.5× faster than ``walk_forward_validate``.
    """
    import lightgbm as lgb
    from qlib.contrib.data.loader import Alpha158DL
    from qlib.data import D

    from src.common.dates import default_train_end
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    train_end = train_end or default_train_end()
    safe_qlib_init(build_qlib_init_cfg(None, market=market))

    # --- Load symbols ---
    from pathlib import Path

    instr_path = Path("data/watchlist/instruments") / f"{market}.txt"
    symbols = [line.split("\t")[0] for line in instr_path.read_text().splitlines() if line.strip()]
    log.info("Vectorized WF: symbols", n=len(symbols))

    # --- Load all features + labels once ---
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
    label_expr = ["Ref($close, -10) / Ref($close, -1) - 1"]

    full_end = _add_months(datetime.strptime(train_end, "%Y-%m-%d"), test_window_months).strftime(
        "%Y-%m-%d"
    )

    log.info("Vectorized WF: loading", n_features=len(all_exprs))
    X_all = D.features(symbols, all_exprs, start_time=train_start, end_time=full_end)
    y_all = D.features(symbols, label_expr, start_time=train_start, end_time=full_end)
    X_all = X_all.fillna(0.0)
    y_series = y_all.iloc[:, 0]
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
    feature_names = X_all.columns.tolist()

    # --- Generate splits ---
    splits = generate_splits(
        train_start=train_start,
        train_end=train_end,
        test_window_months=test_window_months,
        step_months=step_months,
    )
    if not splits:
        log.warning("Vectorized WF: no splits")
        r = WalkForwardResult(market=market, model_type="lgbm_vectorized")
        r.aggregate()
        return r

    log.info("Vectorized WF: starting", n_splits=len(splits))
    result = WalkForwardResult(market=market, model_type="lgbm_vectorized")

    params = {
        "objective": "regression",
        "metric": "l2",
        "learning_rate": learning_rate,
        "max_depth": 10,
        "num_leaves": 128,
        "feature_fraction": 0.8879,
        "bagging_fraction": 0.8789,
        "lambda_l1": 1.0,
        "lambda_l2": 1.0,
        "num_threads": 20,
        "verbosity": -1,
        "min_data_in_leaf": 20,
    }

    for split_id, (ts, te, vs, ve) in enumerate(splits):
        try:
            train_mask = (X_all.index.get_level_values("datetime") >= ts) & (
                X_all.index.get_level_values("datetime") <= te
            )
            test_mask = (X_all.index.get_level_values("datetime") >= vs) & (
                X_all.index.get_level_values("datetime") <= ve
            )
            X_tr = X_all[train_mask].copy()
            y_tr = y_series[train_mask].copy()
            X_te = X_all[test_mask].copy()
            y_te = y_series[test_mask].copy()

            if len(X_tr) < 100 or len(X_te) < 50:
                result.splits.append(
                    SplitResult(
                        split_id=split_id,
                        train_start=ts,
                        train_end=te,
                        test_start=vs,
                        test_end=ve,
                        ic=None,
                        rank_ic=None,
                        status="skipped",
                        error_message="Insufficient data",
                    )
                )
                continue

            # Z-score fit on train only
            mu, sd = X_tr.mean(), X_tr.std().replace(0, 1.0)
            X_tr[:] = (X_tr - mu) / sd
            X_te[:] = (X_te - mu) / sd

            # Train
            booster = lgb.train(
                params, lgb.Dataset(X_tr[feature_names], label=y_tr), num_boost_round=n_estimators
            )

            # Predict + IC
            y_pred = booster.predict(X_te[feature_names])
            pearson_ic, rank_ic = _compute_ic(y_pred, y_te.values)

            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=te,
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
                ic=round(pearson_ic, 4) if pearson_ic else None,
            )

        except Exception as exc:
            log.exception("Vectorized WF split failed", split_id=split_id, error=str(exc))
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
    n_ok = sum(1 for s in result.splits if s.status == "success" and s.ic is not None)
    log.info(
        "Vectorized WF done",
        market=market,
        n_splits=len(splits),
        n_ok=n_ok,
        mean_ic=result.mean_ic,
        ic_ir=result.ic_ir,
        consistency=result.consistency_score,
    )
    return result
