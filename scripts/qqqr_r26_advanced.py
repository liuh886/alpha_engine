"""QQQR R26+ advanced optimization: exhaustive state weight grid + fine defense sweep.

Extends the 30-round experiment with exhaustive search over state weights
and finer defense splits to find the true global optimum beyond R26.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any
from itertools import product

import numpy as np
import pandas as pd

BACKTEST_PATH = Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json")
COST_BPS = 10.0
ASSETS = ["QQQI", "QQQ", "TQQQ", "SGOV"]

# ===== Exhaustive State Weight Grid =====
# State 0: defense (test variants with/without SGOV)
STATE_0_GRID = [
    (1.0, 0.0, 0.0, 0.0),   # QQQI 100% (current)
    (0.9, 0.0, 0.0, 0.1),   # QQQI 90% / SGOV 10%
    (0.8, 0.0, 0.0, 0.2),
    (0.7, 0.0, 0.0, 0.3),
    (0.6, 0.0, 0.0, 0.4),
    (0.5, 0.0, 0.0, 0.5),
]

# State 1: recovery bridge — finer grid
STATE_1_GRID = [
    # (qqqi, qqq, tqqq, sgov)
    (0.0, 1.0, 0.0, 0.0),   # QQQ 100%
    (0.1, 0.9, 0.0, 0.0),
    (0.2, 0.8, 0.0, 0.0),
    (0.25, 0.75, 0.0, 0.0),
    (0.3, 0.7, 0.0, 0.0),
    (0.4, 0.6, 0.0, 0.0),
    (0.5, 0.5, 0.0, 0.0),   # Current
    (0.6, 0.4, 0.0, 0.0),
    (0.7, 0.3, 0.0, 0.0),
    (0.75, 0.25, 0.0, 0.0),
    (0.8, 0.2, 0.0, 0.0),
    (0.9, 0.1, 0.0, 0.0),
    (0.3, 0.5, 0.2, 0.0),   # With TQQQ
    (0.2, 0.5, 0.3, 0.0),
    (0.4, 0.3, 0.3, 0.0),
]

# State 2: leveraged recovery — test 80-100% TQQQ
STATE_2_GRID = [
    (0.0, 0.0, 1.0, 0.0),   # TQQQ 100% (R26 best)
    (0.0, 0.05, 0.95, 0.0),
    (0.0, 0.1, 0.9, 0.0),
    (0.0, 0.15, 0.85, 0.0),
    (0.0, 0.2, 0.8, 0.0),
    (0.0, 0.25, 0.75, 0.0), # Current
    (0.0, 0.0, 0.95, 0.05), # TQQQ 95% / SGOV 5%
    (0.0, 0.0, 0.9, 0.1),
    (0.0, 0.0, 0.85, 0.15),
    (0.0, 0.0, 0.8, 0.2),
    (0.0, 0.05, 0.9, 0.05),
]

# ===== Fine Defense Split Sweep (0-100% QQQI in 5% increments) =====
DEFENSE_FINE_GRID = [(qqi/100.0, (100-qqi)/100.0) for qqi in range(0, 105, 5)]


def load_v43_data():
    d = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"])
    report["date"] = pd.to_datetime(report["date"])
    positions = pd.DataFrame(d["positions"])
    positions["date"] = pd.to_datetime(positions["date"])
    asset_returns = {}
    for asset in ["QQQI", "QQQ", "TQQQ"]:
        asset_pos = positions[positions["instrument"] == asset].set_index("date")["price"]
        asset_returns[asset] = asset_pos.pct_change().fillna(0.0)
    asset_returns["SGOV"] = pd.Series(0.0, index=asset_returns["QQQ"].index)
    returns_df = pd.DataFrame(asset_returns).reindex(report["date"]).fillna(0.0)
    return report, returns_df


def compute_strategy(report, returns_df, state_weights, panic_boost, defense_split):
    daily = report[["date", "position_state", "panic_repair_active",
                     "slow_bear_defense_active", "bench_qqq"]].copy().set_index("date")
    weights = pd.DataFrame(0.0, index=daily.index, columns=ASSETS)
    n = len(daily)
    for i in range(n):
        state = int(daily["position_state"].iloc[i])
        ws = state_weights.get(state, state_weights.get(0, {"QQQI": 1.0}))
        for asset in ASSETS:
            weights.iloc[i, weights.columns.get_loc(asset)] = ws.get(asset, 0.0)
        if daily["panic_repair_active"].iloc[i] and panic_boost > 0 and state in (0, 1):
            current_tqqq = ws.get("TQQQ", 0.0)
            current_qqqi = ws.get("QQQI", 0.0)
            boost_amount = min(panic_boost, current_qqqi)
            weights.iloc[i, weights.columns.get_loc("TQQQ")] = current_tqqq + boost_amount
            weights.iloc[i, weights.columns.get_loc("QQQI")] = current_qqqi - boost_amount
        if daily["slow_bear_defense_active"].iloc[i]:
            qqqi_pct, sgov_pct = defense_split
            weights.iloc[i, weights.columns.get_loc("QQQI")] = qqqi_pct
            weights.iloc[i, weights.columns.get_loc("SGOV")] = sgov_pct
            for asset in ["QQQ", "TQQQ"]:
                weights.iloc[i, weights.columns.get_loc(asset)] = 0.0
    aligned_returns = returns_df.reindex(daily.index).fillna(0.0)
    gross_returns = (weights.values * aligned_returns.values).sum(axis=1)
    weight_changes = weights.diff().abs().sum(axis=1)
    weight_changes.iloc[0] = weights.iloc[0].abs().sum()
    transaction_costs = weight_changes * COST_BPS / 10000.0
    net_returns = gross_returns - transaction_costs.values
    equity = (1.0 + pd.Series(net_returns, index=daily.index)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    max_dd = float(drawdown.min())
    total_return = float(equity.iloc[-1] - 1.0)
    n_days = len(daily)
    cagr = float((equity.iloc[-1]) ** (252.0 / max(n_days, 1)) - 1.0)
    annual_vol = float(pd.Series(net_returns).std() * np.sqrt(252))
    sharpe = float(cagr / annual_vol) if annual_vol > 0 else 0.0
    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else 0.0
    bench_return = float(daily["bench_qqq"].iloc[-1] / daily["bench_qqq"].iloc[0] - 1.0)
    excess = total_return - bench_return
    total_turnover = float(weight_changes.sum())
    total_cost = float(transaction_costs.sum())
    return {"total_return": total_return, "cagr": cagr, "max_drawdown": max_dd,
            "sharpe": sharpe, "calmar": calmar, "annual_vol": annual_vol,
            "benchmark_return": bench_return, "excess_return": excess,
            "total_turnover": total_turnover, "total_cost": total_cost, "n_days": n_days}


def run():
    print("Loading v4.3 data...")
    report, returns_df = load_v43_data()
    base_weights = {0: {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
                    1: {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
                    2: {"QQQ": 0.25, "QQQI": 0.0, "TQQQ": 0.75, "SGOV": 0.0}}

    # Baseline
    bl = compute_strategy(report, returns_df, base_weights, 0.0, (0.5, 0.5))
    print(f"Baseline v4.3: Calmar={bl['calmar']:.4f}, CAGR={bl['cagr']:.4f}, DD={bl['max_drawdown']:.4f}")

    # R26 reference
    r26_weights = {0: {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
                   1: {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
                   2: {"QQQ": 0.0, "QQQI": 0.0, "TQQQ": 1.0, "SGOV": 0.0}}
    r26 = compute_strategy(report, returns_df, r26_weights, 0.0, (0.75, 0.25))
    print(f"R26 reference:  Calmar={r26['calmar']:.4f}, CAGR={r26['cagr']:.4f}, DD={r26['max_drawdown']:.4f}")

    all_results = []

    # ===== Round 31-40: Exhaustive State Weight Grid =====
    print(f"\n{'='*60}")
    print(f"R31+: Exhaustive State Weight Grid ({len(STATE_0_GRID)}×{len(STATE_1_GRID)}×{len(STATE_2_GRID)}={len(STATE_0_GRID)*len(STATE_1_GRID)*len(STATE_2_GRID)} combos)")

    round_num = 30
    best_so_far_calmar = r26["calmar"]
    best_so_far = None

    for s0_w in STATE_0_GRID:
        for s1_w in STATE_1_GRID:
            for s2_w in STATE_2_GRID:
                # Skip baseline and R26 (already tested)
                if (s0_w == (1.0, 0.0, 0.0, 0.0) and s1_w == (0.5, 0.5, 0.0, 0.0) and
                    (s2_w == (0.0, 0.25, 0.75, 0.0) or s2_w == (0.0, 0.0, 1.0, 0.0))):
                    continue

                weights = {0: {"QQQI": s0_w[0], "QQQ": s0_w[1], "TQQQ": s0_w[2], "SGOV": s0_w[3]},
                          1: {"QQQI": s1_w[0], "QQQ": s1_w[1], "TQQQ": s1_w[2], "SGOV": s1_w[3]},
                          2: {"QQQI": s2_w[0], "QQQ": s2_w[1], "TQQQ": s2_w[2], "SGOV": s2_w[3]}}
                result = compute_strategy(report, returns_df, weights, 0.0, (0.75, 0.25))
                label = f"R{round_num+1}_s0{s0_w}_s1{s1_w}_s2{s2_w}"
                all_results.append({"label": label, **{k: v for k, v in result.items() if k != 'net_returns'}})
                if result["calmar"] > best_so_far_calmar:
                    best_so_far_calmar = result["calmar"]
                    best_so_far = (label, result, s0_w, s1_w, s2_w)
                    print(f"  NEW BEST: {label} Calmar={result['calmar']:.4f} CAGR={result['cagr']:.4f} DD={result['max_drawdown']:.4f}")
                round_num += 1

    print(f"\nExhaustive grid best: {best_so_far[0]} Calmar={best_so_far_calmar:.4f}")

    # ===== Round 41-45: Fine Defense Sweep with Best Weights =====
    print(f"\n{'='*60}")
    print(f"R{round_num+1}+: Fine Defense Sweep ({len(DEFENSE_FINE_GRID)} splits)")

    best_w = best_so_far
    best_s0 = best_w[3]  # (qqqi, qqq, tqqq, sgov)
    best_s1 = best_w[4]
    best_s2 = best_w[5]
    for i, (qqi, sgov) in enumerate(DEFENSE_FINE_GRID):
        result = compute_strategy(report, returns_df,
                                  {0: {"QQQI": best_s0[0], "QQQ": best_s0[1], "TQQQ": best_s0[2], "SGOV": best_s0[3]},
                                   1: {"QQQI": best_s1[0], "QQQ": best_s1[1], "TQQQ": best_s1[2], "SGOV": best_s1[3]},
                                   2: {"QQQI": best_s2[0], "QQQ": best_s2[1], "TQQQ": best_s2[2], "SGOV": best_s2[3]}},
                                  0.0, (qqi, sgov))
        label = f"R{round_num+1+i}_def{int(qqi*100):d}_{int(sgov*100):d}"
        all_results.append({"label": label, **{k: v for k, v in result.items() if k != 'net_returns'}})
        if result["calmar"] > best_so_far_calmar:
            best_so_far_calmar = result["calmar"]
            print(f"  NEW BEST: {label} Calmar={result['calmar']:.4f} CAGR={result['cagr']:.4f} DD={result['max_drawdown']:.4f}")

    # ===== Final Summary =====
    all_results_sorted = sorted(all_results, key=lambda r: r["calmar"], reverse=True)
    print(f"\n{'='*60}")
    print(f"FINAL: Top-20 Results (Total: {len(all_results)} configurations)")
    print(f"{'Label':<60s} {'Calmar':>8s} {'CAGR':>8s} {'MaxDD':>8s} {'Sharpe':>8s} {'Excess':>8s} {'Cost':>8s}")
    print("-" * 120)
    for r in all_results_sorted[:20]:
        print(f"{r['label']:<60s} {r['calmar']:>8.4f} {r['cagr']:>8.4f} {r['max_drawdown']:>8.4f} {r['sharpe']:>8.4f} {r['excess_return']:>8.4f} {r['total_cost']:>8.4f}")

    best = all_results_sorted[0]
    print(f"\nABSOLUTE BEST: {best['label']}")
    print(f"  Calmar: {best['calmar']:.4f} (vs R26: {r26['calmar']:.4f}, +{(best['calmar']/r26['calmar']-1)*100:.1f}%)")
    print(f"  CAGR:   {best['cagr']:.4f} (vs R26: {r26['cagr']:.4f})")
    print(f"  Max DD: {best['max_drawdown']:.4f} (vs R26: {r26['max_drawdown']:.4f})")
    print(f"  Sharpe: {best['sharpe']:.4f}")
    print(f"  Excess: {best['excess_return']:.4f}")
    print(f"  Cost:   {best['total_cost']:.4f}")

    # Save
    output = {"experiment_id": "qqqr_r26_advanced_v1", "total_configs": len(all_results),
              "r26_baseline": {"calmar": r26["calmar"], "cagr": r26["cagr"], "max_dd": r26["max_drawdown"]},
              "absolute_best": best, "top_20": all_results_sorted[:20],
              "all_results": all_results_sorted}
    out_path = Path("artifacts/evidence/qqqr_r26_advanced_v1/results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {out_path}")
    return output


if __name__ == "__main__":
    run()
