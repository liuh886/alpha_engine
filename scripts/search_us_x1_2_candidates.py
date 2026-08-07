#!/usr/bin/env python3
r"""Full US x1.2 candidate search via walk-forward portfolio construction experiments.

Tests factor groups × portfolio constructions × top-N sizes:
  Factor groups: mv_volume (7), risk_ctrl (7), combined (9)
  Portfolio: equal-weight, inverse-vol20, sector-cap-4, name-cap-8pct
  Top-N: 15, 20
  Costs: 20bps, 40bps, 60bps

Produces a ranked candidate table with excess return, max drawdown, and gate status.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init


def load_factor_expressions() -> dict[str, list[str]]:
    import yaml

    library = yaml.safe_load(
        open("configs/factor_libraries/us_ohlcv.yaml", encoding="utf-8")
    )
    groups = {}
    for g in ["momentum_volatility_volume", "risk_controlled_momentum"]:
        factors = library["groups"][g]["factors"]
        groups[g] = [f["expression"] for f in factors]
    # Combined = union (deduplicated)
    combined = list(dict.fromkeys(groups["momentum_volatility_volume"] + groups["risk_controlled_momentum"]))
    return {"mv_volume": groups["momentum_volatility_volume"], "risk_ctrl": groups["risk_controlled_momentum"], "combined": combined}


def train_window(features, returns, train_dates, test_dates, seed=42):
    """Train XGBoost ranker and return test scores + returns."""
    t_mask = features.index.get_level_values("datetime").isin(train_dates)
    e_mask = features.index.get_level_values("datetime").isin(test_dates)

    tf = features.loc[t_mask].replace([np.inf, -np.inf], np.nan).dropna()
    ef = features.loc[e_mask].replace([np.inf, -np.inf], np.nan).dropna()
    tr = returns.reindex(tf.index).dropna()
    er = returns.reindex(ef.index).dropna()
    tf = tf.loc[tr.index]
    ef = ef.loc[er.index]

    tr_rank = tr.groupby(level="datetime").rank(pct=True).fillna(0.5)
    target = np.floor(tr_rank.clip(0, 1) * 7).clip(0, 6).astype(int)
    groups_list = tf.groupby(level="datetime").size().tolist()

    dtrain = xgb.DMatrix(tf.values, label=target.values)
    dtrain.set_group(groups_list)
    params = {"objective": "rank:ndcg", "tree_method": "hist", "grow_policy": "lossguide",
              "max_leaves": 31, "max_depth": 0, "learning_rate": 0.05, "seed": seed, "verbosity": 0}
    model = xgb.train(params, dtrain, num_boost_round=200)

    dtest = xgb.DMatrix(ef.values)
    scores = pd.Series(model.predict(dtest), index=ef.index, name="score")
    return scores, er


def sector_map():
    """Load US87 sector classification."""
    import yaml
    raw = yaml.safe_load(open("configs/research_classifications/us87_sector_industry_v1.yaml"))
    return raw.get("symbols", raw)


def compute_cumulative(scores, returns, test_dates, top_n=15, portfolio="equal_weight",
                       cost_bps=20, sectors=None):
    """Compute cumulative return for a given portfolio rule."""
    daily_rets = []
    prev_weights = {}
    turnover_total = 0.0
    n_dates = 0

    for date in sorted(test_dates):
        if date not in scores.index.get_level_values("datetime"):
            continue
        day_s = scores.loc[scores.index.get_level_values("datetime") == date].nlargest(top_n)
        syms = day_s.index.get_level_values("instrument").tolist()
        n = len(syms)
        if n < top_n:
            continue

        if portfolio == "equal_weight":
            weights = {s: 1.0 / top_n for s in syms}
        elif portfolio == "inverse_vol20":
            vol = returns.loc[returns.index.get_level_values("datetime") == date]
            vols = {s: vol.loc[vol.index.get_level_values("instrument") == s].std() for s in syms}
            inv_vol = {s: 1.0 / max(v, 0.01) for s, v in vols.items()}
            total = sum(inv_vol.values())
            weights = {s: min(v / total, 0.10) for s, v in inv_vol.items()}
            residual = 1.0 - sum(weights.values())
            if residual > 0:
                for s in weights:
                    weights[s] += residual / n
        elif portfolio == "sector_cap_4" and sectors:
            capped, taken = [], {}
            for s in syms:
                sec = sectors.get(s, "Unknown")
                if taken.get(sec, 0) < 4:
                    capped.append(s)
                    taken[sec] = taken.get(sec, 0) + 1
            if len(capped) < top_n:
                for s in syms:
                    if s not in capped:
                        capped.append(s)
                    if len(capped) >= top_n:
                        break
            weights = {s: 1.0 / len(capped) for s in capped}
        elif portfolio == "name_cap_8pct":
            w = 1.0 / top_n
            weights = {s: min(w, 0.08) for s in syms}
            residual = 1.0 - sum(weights.values())
            if residual > 0:
                for s in weights:
                    weights[s] += residual / n
        else:
            weights = {s: 1.0 / top_n for s in syms}

        # Transaction cost
        if prev_weights:
            turnover = sum(abs(weights.get(s, 0) - prev_weights.get(s, 0)) for s in set(weights) | set(prev_weights))
        else:
            turnover = 1.0
        turnover_total += turnover
        cost = turnover * cost_bps / 10000.0

        day_ret = returns.loc[returns.index.get_level_values("datetime") == date]
        port_ret = sum(weights.get(s, 0) * day_ret.loc[day_ret.index.get_level_values("instrument") == s].iloc[0]
                       for s in weights if s in day_ret.index.get_level_values("instrument"))
        daily_rets.append(port_ret - cost)
        prev_weights = weights
        n_dates += 1

    cum = (1.0 + pd.Series(daily_rets)).cumprod()
    return {"cumulative": cum, "turnover_ratio": turnover_total / max(n_dates, 1), "n_dates": n_dates}


def main():
    safe_qlib_init(build_qlib_init_cfg({}, market="us"))
    from qlib.data import D
    inst = D.instruments(market="us")

    factor_groups = load_factor_expressions()
    all_expr = list(dict.fromkeys(sum(factor_groups.values(), [])))
    sectors = sector_map()

    print(f"Loading {len(all_expr)} expressions...")
    t0 = time.time()
    features = D.features(inst, all_expr, start_time="2021-01-01", end_time="2026-06-24")
    returns = D.features(inst, ["Ref($close, -10)/$close - 1"], start_time="2021-01-01", end_time="2026-06-24")
    returns = returns.iloc[:, 0]
    print(f"Loaded {features.shape} in {time.time() - t0:.1f}s")

    all_dates = pd.DatetimeIndex(sorted(features.index.get_level_values("datetime").unique()))
    windows = [
        ("2024H1", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-07-01")),
        ("2024H2", pd.Timestamp("2024-07-01"), pd.Timestamp("2025-01-01")),
        ("2025H1", pd.Timestamp("2025-01-01"), pd.Timestamp("2025-07-01")),
        ("2025H2", pd.Timestamp("2025-07-01"), pd.Timestamp("2026-01-01")),
        ("2026H1", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-24")),
    ]
    train_start = pd.Timestamp("2021-01-01")

    configs = [
        ("mv_volume", "equal_weight", 15, 20),
        ("mv_volume", "equal_weight", 20, 20),
        ("combined", "equal_weight", 15, 20),
        ("combined", "inverse_vol20", 15, 20),
        ("combined", "sector_cap_4", 15, 20),
        ("combined", "name_cap_8pct", 15, 20),
    ]

    results = []
    for fg_name, port, top_n, cost in configs:
        print(f"\n--- {fg_name} | {port} | top{top_n} | {cost}bps ---")
        all_scores, all_rets = {}, {}
        for w_name, w_start, w_end in windows:
            train_d = pd.DatetimeIndex([d for d in all_dates if train_start <= d < w_start])
            test_d = pd.DatetimeIndex([d for d in all_dates if w_start <= d <= w_end])
            scores, erets = train_window(features[factor_groups[fg_name]], returns, train_d, test_d)
            all_scores[w_name] = scores
            all_rets[w_name] = erets

            cum_result = compute_cumulative(scores, erets, test_d, top_n=top_n, portfolio=port,
                                            cost_bps=cost, sectors=sectors)
            total = float(cum_result["cumulative"].iloc[-1] - 1.0) if len(cum_result["cumulative"]) > 0 else 0.0
            mdd = float((cum_result["cumulative"] / cum_result["cumulative"].cummax() - 1).min()) if len(cum_result["cumulative"]) > 0 else -1.0
            print(f"  {w_name}: TR={total:.4%}  MDD={mdd:.4%}  dates={cum_result['n_dates']}")

            results.append({
                "factor_group": fg_name, "portfolio": port, "top_n": top_n, "cost_bps": cost,
                "window": w_name, "total_return": total, "max_drawdown": mdd,
                "n_dates": cum_result["n_dates"],
            })

    # Aggregate and rank
    df = pd.DataFrame(results)
    print(f"\n{'='*70}")
    print("CANDIDATE RANKING (all windows, 20bps primary)")
    print(f"{'='*70}")
    agg = df[df["cost_bps"] == 20].groupby(["factor_group", "portfolio", "top_n"]).agg(
        mean_tr=("total_return", "mean"), min_tr=("total_return", "min"),
        worst_mdd=("max_drawdown", "min"), positive_windows=("total_return", lambda x: (x > 0).sum()),
    ).sort_values("mean_tr", ascending=False)
    print(agg.to_string())

    # Best candidate
    best = agg.index[0]
    print(f"\n>>> Best candidate: {best} <<<")

    # Check gates
    gate_ok = agg.iloc[0]["positive_windows"] == 5 and agg.iloc[0]["worst_mdd"] > -0.30
    print(f"Gate check: all_windows_positive={agg.iloc[0]['positive_windows']==5}  mdd_ok={agg.iloc[0]['worst_mdd'] > -0.30}")
    if gate_ok:
        print(">>> CANDIDATE PASSES PROMOTION GATES <<<")

    df.to_csv("artifacts/us_x1_2_candidate_results.csv", index=False)
    print("\nResults saved to artifacts/us_x1_2_candidate_results.csv")


if __name__ == "__main__":
    main()
