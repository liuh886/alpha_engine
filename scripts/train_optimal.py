"""Train optimal model + walk-forward + backtest + register — full pipeline.

Optimal config: Alpha158 features + absolute return label + LightGBM.

Steps:
  1. Load Alpha158 features + absolute return labels
  2. Compare predeclared candidates by historical walk-forward validation
  3. Train the selected LightGBM configuration (2021-2024)
  4. Open the 2025-2026 holdout once with SignalExecutionEngine
  5. Save artifact bundle (model + predictions + labels + config + metrics)
  6. Run effectiveness, inference, and clean reconstruction gates
  7. Register in SQLite + dashboard DB
"""

from __future__ import annotations

import json
import pickle
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import lightgbm as lgb
import numpy as np
import pandas as pd
import structlog
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine
from src.models.reconstruction import validate_inference
from src.research.vectorized_backtest import run_vectorized_backtest
from src.research.walk_forward import _normalize_qlib_index, walk_forward_vectorized

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MARKET = "cn"
BENCHMARK = "000300"
# Production training window - final model is trained on this period only.
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-12-31"  # nominal end; actual training data is purge-cut before VALID_START
# Walk-forward historical evaluation window - separate, longer source so
# label-horizon purges + validation hold-out still leave >= 8 evaluable
# splits.  The WF trains on expanding windows from this start date, but
# the final production model is trained on the TRAIN_START..TRAIN_END
# window above (not on the WF history source).
WF_TRAIN_START = "2018-01-01"
VALID_START = "2024-07-01"
VALID_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END = "2026-06-18"
TOP_K = 15
COST_BPS = 20.0
MODEL_TAG = "optimal_alpha158_absret"


def _wf_success_count(wf) -> int:
    """Count successful walk-forward splits with valid IC."""
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
    """Return whether historical stability and final holdout both pass.

    Matches the US governance thresholds from train_us_optimal.py.
    """
    n_success = _wf_success_count(wf)
    return bool(
        n_success >= 8
        and wf.mean_ic > 0
        and wf.ic_ir > 0.3
        and wf.consistency_score >= 0.6
        and backtest.excess_return > 0
    )


def load_data(label_horizon=10, feature_profile="alpha158"):
    """Load features + absolute return labels.

    Parameters
    ----------
    label_horizon : int
        Number of trading sessions the forward-return label looks ahead.
    feature_profile : str
        ``"alpha158"`` (default) for the full Alpha158 suite, or
        ``"curated_us_momentum"`` for a smaller curated momentum set.
    """
    safe_qlib_init(build_qlib_init_cfg(None, market=MARKET))

    instr_path = ROOT / "data" / "watchlist" / "instruments" / f"{MARKET}.txt"
    symbols = [line.split("\t")[0] for line in instr_path.read_text().splitlines() if line.strip()]
    logger.info("Symbols loaded", n=len(symbols))

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
    label_expr = [f"Ref($close, -{label_horizon}) / Ref($close, -1) - 1"]

    logger.info("Loading features", n_features=len(all_exprs))
    t0 = time.perf_counter()
    X_all = D.features(symbols, all_exprs, start_time=TRAIN_START, end_time=TEST_END)
    y_all = D.features(symbols, label_expr, start_time=TRAIN_START, end_time=TEST_END)
    X_all = _normalize_qlib_index(X_all)
    y_all = _normalize_qlib_index(y_all)
    logger.info("Data loaded", seconds=round(time.perf_counter() - t0, 1), X=X_all.shape)

    X_all = X_all.fillna(0.0)
    y_series = y_all.iloc[:, 0]

    # --- Boundary purge: exclude rows whose *label_horizon*-session forward
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
        observed_dates, TRAIN_START, VALID_START, label_horizon, label="train→valid"
    )
    valid_cutoff = _purge_tail(
        observed_dates, VALID_START, TEST_START, label_horizon, label="valid→test"
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

    # CORRECTED 2026-06-27: The label Ref($close,-10)/Ref($close,-1)-1 is a
    # FORWARD return (t+1 to t+10). Qlib Ref with N<0 looks INTO THE FUTURE
    # (see qlib/data/ops.py:789). For a long-only strategy that buys
    # high-score stocks, we want the model to predict future returns
    # DIRECTLY (high score means high expected return). Do NOT negate.

    # Normalization moved to train_model (after feature selection) so the
    # selector sees raw feature values.

    logger.info("Data split", train=len(X_train), valid=len(X_valid), test=len(X_test))
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
        params["monotone_constraints"] = monotone_constraints
        params["monotone_constraints_method"] = "advanced"
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


def run_backtest(
    booster,
    X_test,
    y_test,
    feature_names,
    symbols,
    norm_mean=None,
    norm_std=None,
    label_horizon=10,
    rebalance_days=None,
):
    """Run vectorized + grade-weighted backtests using REAL forward returns.

    Args:
        norm_mean, norm_std: Optional training-set normalization stats.
            When provided, X_test is subset to *feature_names* and normalized
            before prediction (must match training).
        label_horizon: Number of trading sessions for the return label.
        rebalance_days: Execution cadence. Defaults to ``label_horizon``.
            Must match the horizon the model was trained to predict.
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

    rebalance_days = label_horizon if rebalance_days is None else rebalance_days
    inference_features = X_test[feature_names].copy()

    # Predictions DataFrame
    y_pred = booster.predict(X_test[feature_names])
    predictions = pd.DataFrame(y_pred, index=X_test.index, columns=["score"])

    # Load REAL forward returns matching the candidate's label_horizon
    real_returns = D.features(
        symbols,
        [f"Ref($close, -{label_horizon}) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(real_returns, pd.DataFrame):
        real_returns.columns = ["return"]
        if real_returns.index.names == ["instrument", "datetime"]:
            real_returns = real_returns.swaplevel().sort_index()

    # Benchmark — same horizon as the label
    bench_raw = D.features(
        [BENCHMARK],
        [f"Ref($close, -{label_horizon}) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench = bench_raw.xs(BENCHMARK, level="instrument")
    else:
        bench = bench_raw
    if isinstance(bench, pd.DataFrame):
        bench.columns = ["benchmark"]

    # 1. Vectorized backtest (baseline)
    vec_result = run_vectorized_backtest(
        predictions,
        real_returns,
        bench,
        topk=TOP_K,
        rebalance_days=rebalance_days,
        initial_capital=10000.0,
        cost_bps=COST_BPS,
        non_overlapping=True,
    )

    # 2. Grade-weighted + regime (best engine)
    cfg = SignalExecutionConfig(
        market=MARKET,
        step_size=5,
        long_fraction=1.0,
        short_fraction=0.0,
        rebalance_days=rebalance_days,
        enable_regime_filter=True,
        buy_cost_bps=COST_BPS / 2,
        sell_cost_bps=COST_BPS / 2,
    )
    engine = SignalExecutionEngine(cfg)
    grade_result = engine.execute(predictions, real_returns, bench)

    return predictions, real_returns, vec_result, grade_result, inference_features


def passes_historical_gate(wf) -> bool:
    """Apply candidate-selection gates without consulting the holdout."""
    return bool(
        _wf_success_count(wf) >= 8
        and wf.mean_ic > 0
        and wf.ic_ir > 0.3
        and wf.consistency_score >= 0.6
    )


def select_historical_candidate(results):
    """Select one candidate using historical evidence and a stable tie-break."""
    eligible = [item for item in results if item.get("wf") and passes_historical_gate(item["wf"])]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item["wf"].ic_ir,
            item["wf"].mean_ic,
            item["wf"].consistency_score,
            _wf_success_count(item["wf"]),
            -item["order"],
        ),
    )


def _run_clean_artifact_reconstruction(artifact_id):
    """Load and predict from the artifact in a fresh interpreter."""
    from src.models.reconstruction import ReconstructionResult

    script = r"""
import json, pickle, sys
from src.common.paths import ARTIFACTS_DIR
from src.models.artifact import validate_artifact
from src.models.reconstruction import reconstruct_model

artifact_id = sys.argv[1]
manifest = validate_artifact(artifact_id)
artifact_dir = ARTIFACTS_DIR / "artifacts" / artifact_id

def load_model(_config):
    with open(artifact_dir / manifest.model_binary_path, "rb") as handle:
        return pickle.load(handle)

def predict(model, frame):
    return model.predict(frame[manifest.features])

result = reconstruct_model(
    artifact_id,
    retrain_fn=load_model,
    predict_fn=predict,
    clean_process=True,
)
print(json.dumps(result.__dict__))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, artifact_id],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            status="not_run",
            clean_process=True,
            error=(proc.stderr or "clean reconstruction produced no result")[-1000:],
        )
    return ReconstructionResult(**json.loads(proc.stdout.strip().splitlines()[-1]))


def _snapshot_provenance():
    marker = ARTIFACTS_DIR / "snapshots" / "watchlist_latest.json"
    if marker.exists():
        payload = json.loads(marker.read_text())
        return str(payload.get("snapshot_id", "")), str(payload.get("provider_uri", ""))
    return "watchlist-local", str((ROOT / "data" / "watchlist").resolve())


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
    training_objective="regression",
    feature_profile="alpha158",
    label_horizon=10,
    rebalance_days=10,
    inference_features=None,
    max_depth=4,
    num_leaves=15,
    use_monotone_constraints=True,
):
    """Create a formal artifact and register only after all three gates pass."""
    from src.models.artifact import create_artifact, register_artifact, set_artifacts_root

    if inference_features is None:
        inference_features = pd.DataFrame(
            {name: np.zeros(len(predictions)) for name in feature_names},
            index=predictions.index,
        )

    n_success = _wf_success_count(wf)
    positive_ic_ratio = sum(
        split.status == "success" and split.ic is not None and split.ic > 0
        for split in getattr(wf, "splits", [])
    ) / max(n_success, 1)
    metrics = {
        "vectorized_backtest": vec.to_dict(),
        "grade_regime_backtest": grade.to_dict(),
        "walk_forward": {
            "mean_ic": wf.mean_ic,
            "ic_ir": wf.ic_ir,
            "consistency": wf.consistency_score,
            "positive_ic_ratio": positive_ic_ratio,
            "n_splits": len(wf.splits),
            "n_success": n_success,
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
    model_params = {
        "learning_rate": 0.03,
        "max_depth": max_depth,
        "num_leaves": num_leaves,
        "lambda_l1": 1.0,
        "lambda_l2": 10.0,
        "min_data_in_leaf": 100,
        "n_features": len(feature_names),
        "feature_profile": feature_profile,
        "training_objective": training_objective,
        "label_horizon": label_horizon,
        "rebalance_days": rebalance_days,
        "wf_train_start": WF_TRAIN_START,
        "use_monotone_constraints": use_monotone_constraints,
    }
    snapshot_id, provider_uri = _snapshot_provenance()
    config = {
        "market": MARKET,
        "benchmark": BENCHMARK,
        "model_params": model_params,
        "inference": {
            "feature_names": list(feature_names),
            "norm_mean": {str(k): float(v) for k, v in norm_mean.items()},
            "norm_std": {str(k): float(v) for k, v in norm_std.items()},
        },
        "task": {
            "model": {"class": "LightGBM", "kwargs": model_params},
            "dataset": {
                "kwargs": {
                    "segments": {
                        "train": [TRAIN_START, VALID_START],
                        "valid": [VALID_START, TEST_START],
                        "test": [TEST_START, TEST_END],
                    }
                }
            },
        },
    }
    prediction_bundle = inference_features.loc[predictions.index, feature_names].copy()
    prediction_bundle["score"] = predictions["score"]
    set_artifacts_root(ARTIFACTS_DIR)

    with tempfile.TemporaryDirectory(prefix="cn-model-") as temp_dir:
        model_path = Path(temp_dir) / f"cn_model_{tag}.pkl"
        with model_path.open("wb") as handle:
            pickle.dump(booster, handle)
        manifest = create_artifact(
            model_path,
            config,
            prediction_bundle,
            realized_returns,
            features=list(feature_names),
            label_schema={
                "expression": f"Ref($close,-{label_horizon})/Ref($close,-1)-1",
                "horizon": label_horizon,
            },
            snapshot_id=snapshot_id,
            provider_uri=provider_uri,
            benchmark=BENCHMARK,
            costs={"round_trip_bps": COST_BPS},
            seeds={"python": 42, "numpy": 42, "model": 42},
        )

    artifact_id = manifest.id
    artifact_dir = ARTIFACTS_DIR / "artifacts" / artifact_id
    (artifact_dir / "metrics_extended.json").write_text(
        json.dumps(metrics, indent=2, default=str)
    )

    effectiveness_passed = passes_effectiveness_gate(wf, grade)
    inference_result = validate_inference(artifact_id) if effectiveness_passed else None
    reconstruction_result = (
        _run_clean_artifact_reconstruction(artifact_id)
        if inference_result is not None and inference_result.passed
        else None
    )
    all_gates_passed = bool(
        effectiveness_passed
        and inference_result is not None
        and inference_result.passed
        and reconstruction_result is not None
        and reconstruction_result.passed
        and reconstruction_result.clean_process
    )

    version_id = f"cn_model_{tag}_{datetime.now().strftime('%Y%m%d')}"
    if not all_gates_passed:
        failure = {
            "effectiveness_passed": effectiveness_passed,
            "inference": getattr(inference_result, "__dict__", None),
            "reconstruction": getattr(reconstruction_result, "__dict__", None),
        }
        (artifact_dir / "gate_failed.json").write_text(
            json.dumps(failure, indent=2, default=str)
        )
        return version_id, artifact_id, metrics

    register_artifact(
        artifact_id,
        inference_result=inference_result,
        reconstruction_result=reconstruction_result,
    )
    marker_path = artifact_dir / ".registered"
    marker = json.loads(marker_path.read_text())
    marker["effectiveness_gate"] = {
        "passed": True,
        "n_success": n_success,
        "mean_ic": wf.mean_ic,
        "ic_ir": wf.ic_ir,
        "consistency": wf.consistency_score,
        "holdout_excess_return": grade.excess_return,
    }
    marker_path.write_text(json.dumps(marker, indent=2, default=str))

    from src.assistant.metadata_db import resolve_metadata_db_path
    from src.assistant.model_registry_index import ModelRegistryIndex

    stored_model_path = artifact_dir / manifest.model_binary_path
    entry = {
        "id": version_id,
        "tag": tag,
        "name": f"CN {feature_profile} AbsRet ({training_objective})",
        "market": MARKET,
        "model_type": "LightGBM",
        "path": str(stored_model_path).replace("\\", "/"),
        "run_id": artifact_id,
        "created_at": str(datetime.now().date()),
        "stage": "STAGING",
        "description": f"CN historical-WF selected model; horizon={label_horizon}.",
        "params": model_params,
        "backtest": {"metrics": grade.to_dict()},
        "walk_forward": {
            "gate_passed": True,
            "inference_passed": True,
            "reconstruction_passed": True,
            "n_success": n_success,
            "n_total_splits": len(wf.splits),
            "positive_ic_ratio": positive_ic_ratio,
            "mean_ic": wf.mean_ic,
            "ic_ir": wf.ic_ir,
            "consistency": wf.consistency_score,
            "model_id": version_id,
            "artifact_id": artifact_id,
        },
        "artifact_id": artifact_id,
        "inference_passed": True,
        "gate_passed": True,
    }
    registry = ModelRegistryIndex(db_path=resolve_metadata_db_path(ROOT))
    registry.upsert_entry(entry, validate=True)

    db = (
        json.loads(DASHBOARD_DB_PATH.read_text())
        if DASHBOARD_DB_PATH.exists()
        else {"models": [], "name_map": {}, "generated_at": ""}
    )
    db["models"] = [item for item in db["models"] if item.get("id") != version_id]
    db["models"].append(
        {
            "id": version_id,
            "run_id": artifact_id,
            "name": f"CN {tag} ({training_objective})",
            "date": str(datetime.now().date()),
            "experiment": "cn_optimal",
            "market": MARKET,
            "stage": "STAGING",
            "params": model_params,
            "data": {
                "report_normal": None,
                "positions_normal": [],
                "indicators": {
                    "total_return": grade.total_return,
                    "annual_return": grade.annual_return,
                    "excess_return": grade.excess_return,
                    "benchmark_return": grade.benchmark_return,
                    "sharpe": grade.sharpe_ratio,
                    "information_ratio": wf.ic_ir,
                    "max_drawdown": grade.max_drawdown,
                    "annual_volatility": grade.volatility,
                },
                "sig_analysis": {
                    "ic": {"ic": wf.mean_ic},
                    "ric": {"ric": wf.mean_ic},
                    "icir": {"icir": wf.ic_ir},
                    "positive_ic_ratio": positive_ic_ratio,
                    "consistency": wf.consistency_score,
                    "wf_successful_splits": n_success,
                    "wf_total_splits": len(wf.splits),
                },
                "benchmarks": {"CSI300": {"return": grade.benchmark_return}},
            },
            "has_full_data": True,
        }
    )
    db["generated_at"] = datetime.now().isoformat()
    DASHBOARD_DB_PATH.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    return version_id, artifact_id, metrics


CANDIDATES = [
    ("a158_10d_reg", "regression", "alpha158", 10),
    ("a158_10d_lambda", "lambdarank", "alpha158", 10),
    ("a158_20d_reg", "regression", "alpha158", 20),
    ("a158_20d_lambda", "lambdarank", "alpha158", 20),
    ("curated_10d_reg", "regression", "curated_us_momentum", 10),
    ("curated_10d_lambda", "lambdarank", "curated_us_momentum", 10),
    ("curated_20d_reg", "regression", "curated_us_momentum", 20),
    ("curated_20d_lambda", "lambdarank", "curated_us_momentum", 20),
]


def main():
    historical_results = []
    for order, (suffix, objective, profile, horizon) in enumerate(CANDIDATES):
        tag = f"{MODEL_TAG}_{suffix}"
        try:
            wf = walk_forward_vectorized(
                market=MARKET,
                train_start=WF_TRAIN_START,
                train_end=TRAIN_END,
                test_window_months=6,
                step_months=3,
                learning_rate=0.03,
                n_estimators=200,
                min_train_months=36,
                label_horizon=horizon,
                training_objective=objective,
                feature_profile=profile,
            )
            historical_results.append(
                {
                    "order": order,
                    "tag": tag,
                    "objective": objective,
                    "profile": profile,
                    "horizon": horizon,
                    "wf": wf,
                }
            )
            print(
                f"{tag}: WF IC={wf.mean_ic:.4f}, IR={wf.ic_ir:.3f}, "
                f"consistency={wf.consistency_score:.1%}, success={_wf_success_count(wf)}"
            )
        except Exception as exc:
            logger.exception("Historical candidate failed", tag=tag, error=str(exc))
            historical_results.append(
                {
                    "order": order,
                    "tag": tag,
                    "objective": objective,
                    "profile": profile,
                    "horizon": horizon,
                    "error": str(exc),
                }
            )

    selected = select_historical_candidate(historical_results)
    if selected is None:
        print("No CN candidate passed the historical walk-forward gate; holdout was not opened.")
        return None

    horizon = selected["horizon"]
    rebalance_days = horizon
    X_train, y_train, X_valid, y_valid, X_test, y_test, symbols = load_data(
        label_horizon=horizon,
        feature_profile=selected["profile"],
    )
    booster, feature_names, (norm_mean, norm_std) = train_model(
        X_train,
        y_train,
        X_valid,
        y_valid,
        training_objective=selected["objective"],
        use_monotone_constraints=selected["profile"] != "curated_us_momentum",
        max_depth=3 if selected["profile"] == "curated_us_momentum" else 4,
        num_leaves=7 if selected["profile"] == "curated_us_momentum" else 15,
    )
    predictions, returns, vec, grade, inference_features = run_backtest(
        booster,
        X_test,
        y_test,
        feature_names,
        symbols,
        norm_mean=norm_mean,
        norm_std=norm_std,
        label_horizon=horizon,
        rebalance_days=rebalance_days,
    )
    version_id, artifact_id, metrics = save_and_register(
        selected["tag"],
        booster,
        feature_names,
        predictions,
        returns,
        norm_mean,
        norm_std,
        vec,
        grade,
        selected["wf"],
        training_objective=selected["objective"],
        feature_profile=selected["profile"],
        label_horizon=horizon,
        rebalance_days=rebalance_days,
        inference_features=inference_features,
        max_depth=3 if selected["profile"] == "curated_us_momentum" else 4,
        num_leaves=7 if selected["profile"] == "curated_us_momentum" else 15,
        use_monotone_constraints=selected["profile"] != "curated_us_momentum",
    )
    print(
        f"Selected {selected['tag']} by historical WF; holdout excess={grade.excess_return:.2%}; "
        f"artifact={artifact_id}; model={version_id}."
    )
    return metrics


if __name__ == "__main__":
    main()
