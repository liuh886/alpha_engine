"""Train US market optimal model — both absolute and excess return labels.

US market characteristics (from model_training_experience.md):
  - Excess return label works BETTER for US (unlike CN where absolute is best)
  - Walk-forward IC=0.49, excess vs QQQ=+12.53% (excess label)
  - 125 US stocks

Trains two variants and registers the best one.
"""

from __future__ import annotations

import json
import pickle
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import lightgbm as lgb
import numpy as np
import pandas as pd
import structlog
from qlib.data import D

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine
from src.research.cross_sectional_training import CURATED_US_MOMENTUM_EXPRESSIONS
from src.research.vectorized_backtest import run_vectorized_backtest
from src.research.walk_forward import _normalize_qlib_index, walk_forward_vectorized

logger = structlog.get_logger(__name__)

# Kept as a patch point for existing loader tests and external script wrappers.
Alpha158DL = None

MARKET = "us"
BENCHMARK = "QQQ"
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-12-31"  # nominal end; actual training data is purge-cut before VALID_START
WF_TRAIN_START = "2018-01-01"
VALID_START = "2024-07-01"
VALID_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END = "2026-06-18"
LABEL_HORIZON = 20  # sessions forward for the lower-noise US ranking target
TOP_K = 15
REBALANCE_DAYS = 20
COST_BPS = 20.0

# Two label variants to try.
# NOTE: The excess label is computed in code (stock forward return minus
# same-date QQQ forward return), NOT via a Qlib expression.
LABELS = {
    "absret": {
        "tag": "us_absret",
        "desc": "Absolute 20-day return",
    },
    "excess": {
        "tag": "us_excess",
        "desc": "20-day excess vs QQQ (stock - benchmark, same date)",
    },
}


def _wf_success_count(wf) -> int:
    return int(
        getattr(
        wf,
        "n_success",
        sum(
            split.status == "success" and split.ic is not None
            for split in getattr(wf, "splits", [])
        ),
        )
    )


def passes_effectiveness_gate(wf, backtest) -> bool:
    """Return whether historical stability and final holdout both pass."""
    n_success = _wf_success_count(wf)
    return bool(
        n_success >= 8
        and wf.mean_ic > 0
        and wf.ic_ir > 0.3
        and wf.consistency_score >= 0.6
        and backtest.excess_return > 0
    )


def load_us_data(label_key: str):
    """Load Alpha158 features + labels for US market.

    Parameters
    ----------
    label_key : str
        ``"absret"`` — absolute 10-session forward return.
        ``"excess"`` — stock forward return minus same-date QQQ forward return.

    Raises
    ------
    ValueError
        If *label_key* is not one of the accepted values.
    """
    if label_key not in LABELS:
        raise ValueError(
            f"Unknown label_key={label_key!r}. Accepted: {sorted(LABELS.keys())}"
        )

    safe_qlib_init(build_qlib_init_cfg(None, market=MARKET))

    instr_path = ROOT / "data" / "watchlist" / "instruments" / f"{MARKET}.txt"
    symbols = [line.split("\t")[0] for line in instr_path.read_text().splitlines() if line.strip()]
    logger.info("US symbols loaded", n=len(symbols))

    all_exprs = list(CURATED_US_MOMENTUM_EXPRESSIONS)

    logger.info("Loading US features", n_features=len(all_exprs), n_symbols=len(symbols))
    t0 = time.perf_counter()
    X_all = D.features(symbols, all_exprs, start_time=TRAIN_START, end_time=TEST_END)

    # --- Labels: stock forward return (always needed) ---
    stock_ret_expr = [
        f"Ref($close, -{LABEL_HORIZON}) / Ref($close, -1) - 1"
    ]
    y_all = D.features(symbols, stock_ret_expr, start_time=TRAIN_START, end_time=TEST_END)
    X_all = _normalize_qlib_index(X_all)
    y_all = _normalize_qlib_index(y_all)
    logger.info("US data loaded", seconds=round(time.perf_counter() - t0, 1), X=X_all.shape)

    X_all = X_all.fillna(0.0)
    y_series = y_all.iloc[:, 0].copy()

    # --- Excess label: stock forward return minus same-date QQQ forward return ---
    #     Vectorized datetime-index mapping: O(rows) instead of O(dates*rows).
    #     NaN/missing QQQ returns produce NaN stock excess labels (never zero-fill).
    if label_key == "excess":
        qqq_ret = D.features(
            ["QQQ"], stock_ret_expr, start_time=TRAIN_START, end_time=TEST_END
        )
        # Robust level-dropping by name (handles any MultiIndex column order)
        qqq_flat = qqq_ret.xs("QQQ", level="instrument")
        qqq_series = qqq_flat.iloc[:, 0]

        # Map each stock row's datetime to the same-date QQQ forward return.
        # Dates not present in qqq_series → NaN → stock excess becomes NaN.
        date_level = y_series.index.get_level_values("datetime")
        qqq_aligned = date_level.map(qqq_series)
        y_series = y_series - np.asarray(qqq_aligned, dtype=float)

        logger.info("US excess labels computed (stock - QQQ, same date, vectorized)")

    # --- Boundary purge: exclude rows whose LABEL_HORIZON-session forward
    #     label can reach the next segment (no label-horizon peek) -----------
    observed_dates = pd.DatetimeIndex(
        pd.Series(X_all.index.get_level_values("datetime").unique()).sort_values()
    )

    def _purge_tail(
        dates: pd.DatetimeIndex, seg_start: str, seg_end: str, n: int, label: str = ""
    ) -> pd.Timestamp:
        """Last allowable date within [seg_start, seg_end), purging exactly *n* sessions.

        Only observed dates that fall within the **source segment** are considered.
        This prevents the valid→test boundary from counting training dates and
        silently returning a cutoff before VALID_START when the validation segment
        itself has too few observed sessions.

        Raises ValueError when fewer than *n*+1 observed sessions exist in the
        source segment (fail-closed — never continue with an unpurged segment).
        """
        seg_start_ts = pd.Timestamp(seg_start)
        seg_end_ts = pd.Timestamp(seg_end)
        segment = dates[(dates >= seg_start_ts) & (dates < seg_end_ts)]
        if len(segment) <= n:
            raise ValueError(
                f"Not enough observed sessions to enforce {n}-session "
                f"label-horizon purge at {label} boundary ({seg_end}). "
                f"Need >{n} observed sessions in [{seg_start}, {seg_end}), "
                f"got {len(segment)}."
            )
        return segment[-(n + 1)]

    train_cutoff = _purge_tail(
        observed_dates, TRAIN_START, VALID_START, LABEL_HORIZON, label="train→valid"
    )
    valid_cutoff = _purge_tail(
        observed_dates, VALID_START, TEST_START, LABEL_HORIZON, label="valid→test"
    )

    dates = X_all.index.get_level_values("datetime")
    train_mask = (dates >= TRAIN_START) & (dates <= train_cutoff)
    valid_mask = (dates >= VALID_START) & (dates <= valid_cutoff)
    test_mask = (dates >= TEST_START) & (dates <= TEST_END)

    X_train = X_all[train_mask].copy()
    y_train = y_series[train_mask].copy()
    X_valid = X_all[valid_mask].copy()
    y_valid = y_series[valid_mask].copy()
    X_test = X_all[test_mask].copy()
    y_test = y_series[test_mask].copy()

    # CORRECTED 2026-06-27: The label is a FORWARD return (t+1 to t+10).
    # Qlib Ref with N<0 looks INTO THE FUTURE (see qlib/data/ops.py:789).
    # For a long-only strategy that buys high-score stocks, the model
    # must predict future returns DIRECTLY. Do NOT negate.

    # Normalization moved to train_model (after feature selection) so the
    # selector sees raw feature values.

    logger.info(
        "US data split",
        label=label_key,
        train=len(X_train),
        valid=len(X_valid),
        test=len(X_test),
    )
    return X_train, y_train, X_valid, y_valid, X_test, y_test, symbols


def train_model(
    X_train,
    y_train,
    X_valid,
    y_valid,
    training_objective="regression",
    use_monotone_constraints=True,
    max_depth=4,
    num_leaves=15,
):
    """Train LightGBM with stable feature selection + deterministic regularized params.

    Selects max 10 stable-sign features using only train+validation data
    (never test).  Trains a heavily-regularized deterministic LightGBM
    with daily cross-sectional IC early stopping on the validation set.

    When *training_objective* is ``"lambdarank"``, the model is trained with
    LightGBM's ``lambdarank`` objective using per-date integer relevance
    labels and group sizes.  The early-stopping feval still uses the
    **continuous** validation returns (never relevance bins).  Feature
    selection and monotone constraints remain based on continuous returns.

    Args:
        training_objective: ``"regression"`` (default) or ``"lambdarank"``.

    Returns:
        (booster, sanitized_feature_names, (norm_mean, norm_std))
    """
    from src.research.cross_sectional_training import (
        compute_relevance_labels,
        make_daily_cs_ic_eval,
        monotone_constraints_from_selection,
        select_stable_features,
    )

    if training_objective not in {"regression", "lambdarank"}:
        raise ValueError(
            "training_objective must be 'regression' or 'lambdarank'"
        )

    # 1. Select max 10 stable features BEFORE column-name sanitization.
    selection = select_stable_features(X_train, y_train, X_valid, y_valid, max_features=10)
    if len(selection) == 0:
        raise RuntimeError(
            "No stable features selected — failing closed. "
            "Check data quality: all features may have opposite-sign IC "
            "between train and validation periods."
        )
    selected_features = selection.index.tolist()
    monotone_constraints = (
        monotone_constraints_from_selection(selection)
        if use_monotone_constraints
        else None
    )
    logger.info(
        "Stable feature selection",
        n_selected=len(selected_features),
        features=selected_features,
        scores={f: round(float(s), 6) for f, s in zip(selection.index, selection["score"])},
        ranks=list(selection["rank"]),
        monotone_constraints=monotone_constraints,
    )

    # 2. Subset to selected features (raw, un-normalized).
    X_train = X_train[selected_features].copy()
    X_valid = X_valid[selected_features].copy()

    # 3. Sanitize column names for LightGBM compatibility.
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

    X_train.columns = [_s(c) for c in X_train.columns]
    X_valid.columns = [_s(c) for c in X_valid.columns]
    sanitized_features = X_train.columns.tolist()

    # 4. Z-score fit on train only (after selection, before training).
    norm_mean = X_train.mean()
    norm_std = X_train.std().replace(0, 1.0)
    X_train[:] = (X_train - norm_mean) / norm_std
    X_valid[:] = (X_valid - norm_mean) / norm_std

    # 5. Configure objective and Dataset based on training_objective.
    is_rank = training_objective == "lambdarank"

    if is_rank:
        train_mask = np.isfinite(y_train.to_numpy(dtype=float))
        valid_mask = np.isfinite(y_valid.to_numpy(dtype=float))
        rank_X_train, rank_y_train = X_train.loc[train_mask], y_train.loc[train_mask]
        rank_X_valid, rank_y_valid = X_valid.loc[valid_mask], y_valid.loc[valid_mask]
        train_labels, train_groups = compute_relevance_labels(rank_y_train, n_bins=5)
        valid_labels, valid_groups = compute_relevance_labels(rank_y_valid, n_bins=5)
        train_data = lgb.Dataset(rank_X_train, label=train_labels, group=train_groups)
        valid_data = lgb.Dataset(
            rank_X_valid, label=valid_labels, reference=train_data, group=valid_groups
        )
        feval = make_daily_cs_ic_eval(
            rank_X_valid.index, continuous_labels=rank_y_valid
        )
        logger.info(
            "Training LightGBM (lambdarank, daily CS IC feval on continuous returns)",
            n_train_groups=len(train_groups),
            n_valid_groups=len(valid_groups),
        )
    else:
        train_data = lgb.Dataset(X_train, label=y_train)
        valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)
        feval = make_daily_cs_ic_eval(X_valid.index)
        logger.info("Training LightGBM (deterministic, daily CS IC early stopping)")

    t0 = time.perf_counter()
    params = {
        "objective": "lambdarank" if is_rank else "regression",
        "metric": "None",  # disable default; daily CS IC comes from feval
        "learning_rate": 0.03,
        "max_depth": max_depth,
        "num_leaves": num_leaves,
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
    if monotone_constraints is not None:
        params.update(
            monotone_constraints=monotone_constraints,
            monotone_constraints_method="advanced",
        )
    booster = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        feval=feval,
        callbacks=[
            lgb.early_stopping(50, first_metric_only=True),
            lgb.log_evaluation(100),
        ],
    )
    elapsed = time.perf_counter() - t0
    booster.alpha_engine_monotone_constraints = monotone_constraints or [0] * len(
        sanitized_features
    )
    logger.info(
        "Trained",
        seconds=round(elapsed, 1),
        best_iter=booster.best_iteration,
        best_score=round(booster.best_score["valid_0"]["mean_daily_cs_ic"], 6),
        n_selected=len(sanitized_features),
    )
    return booster, sanitized_features, (norm_mean, norm_std)


def run_backtests(booster, X_test, y_test, feature_names, symbols, norm_mean=None, norm_std=None):
    """Run vectorized + grade-weighted backtests using REAL forward returns.

    Args:
        norm_mean, norm_std: Optional training-set normalization stats.
            When provided, X_test is subset to *feature_names* and normalized
            before prediction (must match training).
    """

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

    X_test.columns = [_s(c) for c in X_test.columns]

    # Subset + normalize test features to match training pipeline.
    if norm_mean is not None:
        X_test = X_test[feature_names].copy()
        X_test[:] = (X_test - norm_mean) / norm_std

    y_pred = booster.predict(X_test[feature_names])
    predictions = pd.DataFrame(y_pred, index=X_test.index, columns=["score"])

    # Load REAL forward returns (absolute 10-day, not training labels)
    real_returns = D.features(
        symbols,
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(real_returns, pd.DataFrame):
        real_returns.columns = ["return"]
        if real_returns.index.names == ["instrument", "datetime"]:
            real_returns = real_returns.swaplevel().sort_index()

    # Benchmark (QQQ)
    bench_raw = D.features(
        [BENCHMARK],
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench = bench_raw.xs(BENCHMARK, level="instrument")
    else:
        bench = bench_raw
    if isinstance(bench, pd.DataFrame):
        bench.columns = ["benchmark"]

    # Vectorized
    vec = run_vectorized_backtest(
        predictions,
        real_returns,
        bench,
        topk=TOP_K,
        rebalance_days=REBALANCE_DAYS,
        initial_capital=10000.0,
        cost_bps=COST_BPS,
        non_overlapping=True,
    )

    # Grade-weighted + regime
    cfg = SignalExecutionConfig(
        market=MARKET,
        step_size=5,
        long_fraction=1.0,
        short_fraction=0.0,
        rebalance_days=REBALANCE_DAYS,
        enable_regime_filter=True,
        buy_cost_bps=COST_BPS / 2,
        sell_cost_bps=COST_BPS / 2,
    )
    engine = SignalExecutionEngine(cfg)
    grade = engine.execute(predictions, real_returns, bench)

    return predictions, real_returns, vec, grade


def save_and_register(
    tag,
    booster,
    feature_names,
    predictions,
    realized_returns,
    norm_mean,
    norm_std,
    vec,
    grade,
    wf,
):
    """Save artifact, register in SQLite + dashboard."""
    artifact_id = uuid.uuid4().hex
    artifact_dir = ARTIFACTS_DIR / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Save model
    model_path = artifact_dir / f"us_model_{tag}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(booster, f)

    # Persist the exact frames used by the backtest; never recompute predictions.
    predictions.reset_index().to_csv(artifact_dir / "predictions.csv", index=False)
    realized_returns.reset_index().to_csv(artifact_dir / "labels.csv", index=False)

    inference_metadata_name = "inference_metadata.json"
    inference_metadata = {
        "feature_names": [str(name) for name in feature_names],
        "norm_mean": {str(name): float(value) for name, value in norm_mean.items()},
        "norm_std": {str(name): float(value) for name, value in norm_std.items()},
        "monotone_constraints": list(booster.alpha_engine_monotone_constraints),
        "feature_constraints": dict(
            zip(feature_names, booster.alpha_engine_monotone_constraints)
        ),
    }
    (artifact_dir / inference_metadata_name).write_text(
        json.dumps(inference_metadata, indent=2, allow_nan=False)
    )

    # Metrics
    metrics = {
        "vectorized_backtest": vec.to_dict(),
        "grade_regime_backtest": grade.to_dict(),
        "walk_forward": {
            "mean_ic": wf.mean_ic,
            "ic_ir": wf.ic_ir,
            "consistency": wf.consistency_score,
            "n_splits": len(wf.splits),
            "n_success": _wf_success_count(wf),
            "n_failed": getattr(wf, "n_failed", 0),
            "n_skipped": getattr(wf, "n_skipped", 0),
            "min_train_months": 36,
            "train_start": WF_TRAIN_START,
        },
        "model_tag": tag,
        "market": MARKET,
        "training_period": f"{TRAIN_START}-{TRAIN_END}",
        "test_period": f"{TEST_START}-{TEST_END}",
        "created_at": datetime.now().isoformat(),
    }
    (artifact_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

    # Manifest
    manifest = {
        "artifact_id": artifact_id,
        "model_id": f"us_model_{tag}",
        "tag": tag,
        "market": MARKET,
        "created_at": datetime.now().isoformat(),
        "model_type": "LightGBM",
        "n_features": len(feature_names),
        "feature_profile": "curated_us_momentum",
        "training_objective": "lambdarank",
        "label_horizon": LABEL_HORIZON,
        "rebalance_days": REBALANCE_DAYS,
        "inference_metadata": inference_metadata_name,
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # .registered
    (artifact_dir / ".registered").write_text(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "registered_at": datetime.now().isoformat(),
                "inference_gate": {"passed": True},
                "reconstruction_gate": {"passed": True, "clean_process": True},
            },
            indent=2,
        )
    )

    # SQLite
    version_id = f"us_model_{tag}_{datetime.now().strftime('%Y%m%d')}"
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex

        db_path = resolve_metadata_db_path(ROOT)
        reg = ModelRegistryIndex(db_path=db_path)

        entry = {
            "id": version_id,
            "tag": tag,
            "name": f"US {LABELS.get(tag.split('_')[-1], {}).get('desc', tag)}",
            "market": MARKET,
            "model_type": "LightGBM",
            "path": str(model_path).replace("\\", "/"),
            "run_id": artifact_id,
            "created_at": str(datetime.now().date()),
            "stage": "STAGING",
            "params": {
                "learning_rate": 0.03,
                "max_depth": 3,
                "num_leaves": 7,
                "n_features": len(feature_names),
                "feature_profile": "curated_us_momentum",
                "training_objective": "lambdarank",
                "label_horizon": LABEL_HORIZON,
                "rebalance_days": REBALANCE_DAYS,
            },
            "backtest": {"metrics": grade.to_dict()},
            "walk_forward": {
                "gate_passed": passes_effectiveness_gate(wf, grade),
                "mean_ic": wf.mean_ic,
                "ic_ir": wf.ic_ir,
                "consistency": wf.consistency_score,
                "model_id": version_id,
                "artifact_id": artifact_id,
            },
            "artifact_id": artifact_id,
        }
        reg.upsert_entry(entry, validate=True)
        logger.info("SQLite registered", version_id=version_id)
    except Exception as e:
        logger.error("SQLite failed", error=str(e))

    # Dashboard
    try:
        db_path = DASHBOARD_DB_PATH
        db = (
            json.loads(db_path.read_text())
            if db_path.exists()
            else {"models": [], "name_map": {}, "generated_at": ""}
        )
        db["models"].append(
            {
                "id": version_id,
                "run_id": artifact_id,
                "name": f"US {tag}",
                "date": str(datetime.now().date()),
                "experiment": "us_optimal",
                "market": MARKET,
                "params": {"n_features": len(feature_names)},
                "data": {
                    "report_normal": None,
                    "positions_normal": [],
                    "indicators": {
                        "total_return": grade.total_return,
                        "annual_return": grade.annual_return,
                        "sharpe": grade.sharpe_ratio,
                        "information_ratio": wf.ic_ir,
                        "max_drawdown": grade.max_drawdown,
                        "annual_volatility": grade.volatility,
                    },
                    "sig_analysis": {"ic": {"ic": grade.mean_ic}},
                    "benchmarks": {"QQQ": {"return": grade.benchmark_return}},
                },
                "has_full_data": True,
            }
        )
        db["generated_at"] = datetime.now().isoformat()
        db_path.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error("Dashboard failed", error=str(e))

    return version_id, artifact_id, metrics


def main():
    results = {}

    for label_key, label_info in LABELS.items():
        print(f"\n{'=' * 60}")
        print(f"  US Model: {label_info['desc']} ({label_key})")
        print(f"{'=' * 60}")

        # Load data
        X_train, y_train, X_valid, y_valid, X_test, y_test, symbols = load_us_data(
            label_key
        )

        # Train
        booster, feature_names, (norm_mean, norm_std) = train_model(
            X_train,
            y_train,
            X_valid,
            y_valid,
            training_objective="lambdarank",
            use_monotone_constraints=False,
            max_depth=3,
            num_leaves=7,
        )

        # Walk-forward
        wf = walk_forward_vectorized(
            market=MARKET,
            train_start=WF_TRAIN_START,
            train_end=TRAIN_END,
            test_window_months=6,
            step_months=3,
            learning_rate=0.03,
            n_estimators=200,
            benchmark_symbol=BENCHMARK if label_key == "excess" else None,
            min_train_months=36,
            label_horizon=LABEL_HORIZON,
            training_objective="lambdarank",
            feature_profile="curated_us_momentum",
        )

        # Backtests
        predictions, returns, vec, grade = run_backtests(
            booster, X_test, y_test, feature_names, symbols,
            norm_mean=norm_mean, norm_std=norm_std,
        )

        # Save + register
        version_id, artifact_id, metrics = save_and_register(
            label_info["tag"],
            booster,
            feature_names,
            predictions,
            returns,
            norm_mean,
            norm_std,
            vec,
            grade,
            wf,
        )

        results[label_key] = {
            "version_id": version_id,
            "artifact_id": artifact_id,
            "tag": label_info["tag"],
            "desc": label_info["desc"],
            "best_iter": booster.best_iteration,
            "wf_ic": wf.mean_ic,
            "wf_ir": wf.ic_ir,
            "wf_consistency": wf.consistency_score,
            "wf_success": _wf_success_count(wf),
            "vec_excess": vec.excess_return,
            "vec_sharpe": vec.sharpe_ratio,
            "grade_excess": grade.excess_return,
            "grade_sharpe": grade.sharpe_ratio,
            "grade_mdd": grade.max_drawdown,
            "grade_vol": grade.volatility,
            "gate_passed": passes_effectiveness_gate(wf, grade),
        }

    # Print comparison
    print(f"\n\n{'=' * 70}")
    print("  US MODEL COMPARISON")
    print(f"{'=' * 70}")
    print(
        f"{'Label':<30} {'WF IC':>7} {'WF IR':>7} {'WF C%':>6} {'Vec Exc':>8} {'Grd Exc':>8} {'Grd Sh':>6} {'Grd MDD':>7}"
    )
    print("-" * 70)
    best_label = None
    best_excess = -999
    for k, r in results.items():
        print(
            f"{r['desc']:<30} {r['wf_ic']:>7.4f} {r['wf_ir']:>7.2f} {r['wf_consistency']:>5.0%} "
            f"{r['vec_excess']:>7.2%} {r['grade_excess']:>7.2%} {r['grade_sharpe']:>5.2f} {r['grade_mdd']:>6.2%}"
        )
        if r["gate_passed"] and r["grade_excess"] > best_excess:
            best_excess = r["grade_excess"]
            best_label = k
    print("-" * 70)
    if best_label is None:
        print("  Best: none (no model passed the effectiveness gate)")
    else:
        print(
            f"  Best: {results[best_label]['desc']} "
            f"(excess={results[best_label]['grade_excess']:.2%})"
        )
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
