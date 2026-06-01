"""Walk-forward validation for expanding-window model evaluation."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import yaml
from qlib.utils import init_instance_by_config

import structlog

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
    ic: float  # Pearson IC
    rank_ic: float  # Spearman rank IC
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

    def aggregate(self) -> None:
        """Compute summary statistics from split IC values."""
        if not self.splits:
            return
        ics = [s.ic for s in self.splits]
        self.mean_ic = float(np.mean(ics))
        self.std_ic = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0.0
        self.ic_ir = (
            self.mean_ic / self.std_ic if self.std_ic > 1e-12 else 0.0
        )
        self.consistency_score = float(np.mean([1.0 if ic > 0 else 0.0 for ic in ics]))


def generate_splits(
    train_start: str = "2021-01-01",
    train_end: str = "2026-04-03",
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

        splits.append((
            train_start,
            current_end.strftime("%Y-%m-%d"),
            test_start_dt.strftime("%Y-%m-%d"),
            actual_test_end.strftime("%Y-%m-%d"),
        ))

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


def _compute_ic(
    predictions: np.ndarray, actuals: np.ndarray
) -> tuple[float, float]:
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
    # Validation is the last 6 months of training period.
    train_end_dt = datetime.strptime(train_end, "%Y-%m-%d")
    val_start_dt = _add_months(train_end_dt, -6)
    segments["train"] = [train_start, val_start_dt.strftime("%Y-%m-%d")]
    segments["valid"] = [val_start_dt.strftime("%Y-%m-%d"), train_end]
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

    # Predict on test segment
    test_dataset = dataset.prepare(
        segments="test", col_set="feature", data_key="infer"
    )
    predictions = model.predict(test_dataset)

    # Get actual labels for test period
    label_dataset = dataset.prepare(
        segments="test", col_set="label", data_key="infer"
    )
    actuals = label_dataset.iloc[:, 0].values

    # Align by index (predictions may have fewer rows due to NaN filtering)
    common_idx = predictions.index.intersection(actuals.index)
    pred_aligned = predictions.loc[common_idx].values
    act_aligned = actuals.loc[common_idx].values

    pearson_ic, rank_ic = _compute_ic(pred_aligned, act_aligned)

    return SplitResult(
        split_id=split_id,
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
        ic=pearson_ic,
        rank_ic=rank_ic,
    )


def walk_forward_validate(
    market: str = "us",
    model_type: str = "lgbm",
    train_start: str = "2021-01-01",
    train_end: str = "2026-04-03",
    test_window_months: int = 6,
    step_months: int = 3,
) -> WalkForwardResult:
    """Run expanding-window walk-forward validation.

    For each generated split the model is trained from scratch on the
    expanding training window and evaluated on the hold-out test window.
    Aggregate IC metrics are computed at the end.

    Args:
        market: ``"us"`` or ``"cn"``.
        model_type: Config suffix (``"lgbm"``, ``"xgb"``, etc.).
        train_start: Start of the first training window.
        train_end: End of the overall range.
        test_window_months: Length of each test window in months.
        step_months: How far to slide forward between splits.

    Returns:
        WalkForwardResult with per-split and aggregated metrics.
    """
    from src.common.paths import CONFIG_DIR

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
            )
        except Exception:
            log.exception("Split failed", split_id=split_id)
            result.splits.append(
                SplitResult(
                    split_id=split_id,
                    train_start=ts,
                    train_end=te,
                    test_start=vs,
                    test_end=ve,
                    ic=0.0,
                    rank_ic=0.0,
                )
            )

    result.aggregate()

    log.info(
        "Walk-forward validation complete",
        market=market,
        model_type=model_type,
        mean_ic=result.mean_ic,
        std_ic=result.std_ic,
        ic_ir=result.ic_ir,
        consistency_score=result.consistency_score,
    )

    return result
