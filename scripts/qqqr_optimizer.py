"""QQQR v4.3 parameter optimization: 30 rounds across state weights, panic repair, defense.

Uses existing v4.3 formal backtest state trace. Tests alternative allocation weights,
panic repair boost amounts, and slow-bear defense splits with same 10bps cost structure.
"""
from __future__ import annotations

import json, math
from collections import defaultdict
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BACKTEST_PATH = Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json")
COST_BPS = 10.0  # Keep consistent with current v4.3
ASSETS = ["QQQI", "QQQ", "TQQQ", "SGOV"]

# ===== Rounds 1-10: State Allocation Weight Sweep =====
# Current: s0={QQQI:1.0}, s1={QQQI:0.5,QQQ:0.5}, s2={QQQ:0.25,TQQQ:0.75}
STATE_0_VARIANTS = [
    # (label, qqqi, qqq, tqqq, sgov)
    ("s0_qqqi100", 1.0, 0.0, 0.0, 0.0),   # Current baseline
    ("s0_qqqi50_sgov50", 0.5, 0.0, 0.0, 0.5),
    ("s0_qqqi75_sgov25", 0.75, 0.0, 0.0, 0.25),
    ("s0_qqqi60_qqq40", 0.6, 0.4, 0.0, 0.0),
]

STATE_1_VARIANTS = [
    # (label, qqqi, qqq, tqqq, sgov)
    ("s1_qqqi50_qqq50", 0.5, 0.5, 0.0, 0.0),  # Current
    ("s1_qqqi25_qqq75", 0.25, 0.75, 0.0, 0.0),
    ("s1_qqqi75_qqq25", 0.75, 0.25, 0.0, 0.0),
    ("s1_qqqi40_qqq40_tqqq20", 0.4, 0.4, 0.2, 0.0),
    ("s1_qqqi30_qqq50_tqqq20", 0.3, 0.5, 0.2, 0.0),
    ("s1_qqq100", 0.0, 1.0, 0.0, 0.0),
]

STATE_2_VARIANTS = [
    # (label, qqqi, qqq, tqqq, sgov)
    ("s2_qqq25_tqqq75", 0.0, 0.25, 0.75, 0.0),  # Current
    ("s2_tqqq100", 0.0, 0.0, 1.0, 0.0),
    ("s2_qqq50_tqqq50", 0.0, 0.5, 0.5, 0.0),
    ("s2_qqq30_tqqq70", 0.0, 0.3, 0.7, 0.0),
    ("s2_qqq20_tqqq80", 0.0, 0.2, 0.8, 0.0),
    ("s2_qqq10_tqqq90", 0.0, 0.1, 0.9, 0.0),
]

# ===== Rounds 11-18: Panic Repair Boost Sweep =====
PANIC_REPAIR_VARIANTS = [
    # (label, tqqq_boost)
    ("panic_boost_0", 0.0),
    ("panic_boost_10", 0.10),
    ("panic_boost_15", 0.15),
    ("panic_boost_20", 0.20),
    ("panic_boost_25", 0.25),    # Current
    ("panic_boost_30", 0.30),
    ("panic_boost_35", 0.35),
    ("panic_boost_40", 0.40),
]

# ===== Rounds 19-25: Slow Bear Defense Split Sweep =====
DEFENSE_SPLIT_VARIANTS = [
    # (label, qqqi_pct, sgov_pct)
    ("def_qqqi50_sgov50", 0.5, 0.5),   # Current
    ("def_qqqi25_sgov75", 0.25, 0.75),
    ("def_qqqi75_sgov25", 0.75, 0.25),
    ("def_qqqi100_sgov0", 1.0, 0.0),
    ("def_qqqi0_sgov100", 0.0, 1.0),
    ("def_qqqi40_sgov60", 0.4, 0.6),
    ("def_qqqi60_sgov40", 0.6, 0.4),
]

# ===== Rounds 26-30: Combined Best Variants =====
# Built dynamically after evaluating rounds 1-25


def load_v43_data():
    """Load v4.3 formal backtest daily report with reconstructed asset returns."""
    d = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"])
    report["date"] = pd.to_datetime(report["date"])

    # Extract individual asset returns from weighted gross_return
    # We have: gross_return = w_QQQ*r_QQQ + w_QQQI*r_QQQI + w_TQQQ*r_TQQQ + w_SGOV*r_SGOV
    # We need to solve for r_QQQ, r_QQQI, r_TQQQ, r_SGOV
    # Since SGOV weight is almost always 0 in this dataset, we can't identify r_SGOV
    # For SGOV, assume ~0% daily return (money market)

    # Better approach: use benchmark returns for QQQ, and solve the system
    # But simpler: reconstruct from the per-asset weights and daily changes

    # Actually, let's use a simpler approach:
    # We know the weights each day and the total gross_return
    # We can't uniquely decompose without individual asset returns
    # Instead, let's use the actual ETF price data from the positions

    positions = pd.DataFrame(d["positions"])
    positions["date"] = pd.to_datetime(positions["date"])

    # Compute daily returns per instrument from position prices
    asset_returns = {}
    for asset in ["QQQI", "QQQ", "TQQQ"]:
        asset_pos = positions[positions["instrument"] == asset].set_index("date")["price"]
        asset_returns[asset] = asset_pos.pct_change().fillna(0.0)

    # SGOV: approximate as 0 (money market)
    asset_returns["SGOV"] = pd.Series(0.0, index=asset_returns["QQQ"].index)

    # Build unified returns DataFrame
    returns_df = pd.DataFrame(asset_returns)
    returns_df = returns_df.reindex(report["date"]).fillna(0.0)

    return report, returns_df, d["portfolio_contract"]


def compute_strategy(report, returns_df, state_weights, panic_boost, defense_split):
    """Compute strategy returns with given allocation parameters.

    state_weights: dict state->{asset: weight}
    panic_boost: float (TQQQ boost during panic repair)
    defense_split: (qqqi_pct, sgov_pct) for slow bear defense
    """
    daily = report[["date", "position_state", "panic_repair_active",
                     "slow_bear_defense_active", "bench_qqq", "drawdown"]].copy()
    daily = daily.set_index("date")

    # Build weight matrix
    weights = pd.DataFrame(0.0, index=daily.index, columns=ASSETS)
    n = len(daily)

    for i in range(n):
        state = int(daily["position_state"].iloc[i])
        ws = state_weights.get(state, state_weights.get(0, {"QQQI": 1.0}))

        for asset in ASSETS:
            weights.iloc[i, weights.columns.get_loc(asset)] = ws.get(asset, 0.0)

        # Apply panic repair boost
        if daily["panic_repair_active"].iloc[i] and panic_boost > 0:
            # Boost TQQQ from QQQI allocation in states 0 and 1
            if state in (0, 1):
                current_tqqq = ws.get("TQQQ", 0.0)
                current_qqqi = ws.get("QQQI", 0.0)
                boost_amount = min(panic_boost, current_qqqi)
                weights.iloc[i, weights.columns.get_loc("TQQQ")] = current_tqqq + boost_amount
                weights.iloc[i, weights.columns.get_loc("QQQI")] = current_qqqi - boost_amount

        # Apply slow bear defense
        if daily["slow_bear_defense_active"].iloc[i]:
            qqqi_pct, sgov_pct = defense_split
            weights.iloc[i, weights.columns.get_loc("QQQI")] = qqqi_pct
            weights.iloc[i, weights.columns.get_loc("SGOV")] = sgov_pct
            for asset in ["QQQ", "TQQQ"]:
                weights.iloc[i, weights.columns.get_loc(asset)] = 0.0

    # Compute gross returns
    aligned_returns = returns_df.reindex(daily.index).fillna(0.0)
    gross_returns = (weights.values * aligned_returns.values).sum(axis=1)

    # Compute turnover from weight changes
    weight_changes = weights.diff().abs().sum(axis=1)
    weight_changes.iloc[0] = weights.iloc[0].abs().sum()  # Initial entry
    transaction_costs = weight_changes * COST_BPS / 10000.0
    net_returns = gross_returns - transaction_costs.values

    # Compute metrics
    equity = (1.0 + pd.Series(net_returns, index=daily.index)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    max_dd = float(drawdown.min())

    total_return = float(equity.iloc[-1] - 1.0)
    n_days = len(daily)
    cagr = float((equity.iloc[-1]) ** (252.0 / max(n_days, 1)) - 1.0)
    annual_vol = float(pd.Series(net_returns).std() * np.sqrt(252))
    sharpe = float(cagr / annual_vol) if annual_vol > 0 else 0.0
    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else 0.0

    # Benchmark (QQQ buy-and-hold)
    bench_return = float(daily["bench_qqq"].iloc[-1] / daily["bench_qqq"].iloc[0] - 1.0) if len(daily) > 0 else 0.0
    excess = total_return - bench_return

    total_turnover = float(weight_changes.sum())
    total_cost = float(transaction_costs.sum())

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "annual_vol": annual_vol,
        "benchmark_return": bench_return,
        "excess_return": excess,
        "total_turnover": total_turnover,
        "total_cost": total_cost,
        "n_days": n_days,
        "net_returns": net_returns,
    }


def run_all_rounds():
    print("Loading v4.3 formal backtest data...")
    report, returns_df, contract = load_v43_data()
    print(f"Loaded {len(report)} daily records, {len(returns_df)} return dates")
    print(f"Date range: {report['date'].min()} to {report['date'].max()}")

    # Current baseline weights
    base_weights = {
        0: {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
        1: {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
        2: {"QQQ": 0.25, "QQQI": 0.0, "TQQQ": 0.75, "SGOV": 0.0},
    }

    # Baseline
    baseline = compute_strategy(report, returns_df, base_weights, 0.25, (0.5, 0.5))
    print(f"\nBaseline v4.3 (reconstructed):")
    print(f"  Total Return: {baseline['total_return']:.4f}")
    print(f"  CAGR: {baseline['cagr']:.4f}")
    print(f"  Max DD: {baseline['max_drawdown']:.4f}")
    print(f"  Calmar: {baseline['calmar']:.4f}")
    print(f"  Sharpe: {baseline['sharpe']:.4f}")
    print(f"  Excess vs QQQ: {baseline['excess_return']:.4f}")
    print(f"  Total Cost: {baseline['total_cost']:.4f}")
    print(f"  Turnover: {baseline['total_turnover']:.2f}")

    all_results = [{"round": 0, "label": "baseline_v4_3", **{k: v for k, v in baseline.items() if k != 'net_returns'}}]

    # ===== Rounds 1-10: State Weight Sweep =====
    print(f"\n{'='*60}")
    print("R1-10: State Allocation Weight Sweep")

    round_num = 0
    for s0_label, s0_qqqi, s0_qqq, s0_tqqq, s0_sgov in STATE_0_VARIANTS:
        for s1_label, s1_qqqi, s1_qqq, s1_tqqq, s1_sgov in STATE_1_VARIANTS:
            for s2_label, s2_qqqi, s2_qqq, s2_tqqq, s2_sgov in STATE_2_VARIANTS:
                if round_num >= 10:
                    break
                if s0_label == "s0_qqqi100" and s1_label == "s1_qqqi50_qqq50" and s2_label == "s2_qqq25_tqqq75":
                    continue  # Skip baseline (already tested)

                weights = {
                    0: {"QQQI": s0_qqqi, "QQQ": s0_qqq, "TQQQ": s0_tqqq, "SGOV": s0_sgov},
                    1: {"QQQI": s1_qqqi, "QQQ": s1_qqq, "TQQQ": s1_tqqq, "SGOV": s1_sgov},
                    2: {"QQQI": s2_qqqi, "QQQ": s2_qqq, "TQQQ": s2_tqqq, "SGOV": s2_sgov},
                }
                result = compute_strategy(report, returns_df, weights, 0.25, (0.5, 0.5))
                label = f"R{round_num+1}_{s0_label}_{s1_label}_{s2_label}"
                all_results.append({"round": round_num + 1, "label": label, **{k: v for k, v in result.items() if k != 'net_returns'}})
                round_num += 1

    # ===== Rounds 11-18: Panic Repair Boost Sweep =====
    print(f"\n{'='*60}")
    print("R11-18: Panic Repair Boost Sweep")

    for i, (panic_label, boost) in enumerate(PANIC_REPAIR_VARIANTS):
        result = compute_strategy(report, returns_df, base_weights, boost, (0.5, 0.5))
        label = f"R{11+i}_{panic_label}"
        all_results.append({"round": 11 + i, "label": label, **{k: v for k, v in result.items() if k != 'net_returns'}})

    # ===== Rounds 19-25: Defense Split Sweep =====
    print(f"\n{'='*60}")
    print("R19-25: Slow Bear Defense Split Sweep")

    for i, (def_label, qqqi_pct, sgov_pct) in enumerate(DEFENSE_SPLIT_VARIANTS):
        result = compute_strategy(report, returns_df, base_weights, 0.25, (qqqi_pct, sgov_pct))
        label = f"R{19+i}_{def_label}"
        all_results.append({"round": 19 + i, "label": label, **{k: v for k, v in result.items() if k != 'net_returns'}})

    # ===== Rounds 26-30: Combined Best =====
    print(f"\n{'='*60}")
    print("R26-30: Combined Best Configurations")

    # Find best state weights, best panic boost, best defense from earlier rounds
    r1_10 = [r for r in all_results if 1 <= r["round"] <= 10]
    r11_18 = [r for r in all_results if 11 <= r["round"] <= 18]
    r19_25 = [r for r in all_results if 19 <= r["round"] <= 25]

    best_state = max(r1_10, key=lambda r: r["calmar"])
    best_panic = max(r11_18, key=lambda r: r["calmar"])
    best_defense = max(r19_25, key=lambda r: r["calmar"])

    print(f"Best state weights: {best_state['label']} (Calmar={best_state['calmar']:.4f})")
    print(f"Best panic boost: {best_panic['label']} (Calmar={best_panic['calmar']:.4f})")
    print(f"Best defense: {best_defense['label']} (Calmar={best_defense['calmar']:.4f})")

    # Parse best state weights from label
    def parse_state_weights(label):
        """Parse R{N}_{s0_...}_{s1_...}_{s2_...} back to weight dict"""
        parts = label.split("_")
        weights = {}
        # Simple fallback: use optimal from list
        for s0_l, s0_q, s0_qq, s0_t, s0_s in STATE_0_VARIANTS:
            if s0_l in label:
                weights[0] = {"QQQI": s0_q, "QQQ": s0_qq, "TQQQ": s0_t, "SGOV": s0_s}
                break
        for s1_l, s1_q, s1_qq, s1_t, s1_s in STATE_1_VARIANTS:
            if s1_l in label:
                weights[1] = {"QQQI": s1_q, "QQQ": s1_qq, "TQQQ": s1_t, "SGOV": s1_s}
                break
        for s2_l, s2_q, s2_qq, s2_t, s2_s in STATE_2_VARIANTS:
            if s2_l in label:
                weights[2] = {"QQQI": s2_q, "QQQ": s2_qq, "TQQQ": s2_t, "SGOV": s2_s}
                break
        return weights if len(weights) == 3 else base_weights

    # Build combinations
    combo_weights = parse_state_weights(best_state["label"])
    combo_panic = float(best_panic["label"].split("boost_")[1]) if "boost_" in best_panic["label"] else 0.25
    combo_def = (0.5, 0.5)
    for def_l, def_q, def_s in DEFENSE_SPLIT_VARIANTS:
        if def_l in best_defense["label"]:
            combo_def = (def_q, def_s)
            break

    combined_configs = [
        ("R26_best_all", combo_weights, combo_panic, combo_def),
        ("R27_best_weights_only", combo_weights, 0.25, (0.5, 0.5)),
        ("R28_best_panic_only", base_weights, combo_panic, (0.5, 0.5)),
        ("R29_best_defense_only", base_weights, 0.25, combo_def),
    ]

    # R30: Test with higher TQQQ in state 2
    r30_weights = dict(base_weights)
    r30_weights[2] = {"QQQ": 0.1, "QQQI": 0.0, "TQQQ": 0.9, "SGOV": 0.0}
    combined_configs.append(("R30_max_tqqq_s2", r30_weights, combo_panic, combo_def))

    for r_label, weights, panic, defense in combined_configs:
        result = compute_strategy(report, returns_df, weights, panic, defense)
        all_results.append({"round": int(r_label[1:3]) if r_label[1:3].isdigit() else 26,
                           "label": r_label, **{k: v for k, v in result.items() if k != 'net_returns'}})

    # ===== Final Summary =====
    print(f"\n{'='*60}")
    print("FINAL SUMMARY: All 30+ Rounds Sorted by Calmar Ratio")
    print(f"{'Round':<6} {'Label':<55s} {'TotalRet':>8s} {'CAGR':>8s} {'MaxDD':>8s} {'Calmar':>8s} {'Sharpe':>8s} {'Excess':>8s} {'Cost':>8s}")
    print("-" * 135)

    # Filter out net_returns for display
    display_results = [{k: v for k, v in r.items() if k != 'net_returns'} for r in all_results]
    display_results.sort(key=lambda r: r["calmar"], reverse=True)

    for r in display_results:
        print(f"{r['round']:<6} {r['label']:<55s} {r['total_return']:>8.4f} {r['cagr']:>8.4f} {r['max_drawdown']:>8.4f} {r['calmar']:>8.4f} {r['sharpe']:>8.4f} {r['excess_return']:>8.4f} {r['total_cost']:>8.4f}")

    # Best by category
    best_calmar = max(display_results, key=lambda r: r["calmar"])
    best_cagr = max(display_results, key=lambda r: r["cagr"])
    best_dd = max(display_results, key=lambda r: r["max_drawdown"])  # least negative
    best_sharpe = max(display_results, key=lambda r: r["sharpe"])

    print(f"\nBest by category:")
    print(f"  Calmar: R{best_calmar['round']} {best_calmar['label']} = {best_calmar['calmar']:.4f} (CAGR={best_calmar['cagr']:.4f}, DD={best_calmar['max_drawdown']:.4f})")
    print(f"  CAGR:   R{best_cagr['round']} {best_cagr['label']} = {best_cagr['cagr']:.4f} (DD={best_cagr['max_drawdown']:.4f})")
    print(f"  MaxDD:  R{best_dd['round']} {best_dd['label']} = {best_dd['max_drawdown']:.4f} (CAGR={best_dd['cagr']:.4f})")
    print(f"  Sharpe: R{best_sharpe['round']} {best_sharpe['label']} = {best_sharpe['sharpe']:.4f}")

    # Cost comparison
    baseline_cost = next(r for r in display_results if r["round"] == 0)
    print(f"\nBaseline v4.3 cost: {baseline_cost['total_cost']:.4f}, turnover: {baseline_cost['total_turnover']:.2f}")
    high_cost = max(display_results, key=lambda r: r["total_cost"])
    print(f"Highest cost config: R{high_cost['round']} {high_cost['label']} = {high_cost['total_cost']:.4f}")

    # Save
    output = {
        "experiment_id": "qqqr_30_round_optimization_v1",
        "baseline_v4_3": baseline_cost,
        "cost_bps": COST_BPS,
        "all_results": display_results,
        "best_calmar": {"round": best_calmar["round"], "label": best_calmar["label"], "calmar": best_calmar["calmar"], "cagr": best_calmar["cagr"], "max_dd": best_calmar["max_drawdown"]},
        "best_cagr": {"round": best_cagr["round"], "label": best_cagr["label"], "cagr": best_cagr["cagr"], "max_dd": best_cagr["max_drawdown"]},
    }
    out_path = Path("artifacts/evidence/qqqr_30_round_optimization_v1/results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {out_path}")

    return output


if __name__ == "__main__":
    run_all_rounds()
