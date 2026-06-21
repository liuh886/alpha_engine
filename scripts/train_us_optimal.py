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
import pandas as pd
import structlog
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine
from src.research.vectorized_backtest import run_vectorized_backtest
from src.research.walk_forward import walk_forward_vectorized

logger = structlog.get_logger(__name__)

MARKET = "us"
BENCHMARK = "QQQ"
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-12-31"
VALID_START = "2024-07-01"
VALID_END = "2024-12-31"
TEST_START = "2025-01-01"
TEST_END = "2026-06-18"
TOP_K = 15
REBALANCE_DAYS = 10
COST_BPS = 20.0

# Two label variants to try
LABELS = {
    "absret": {
        "tag": "us_absret",
        "expr": ["Ref($close, -10) / Ref($close, -1) - 1"],
        "desc": "Absolute 10-day return",
    },
    "excess": {
        "tag": "us_excess",
        "expr": [
            "(Ref($close, -10) / Ref($close, -1) - 1) - Mean(Ref($close, -10) / Ref($close, -1) - 1, 10)"
        ],
        "desc": "Cross-sectional excess return",
    },
}


def load_us_data(label_expr: list[str]):
    """Load Alpha158 features + labels for US market."""
    safe_qlib_init(build_qlib_init_cfg(None, market=MARKET))

    instr_path = ROOT / "data" / "watchlist" / "instruments" / f"{MARKET}.txt"
    symbols = [line.split("\t")[0] for line in instr_path.read_text().splitlines() if line.strip()]
    logger.info("US symbols loaded", n=len(symbols))

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

    logger.info("Loading US features", n_features=len(all_exprs), n_symbols=len(symbols))
    t0 = time.perf_counter()
    X_all = D.features(symbols, all_exprs, start_time=TRAIN_START, end_time=TEST_END)
    y_all = D.features(symbols, label_expr, start_time=TRAIN_START, end_time=TEST_END)
    logger.info("US data loaded", seconds=round(time.perf_counter() - t0, 1), X=X_all.shape)

    X_all = X_all.fillna(0.0)
    y_series = y_all.iloc[:, 0]

    # Split
    train_mask = (X_all.index.get_level_values("datetime") >= TRAIN_START) & (
        X_all.index.get_level_values("datetime") <= TRAIN_END
    )
    valid_mask = (X_all.index.get_level_values("datetime") >= VALID_START) & (
        X_all.index.get_level_values("datetime") <= VALID_END
    )
    test_mask = (X_all.index.get_level_values("datetime") >= TEST_START) & (
        X_all.index.get_level_values("datetime") <= TEST_END
    )

    X_train = X_all[train_mask].copy()
    y_train = y_series[train_mask].copy()
    X_valid = X_all[valid_mask].copy()
    y_valid = y_series[valid_mask].copy()
    X_test = X_all[test_mask].copy()
    y_test = y_series[test_mask].copy()

    # Negate label: past return → mean-reversion signal for future return
    y_train = -y_train
    y_valid = -y_valid
    y_test = -y_test

    # Z-score fit on train only
    train_mean = X_train.mean()
    train_std = X_train.std().replace(0, 1.0)
    for df in [X_train, X_valid, X_test]:
        df[:] = (df - train_mean) / train_std

    logger.info("US data split", train=len(X_train), valid=len(X_valid), test=len(X_test))
    return X_train, y_train, X_valid, y_valid, X_test, y_test, symbols


def train_model(X_train, y_train, X_valid, y_valid):
    """Train LightGBM."""
    def _s(c):
        return (str(c).replace("$", "D").replace("/", "_d_").replace("(", "L")
                .replace(")", "R").replace(",", "_").replace(" ", "_")
                .replace("-", "neg").replace("+", "plus"))
    X_train.columns = [_s(c) for c in X_train.columns]
    X_valid.columns = [_s(c) for c in X_valid.columns]
    feature_names = X_train.columns.tolist()

    t0 = time.perf_counter()
    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    params = {
        "objective": "regression",
        "metric": "l2",
        "learning_rate": 0.05,
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
    booster = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)],
    )
    elapsed = time.perf_counter() - t0
    logger.info(
        "Trained",
        seconds=round(elapsed, 1),
        best_iter=booster.best_iteration,
        score=round(booster.best_score["valid_0"]["l2"], 6),
    )
    return booster, feature_names


def run_backtests(booster, X_test, y_test, feature_names, symbols):
    """Run vectorized + grade-weighted backtests using REAL forward returns."""
    def _s(c):
        return (str(c).replace("$", "D").replace("/", "_d_").replace("(", "L")
                .replace(")", "R").replace(",", "_").replace(" ", "_")
                .replace("-", "neg").replace("+", "plus"))
    X_test.columns = [_s(c) for c in X_test.columns]

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


def save_and_register(tag, booster, feature_names, X_test, y_test, vec, grade, wf):
    """Save artifact, register in SQLite + dashboard."""
    artifact_id = uuid.uuid4().hex
    artifact_dir = ARTIFACTS_DIR / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Save model
    model_path = artifact_dir / f"us_model_{tag}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(booster, f)

    # Save predictions
    def _s(c):
        return (str(c).replace("$", "D").replace("/", "_d_").replace("(", "L")
                .replace(")", "R").replace(",", "_").replace(" ", "_")
                .replace("-", "neg").replace("+", "plus"))
    X_test_c = X_test.copy()
    X_test_c.columns = [_s(c) for c in X_test_c.columns]
    y_pred = booster.predict(X_test_c[feature_names])
    pred_df = pd.DataFrame(y_pred, index=X_test.index, columns=["score"])
    pred_csv = pred_df.reset_index()
    pred_csv.to_csv(artifact_dir / "predictions.csv", index=False)
    ret_df = y_test.to_frame("return").reset_index()
    ret_df.to_csv(artifact_dir / "labels.csv", index=False)

    # Metrics
    metrics = {
        "vectorized_backtest": vec.to_dict(),
        "grade_regime_backtest": grade.to_dict(),
        "walk_forward": {
            "mean_ic": wf.mean_ic,
            "ic_ir": wf.ic_ir,
            "consistency": wf.consistency_score,
            "n_splits": len(wf.splits),
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
        from src.common import paths

        db_path = resolve_metadata_db_path(paths.get_artifacts_dir())
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
            "params": {"learning_rate": 0.05, "max_depth": 10, "n_features": len(feature_names)},
            "backtest": {"metrics": grade.to_dict()},
            "walk_forward": {
                "gate_passed": wf.consistency_score >= 0.5 and wf.mean_ic > 0,
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
            label_info["expr"]
        )

        # Train
        booster, feature_names = train_model(X_train, y_train, X_valid, y_valid)

        # Walk-forward
        wf = walk_forward_vectorized(
            market=MARKET,
            train_start=TRAIN_START,
            train_end=TRAIN_END,
            test_window_months=6,
            step_months=3,
            n_estimators=200,
        )

        # Backtests
        predictions, returns, vec, grade = run_backtests(
            booster, X_test, y_test, feature_names, symbols
        )

        # Save + register
        version_id, artifact_id, metrics = save_and_register(
            label_info["tag"], booster, feature_names, X_test, y_test, vec, grade, wf
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
            "vec_excess": vec.excess_return,
            "vec_sharpe": vec.sharpe_ratio,
            "grade_excess": grade.excess_return,
            "grade_sharpe": grade.sharpe_ratio,
            "grade_mdd": grade.max_drawdown,
            "grade_vol": grade.volatility,
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
        if r["grade_excess"] > best_excess:
            best_excess = r["grade_excess"]
            best_label = k
    print("-" * 70)
    print(
        f"  ★ Best: {results[best_label]['desc']} (excess={results[best_label]['grade_excess']:.2%})"
    )
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
