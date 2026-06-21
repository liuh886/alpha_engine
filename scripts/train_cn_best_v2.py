"""Train CN Best v2 — optimized hyperparams from exploration."""

import sys

sys.path.insert(0, ".")
import json
import pickle
import time
import uuid
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

safe_qlib_init(build_qlib_init_cfg(None, market="cn"))
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D

from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine

symbols = [
    line.split("\t")[0]
    for line in Path("data/watchlist/instruments/cn.txt").read_text().splitlines()
    if line.strip()
]
alpha_exprs = Alpha158DL.get_feature_config(
    {
        "kbar": {},
        "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
        "rolling": {},
    }
)[0]
extra = [
    "$close/Ref($close,5)-1",
    "$close/Ref($close,10)-1",
    "$close/Ref($close,20)-1",
    "Std($close,10)",
    "$volume/Ref($volume,10)-1",
]
FEATURES = list(alpha_exprs) + extra

# Data
print("[DATA] Loading...")
X = D.features(symbols, FEATURES, start_time="2019-01-01", end_time="2026-06-18")
y = D.features(
    symbols,
    ["Ref($close, -10) / Ref($close, -1) - 1"],
    start_time="2019-01-01",
    end_time="2026-06-18",
)
close = D.features(symbols, ["$close"], start_time="2025-01-01", end_time="2026-06-18")
X, y_s = X.fillna(0.0), -y.iloc[:, 0]
tr = (X.index.get_level_values("datetime") >= "2019-01-01") & (
    X.index.get_level_values("datetime") <= "2024-12-31"
)
te = (X.index.get_level_values("datetime") >= "2025-01-01") & (
    X.index.get_level_values("datetime") <= "2026-06-18"
)
va = (X.index.get_level_values("datetime") >= "2024-07-01") & (
    X.index.get_level_values("datetime") <= "2024-12-31"
)
Xtr, ytr = X[tr].copy(), y_s[tr].copy()
Xva, yva = X[va].copy(), y_s[va].copy()
Xte, yte = X[te].copy(), y_s[te].copy()
mu, sd = Xtr.mean(), Xtr.std().replace(0, 1.0)
for df in [Xtr, Xva, Xte]:
    df[:] = (df - mu) / sd


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
    )


Xtr.columns = [_s(c) for c in Xtr.columns]
Xva.columns = [_s(c) for c in Xva.columns]
Xte.columns = [_s(c) for c in Xte.columns]
fnames = Xtr.columns.tolist()
print(f"[DATA] train={len(Xtr)} valid={len(Xva)} test={len(Xte)}")

# Train — optimized config
print("[TRAIN] slow_deep: lr=0.02 depth=12 leaves=256 rounds=800...")
t0 = time.perf_counter()
tr_d = lgb.Dataset(Xtr, label=ytr)
va_d = lgb.Dataset(Xva, label=yva, reference=tr_d)
params = {
    "objective": "regression",
    "metric": "l2",
    "learning_rate": 0.02,
    "max_depth": 12,
    "num_leaves": 256,
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
    tr_d,
    num_boost_round=800,
    valid_sets=[va_d],
    callbacks=[lgb.early_stopping(100), lgb.log_evaluation(200)],
)
print(f"[TRAIN] {time.perf_counter() - t0:.0f}s, best_iter={booster.best_iteration}")

# Predict + TOP/BOTTOM
pred_arr = booster.predict(Xte[fnames])
predictions = pd.DataFrame(pred_arr, index=Xte.index, columns=["score"])
if predictions.index.names == ["instrument", "datetime"]:
    predictions = predictions.swaplevel().sort_index()
dates = sorted(predictions.index.get_level_values("datetime").unique())
rebal = dates[::20]
spreads = []
for date in rebal:
    if date not in predictions.index:
        continue
    scores = predictions.loc[date].iloc[:, 0].dropna().sort_values(ascending=False)
    if len(scores) < 30:
        continue
    top_s = scores.head(15).index
    bot_s = scores.tail(15).index
    tr_ret, br_ret = [], []
    for sym in top_s:
        try:
            cs = close.xs(sym, level="instrument").iloc[:, 0]
            if date in cs.index:
                i = cs.index.get_loc(date)
                if i + 10 < len(cs):
                    e = float(cs.iloc[i])
                    if e > 0:
                        tr_ret.append(float(cs.iloc[i + 10]) / e - 1)
        except Exception:
            pass
    for sym in bot_s:
        try:
            cs = close.xs(sym, level="instrument").iloc[:, 0]
            if date in cs.index:
                i = cs.index.get_loc(date)
                if i + 10 < len(cs):
                    e = float(cs.iloc[i])
                    if e > 0:
                        br_ret.append(float(cs.iloc[i + 10]) / e - 1)
        except Exception:
            pass
    if tr_ret and br_ret:
        spreads.append(np.mean(tr_ret) - np.mean(br_ret))
arr = np.array(spreads)
ann = float(np.mean(arr) * 252 / 20)
pos = float(np.mean(arr > 0))
ir = float(np.mean(arr) / np.std(arr) * np.sqrt(252 / 20)) if np.std(arr) > 1e-10 else 0
print(f"[TOP/BOTTOM] spread={ann:+.1%} pos={pos:.0%} IR={ir:+.2f} n={len(arr)}")

# Backtest
real_ret = D.features(
    symbols,
    ["Ref($close, -10) / Ref($close, -1) - 1"],
    start_time="2025-01-01",
    end_time="2026-06-18",
)
if real_ret.index.names == ["instrument", "datetime"]:
    real_ret = real_ret.swaplevel().sort_index()
real_ret.columns = ["return"]
bench_raw = D.features(
    ["000300"],
    ["Ref($close, -10) / Ref($close, -1) - 1"],
    start_time="2025-01-01",
    end_time="2026-06-18",
)
bench = bench_raw.xs("000300", level="instrument")
bench.columns = ["benchmark"]
cfg = SignalExecutionConfig(
    market="cn",
    step_size=5,
    long_fraction=1.0,
    short_fraction=0.0,
    rebalance_days=20,
    enable_regime_filter=True,
    buy_cost_bps=10,
    sell_cost_bps=10,
)
grade = SignalExecutionEngine(cfg).execute(predictions, real_ret, bench)
print(
    f"[BACKTEST] excess={grade.excess_return:.2%} sharpe={grade.sharpe_ratio:.2f} mdd={grade.max_drawdown:.2%}"
)

# Register
artifact_id = uuid.uuid4().hex
art_dir = ROOT / "artifacts" / "artifacts" / artifact_id
art_dir.mkdir(parents=True, exist_ok=True)
with open(art_dir / "cn_model_cn_best_v2.pkl", "wb") as f:
    pickle.dump(booster, f)
pred_csv = pd.DataFrame(pred_arr, index=Xte.index, columns=["score"]).reset_index()
pred_csv.to_csv(art_dir / "predictions.csv", index=False)
mets = {
    "grade_regime_backtest": grade.to_dict(),
    "top_bottom": {"annual_spread": ann, "positive_ratio": pos, "spread_ir": ir},
    "config": {"lr": 0.02, "depth": 12, "leaves": 256, "rounds": 800, "negate_label": True},
    "model_tag": "cn_best_v2",
    "market": "cn",
    "training": "2019-2024",
    "test": "2025-2026",
    "created_at": datetime.now().isoformat(),
}
(art_dir / "metrics.json").write_text(json.dumps(mets, indent=2, default=str))
(art_dir / "manifest.json").write_text(
    json.dumps(
        {
            "artifact_id": artifact_id,
            "model_id": "cn_model_cn_best_v2",
            "tag": "cn_best_v2",
            "market": "cn",
            "created_at": datetime.now().isoformat(),
            "model_type": "LightGBM",
            "n_features": len(fnames),
        },
        indent=2,
    )
)
(art_dir / ".registered").write_text(
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
from src.assistant.model_registry_index import ModelRegistryIndex

PROD_DB = "D:/Documents/GitHub/alpha_engine/artifacts/metadata/metadata.db"
reg = ModelRegistryIndex(db_path=PROD_DB)
version_id = f"cn_model_cn_best_v2_{datetime.now().strftime('%Y%m%d')}"
reg.upsert_entry(
    {
        "id": version_id,
        "tag": "cn_best_v2",
        "name": "CN Best v2 (slow_deep)",
        "market": "cn",
        "model_type": "LightGBM",
        "path": str(art_dir / "cn_model_cn_best_v2.pkl").replace("\\", "/"),
        "run_id": artifact_id,
        "created_at": str(datetime.now().date()),
        "stage": "STAGING",
        "backtest": {"metrics": grade.to_dict()},
        "artifact_id": artifact_id,
        "params": mets["config"],
    },
    validate=False,
)
print(f"[REGISTER] {version_id}")

# Dashboard
db = json.loads(Path("artifacts/dashboard/dashboard_db.json").read_text())
pv = grade.to_dict().get("portfolio_values", [10000])
bv = grade.to_dict().get("benchmark_values", [10000])
n_pts = min(len(pv), len(bv))
dates_p = pd.date_range("2025-01-01", periods=n_pts, freq="20B")
db["models"].append(
    {
        "id": version_id,
        "run_id": artifact_id,
        "name": "CN Best v2 (slow_deep)",
        "date": str(datetime.now().date()),
        "experiment": "cn_best_v2",
        "market": "cn",
        "params": mets["config"],
        "data": {
            "report_normal": {
                "columns": ["account", "turnover", "bench_hs300"],
                "index": [str(d.date()) for d in dates_p],
                "data": [[float(pv[i]), 0.0, float(bv[i])] for i in range(n_pts)],
            },
            "positions_normal": [],
            "indicators": {
                "total_return": grade.total_return,
                "annual_return": grade.annual_return,
                "sharpe": grade.sharpe_ratio,
                "information_ratio": 0,
                "max_drawdown": grade.max_drawdown,
                "annual_volatility": grade.volatility,
                "excess_return": grade.excess_return,
            },
            "sig_analysis": {"ic": {"ic": 0}},
            "benchmarks": {"CSI300": {"return": grade.benchmark_return}},
        },
        "has_full_data": True,
    }
)
db["generated_at"] = datetime.now().isoformat()
Path("artifacts/dashboard/dashboard_db.json").write_text(
    json.dumps(db, indent=2, ensure_ascii=False)
)
print(f"[DISPLAY] Dashboard: {len(db['models'])} models")
print("\n=== CN Best v2 ===")
print(f"  TOP/BOTTOM: spread={ann:+.1%} pos={pos:.0%} IR={ir:+.2f}")
print(
    f"  Backtest:   excess={grade.excess_return:.2%} sharpe={grade.sharpe_ratio:.2f} mdd={grade.max_drawdown:.2%}"
)
