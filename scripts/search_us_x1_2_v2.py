#!/usr/bin/env python3
r"""US x1.2 candidate search v2: hyperparameter sweep.

Train: XGBoost rank:ndcg, momentum_volatility_volume (7 factors)
Test: 5 windows, Top-15 equal weight, 20/40/60 bps
Sweep: learning_rate × num_boost_round × subsample
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init


def load_expressions():
    import yaml
    library = yaml.safe_load(open("configs/factor_libraries/us_ohlcv.yaml", encoding="utf-8"))
    return [f["expression"] for f in library["groups"]["momentum_volatility_volume"]["factors"]]


def train_and_score(features, returns, train_dates, test_dates, lr, rounds, subsample, seed=42):
    t_mask = features.index.get_level_values("datetime").isin(train_dates)
    e_mask = features.index.get_level_values("datetime").isin(test_dates)
    tf = features.loc[t_mask].replace([np.inf, -np.inf], np.nan).dropna()
    ef = features.loc[e_mask].replace([np.inf, -np.inf], np.nan).dropna()
    tr = returns.reindex(tf.index).dropna(); er = returns.reindex(ef.index).dropna()
    tf = tf.loc[tr.index]; ef = ef.loc[er.index]
    tr_rank = tr.groupby(level="datetime").rank(pct=True).fillna(0.5)
    target = np.floor(tr_rank.clip(0, 1) * 7).clip(0, 6).astype(int)
    groups_list = tf.groupby(level="datetime").size().tolist()
    dtrain = xgb.DMatrix(tf.values, label=target.values)
    dtrain.set_group(groups_list)
    params = {"objective": "rank:ndcg", "tree_method": "hist", "grow_policy": "lossguide",
              "max_leaves": 31, "max_depth": 0, "learning_rate": lr, "subsample": subsample,
              "colsample_bytree": subsample, "seed": seed, "verbosity": 0}
    model = xgb.train(params, dtrain, num_boost_round=rounds)
    dtest = xgb.DMatrix(ef.values)
    return pd.Series(model.predict(dtest), index=ef.index, name="score"), er


def backtest(scores, returns, test_dates, top_n=15, cost_bps=20):
    daily_rets = []
    prev_weights = {}
    for date in sorted(test_dates):
        if date not in scores.index.get_level_values("datetime"):
            continue
        day_s = scores.loc[scores.index.get_level_values("datetime") == date].nlargest(top_n)
        syms = day_s.index.get_level_values("instrument").tolist()
        if len(syms) < top_n:
            continue
        weights = {s: 1.0 / top_n for s in syms}
        turnover = sum(abs(weights.get(s, 0) - prev_weights.get(s, 0)) for s in set(weights) | set(prev_weights)) if prev_weights else 1.0
        cost = turnover * cost_bps / 10000.0
        day_ret = returns.loc[returns.index.get_level_values("datetime") == date]
        port_ret = sum(weights.get(s, 0) * day_ret.loc[day_ret.index.get_level_values("instrument") == s].iloc[0]
                       for s in weights if s in day_ret.index.get_level_values("instrument"))
        daily_rets.append(port_ret - cost)
        prev_weights = weights
    cr = (1.0 + pd.Series(daily_rets)).cumprod()
    return {"TR": float(cr.iloc[-1]-1) if len(cr) else 0, "MDD": float((cr/cr.cummax()-1).min()) if len(cr) else -1}


def main():
    safe_qlib_init(build_qlib_init_cfg({}, market="us"))
    from qlib.data import D
    inst = D.instruments(market="us")
    expressions = load_expressions()
    features = D.features(inst, expressions, start_time="2021-01-01", end_time="2026-06-24")
    # 10-session forward return
    from qlib.data import D as D2
    returns = D2.features(inst, ["Ref($close, -10)/$close - 1"], start_time="2021-01-01", end_time="2026-06-24")
    returns = returns.iloc[:, 0]
    all_dates = pd.DatetimeIndex(sorted(features.index.get_level_values("datetime").unique()))
    windows = [("2024H1","2024-01-01","2024-07-01"),("2024H2","2024-07-01","2025-01-01"),
               ("2025H1","2025-01-01","2025-07-01"),("2025H2","2025-07-01","2026-01-01"),
               ("2026H1","2026-01-01","2026-06-24")]
    train_start = pd.Timestamp("2021-01-01")

    param_grid = [
        ("x1.1_baseline", 0.05, 200, 1.0),
        ("lr0.03_r300", 0.03, 300, 1.0),
        ("lr0.02_r400", 0.02, 400, 1.0),
        ("lr0.03_sub0.8", 0.03, 300, 0.8),
        ("lr0.02_sub0.8_r400", 0.02, 400, 0.8),
    ]

    all_rows = []
    for name, lr, rounds, sub in param_grid:
        print(f"\n--- {name} lr={lr} rounds={rounds} sub={sub} ---")
        for cost in [20, 40, 60]:
            w_results = []
            for w_name, ws, we in windows:
                td = pd.DatetimeIndex([d for d in all_dates if train_start <= d < pd.Timestamp(ws)])
                ed = pd.DatetimeIndex([d for d in all_dates if pd.Timestamp(ws) <= d <= pd.Timestamp(we)])
                scores, erets = train_and_score(features, returns, td, ed, lr, rounds, sub)
                bt = backtest(scores, erets, ed, cost_bps=cost)
                w_results.append(bt)
                all_rows.append({"config":name, "window":w_name, "cost":cost, **bt})

            avg_tr = np.mean([r["TR"] for r in w_results])
            min_tr = min(r["TR"] for r in w_results)
            worst_mdd = min(r["MDD"] for r in w_results)
            pos = sum(1 for r in w_results if r["TR"] > 0)
            print(f"  cost={cost}bps: avg_TR={avg_tr:.4%} min_TR={min_tr:.4%} worst_MDD={worst_mdd:.4%} pos={pos}/5")

    df = pd.DataFrame(all_rows)
    # Best by cost level
    for cost in [20, 40, 60]:
        cdf = df[df["cost"]==cost].groupby("config").agg(avg_TR=("TR","mean"), worst_MDD=("MDD","min"), pos=("TR",lambda x: (x>0).sum()))
        cdf = cdf.sort_values("avg_TR", ascending=False)
        print(f"\n=== RANKING @ {cost}bps ===")
        print(cdf.to_string())

    df.to_csv("artifacts/us_x1_2_hparam_results.csv", index=False)


if __name__ == "__main__":
    main()
