#!/usr/bin/env python3
r"""Compare US factor groups via walk-forward validation.

Tests three factor configurations against the US87 selected pool:
  1. momentum_volatility_volume (baseline, US x1.1) — 7 factors
  2. risk_controlled_momentum (US x1.0) — 7 factors
  3. combined (baseline + risk_controlled) — 9 factors

Output: per-group rank IC, cumulative spread, and relative economics.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init


def load_factor_expressions(group_names: list[str]) -> dict[str, list[str]]:
    """Load factor expressions for each named group."""
    import yaml

    library = yaml.safe_load(
        open("configs/factor_libraries/us_ohlcv.yaml", encoding="utf-8")
    )
    result: dict[str, list[str]] = {}
    for group_name in group_names:
        group = library["groups"].get(group_name)
        if not group:
            continue
        expressions = [f["expression"] for f in group["factors"]]
        result[group_name] = expressions
    return result


def compute_rank_ic(scores: pd.DataFrame, returns: pd.Series) -> float:
    """Mean rank IC across dates."""
    aligned = scores.unstack().rank(axis=1, pct=True)
    daily_ic = aligned.corrwith(returns.unstack().rank(axis=1, pct=True), axis=1)
    return float(daily_ic.mean())


def compute_excess_vs_benchmark(
    cumulative: pd.Series, benchmark_ret: pd.Series
) -> float:
    """Compounded relative excess vs benchmark."""
    strategy_total = float(cumulative.iloc[-1] - 1.0)
    bench_total = float((1.0 + benchmark_ret).prod() - 1.0)
    return (1.0 + strategy_total) / (1.0 + bench_total) - 1.0


def walk_forward_window(
    features: pd.DataFrame,
    returns: pd.Series,
    train_dates: pd.DatetimeIndex,
    test_dates: pd.DatetimeIndex,
    seed: int = 42,
) -> dict:
    """Train XGBoost ranker on train window, evaluate on test window."""
    import xgboost as xgb

    train_mask = features.index.get_level_values(0).isin(train_dates)
    test_mask = features.index.get_level_values(0).isin(test_dates)

    train_feat = features.loc[train_mask].copy()
    test_feat = features.loc[test_mask].copy()
    train_ret = returns.loc[train_mask]
    test_ret = returns.loc[test_mask]

    # Drop NaN rows
    train_feat = train_feat.dropna()
    test_feat = test_feat.dropna()
    train_ret = train_ret.reindex(train_feat.index)
    test_ret = test_ret.reindex(test_feat.index)

    # Percentile rank target with 7 gain bins
    train_rank = train_ret.groupby(level=0).rank(pct=True)
    train_target = np.floor(train_rank.clip(0, 1) * 7).clip(0, 6).astype(int)

    # Group sizes for rank:ndcg
    train_groups = train_feat.groupby(level=0).size().tolist()

    dtrain = xgb.DMatrix(train_feat.values, label=train_target.values)
    dtrain.set_group(train_groups)

    params = {
        "objective": "rank:ndcg",
        "tree_method": "hist",
        "grow_policy": "lossguide",
        "max_leaves": 31,
        "max_depth": 0,
        "learning_rate": 0.05,
        "seed": seed,
        "verbosity": 0,
    }
    model = xgb.train(params, dtrain, num_boost_round=200)

    dtest = xgb.DMatrix(test_feat.values)
    test_scores = pd.Series(model.predict(dtest), index=test_feat.index, name="score")

    rank_ic = compute_rank_ic(test_scores, test_ret)

    # Top-15 equally-weighted daily returns
    daily_returns = []
    for date in test_dates:
        if date not in test_scores.index.get_level_values(0):
            continue
        day_scores = test_scores.loc[date]
        top15 = day_scores.nlargest(15).index.get_level_values(1)
        day_ret = test_ret.loc[date].loc[top15].mean()
        daily_returns.append(day_ret)

    cumulative = (1.0 + pd.Series(daily_returns)).cumprod()
    return {"rank_ic": rank_ic, "cumulative": cumulative, "n_dates": len(daily_returns)}


def main():
    safe_qlib_init(build_qlib_init_cfg({}, market="us"))
    from qlib.data import D

    inst = D.instruments(market="us")

    # Load factor groups
    groups = load_factor_expressions(
        ["momentum_volatility_volume", "risk_controlled_momentum"]
    )
    # Combined = union of both groups
    combined_expr = list(
        dict.fromkeys(
            groups["momentum_volatility_volume"]
            + groups["risk_controlled_momentum"]
        )
    )

    configs = {
        "mv_volume (US x1.1 baseline)": groups["momentum_volatility_volume"],
        "risk_ctrl (US x1.0)": groups["risk_controlled_momentum"],
        "combined (9 factors)": combined_expr,
    }

    # Fetch data
    start = "2021-01-01"
    end = "2026-06-24"
    all_expr = list(dict.fromkeys(sum(configs.values(), [])))
    print(f"Loading {len(all_expr)} unique expressions ({start} to {end})...")
    t0 = time.time()
    features = D.features(inst, all_expr, start_time=start, end_time=end)
    returns = D.features(inst, ["Ref($close, -10)/$close - 1"], start_time=start, end_time=end)
    returns = returns.iloc[:, 0]
    print(f"Loaded {features.shape} in {time.time() - t0:.1f}s")

    # Walk-forward windows
    all_dates_raw = sorted(features.index.get_level_values(0).unique())
    all_dates = pd.DatetimeIndex(all_dates_raw)
    first_test = pd.Timestamp("2024-01-01")
    test_end = pd.Timestamp("2026-06-24")
    step_months = 6
    train_start = pd.Timestamp("2021-01-01")

    window_start = first_test
    results: dict[str, list] = {name: [] for name in configs}
    cumulative_returns: dict[str, pd.Series] = {}
    benchmark_rets: list[float] = []

    while window_start < test_end:
        window_end = min(window_start + pd.DateOffset(months=step_months), test_end)
        train_dates = pd.DatetimeIndex(
            [d for d in all_dates if train_start <= d < window_start]
        )
        test_dates = pd.DatetimeIndex(
            [d for d in all_dates if window_start <= d <= window_end]
        )

        # Benchmark: QQQ proxy (equal weight all US pool)
        test_mask = features.index.get_level_values(0).isin(test_dates)
        bench_ret = returns.loc[test_mask].groupby(level=0).mean()
        benchmark_rets.extend(bench_ret.values.tolist())

        print(f"\nWindow: {window_start.date()} -> {window_end.date()} "
              f"(train={len(train_dates)}, test={len(test_dates)})")

        for name, expressions in configs.items():
            subset = features[expressions]
            result = walk_forward_window(
                subset, returns, train_dates, test_dates, seed=42
            )
            results[name].append(
                {"window": str(window_start.date()), "rank_ic": result["rank_ic"]}
            )
            if name not in cumulative_returns:
                cumulative_returns[name] = result["cumulative"]
            else:
                cumulative_returns[name] = pd.concat(
                    [cumulative_returns[name], result["cumulative"]]
                )
            print(f"  {name}: rank_ic={result['rank_ic']:.4f}")

        window_start = window_end

    # Final comparison
    benchmark_cum = (1.0 + pd.Series(benchmark_rets)).cumprod()
    print(f"\n{'='*60}")
    print(f"Final Comparison (2024-01 -> 2026-06-24)")
    print(f"{'='*60}")
    for name in configs:
        cum = cumulative_returns[name]
        total = float(cum.iloc[-1] - 1.0)
        excess = compute_excess_vs_benchmark(cum, benchmark_rets)
        mean_ic = np.mean([r["rank_ic"] for r in results[name]])
        print(f"  {name}:")
        print(f"    Mean Rank IC: {mean_ic:.4f}")
        print(f"    Total Return: {total:.4%}")
        print(f"    Excess vs EW: {excess:.4%}")
        print(f"    Max DD: {float((cum/cum.cummax()-1).min()):.4%}")


if __name__ == "__main__":
    main()
