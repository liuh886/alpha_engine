"""BYD v1.2 30-round optimization: allocation weights + convex momentum parameters.

Uses v1.2 formal backtest daily data. Tests defense/offense/expansion weight variants,
convex momentum budget parameters, and combined best configurations.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BACKTEST_PATH = Path("data/research/formal_backtests/byd_v1_2_convex_momentum_budget_v1.json")
COST_BPS = 20.0
STRESS_COST_BPS = 40.0

# ===== Rounds 1-10: Allocation Weight Sweep =====
DEFENSE_BYD_PCTS = [0.0, 0.25, 0.50, 0.625, 0.75, 0.875, 1.0]
OFFENSE_BYD_PCTS = [0.75, 0.875, 1.0, 1.125]
EXPANSION_MAX_PCTS = [1.0, 1.125, 1.25, 1.5]

# ===== Rounds 11-18: Convex Momentum Parameter Sweep =====
FULL_INCREMENT_MOMENTUMS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
CONVEX_POWERS = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
MAX_FINANCED_INCREMENTS = [0.05, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30, 0.50]

# ===== Rounds 19-25: Momentum Threshold Sweep =====
# Current: entry when mom_20 > 0, exit when mom_20 <= 0
MOM_ENTRY_THRESHOLDS = [-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10]
MOM_EXIT_THRESHOLDS = [-0.10, -0.05, -0.02, 0.0, 0.02, 0.05]


def load_data():
    d = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))
    report = pd.DataFrame(d["report"])
    report["date"] = pd.to_datetime(report["date"])
    # Reconstruct individual asset returns from weights and gross_return
    # gross_return = w_BYD * r_BYD + w_515180 * r_515180 + w_cash * 0
    # We can solve for r_BYD from days where w_515180=0 and w_cash=0 (pure BYD days)
    # And r_515180 from days with only 515180
    # But simpler: use positions data to get individual prices
    positions = pd.DataFrame(d["positions"])
    positions["date"] = pd.to_datetime(positions["date"])

    # Get BYD price series
    byd_pos = positions[positions["instrument"] == "BYD"].set_index("date")["price"]
    etf_pos = positions[positions["instrument"] == "515180.SH"].set_index("date")["price"]

    byd_returns = byd_pos.pct_change().fillna(0.0)
    etf_returns = etf_pos.pct_change().fillna(0.0)

    returns_df = pd.DataFrame({"BYD": byd_returns, "515180": etf_returns})
    returns_df = returns_df.reindex(report["date"]).fillna(0.0)

    return report, returns_df, d["portfolio_contract"]


def compute_momentum_scale(momentum_20, full_increment_momentum, convex_power, max_financed_increment):
    """Compute the convex momentum budget scale factor."""
    if momentum_20 <= 0:
        return 0.0, 0.0
    scale = min(1.0, momentum_20 / full_increment_momentum) ** convex_power
    increment = scale * max_financed_increment
    return scale, increment


def compute_by_weights(report, returns_df, defense_byd, offense_byd, expansion_max,
                       full_inc_mom, convex_power, max_financed_inc, cost_bps):
    """Compute strategy returns with given BYD allocation parameters."""
    daily = report[["date", "momentum_20", "momentum_scale", "benchmark_return"]].copy().set_index("date")

    weights_byd = []
    weights_etf = []
    weights_cash = []

    for i in range(len(daily)):
        mom20 = float(daily["momentum_20"].iloc[i])
        scale, increment = compute_momentum_scale(
            max(0.0, mom20), full_inc_mom, convex_power, max_financed_inc
        )

        # Simple state logic based on momentum
        if mom20 > 0:
            # Offense or expansion
            total_byd = min(offense_byd + increment, expansion_max)
            w_byd = total_byd
            w_etf = 0.0
            w_cash = 1.0 - total_byd  # negative cash = margin
        else:
            # Defense
            w_byd = defense_byd
            w_etf = 1.0 - defense_byd
            w_cash = 0.0

        weights_byd.append(w_byd)
        weights_etf.append(w_etf)
        weights_cash.append(w_cash)

    weights_df = pd.DataFrame({
        "BYD": weights_byd, "515180": weights_etf, "cash": weights_cash
    }, index=daily.index)

    # Compute returns
    aligned = returns_df.reindex(daily.index).fillna(0.0)
    gross_returns = (weights_df["BYD"].values * aligned["BYD"].values +
                     weights_df["515180"].values * aligned["515180"].values)

    # Transaction costs
    weight_changes = pd.DataFrame({
        "BYD": abs(weights_df["BYD"].diff().fillna(0)),
        "515180": abs(weights_df["515180"].diff().fillna(0)),
    }).sum(axis=1)
    weight_changes.iloc[0] = abs(weights_df["BYD"].iloc[0]) + abs(weights_df["515180"].iloc[0])
    transaction_costs = weight_changes * cost_bps / 10000.0

    # Financing cost for margin
    financed = np.maximum(weights_df["BYD"].values - 1.0, 0.0)
    financing_cost = financed * 0.06 / 252.0  # annual 6% daily

    net_returns = gross_returns - transaction_costs.values - financing_cost

    # Metrics
    equity = (1.0 + pd.Series(net_returns, index=daily.index)).cumprod()
    max_dd = float((equity / equity.cummax() - 1.0).min())

    total_return = float(equity.iloc[-1] - 1.0)
    n_days = len(daily)
    n_years = n_days / 252.0
    cagr = float(equity.iloc[-1] ** (1.0 / max(n_years, 0.01)) - 1.0)
    annual_vol = float(pd.Series(net_returns).std() * np.sqrt(252))
    sharpe = float(cagr / annual_vol) if annual_vol > 0 else 0.0
    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else 0.0

    bench_return = float(daily["benchmark_return"].iloc[-1])
    excess = total_return - bench_return

    total_turnover = float(weight_changes.sum())
    total_cost = float(transaction_costs.sum()) + float(financing_cost.sum())

    return {
        "total_return": total_return, "cagr": cagr, "max_drawdown": max_dd,
        "sharpe": sharpe, "calmar": calmar, "annual_vol": annual_vol,
        "benchmark_return": bench_return, "excess_return": excess,
        "total_turnover": total_turnover, "total_cost": total_cost,
        "total_financing": float(financing_cost.sum()), "n_days": n_days, "n_years": n_years,
    }


def run():
    print("Loading BYD v1.2 data...")
    report, returns_df, contract = load_data()
    print(f"Records: {len(report)}, Date range: {report['date'].min()} to {report['date'].max()}")

    # Baseline
    bl = compute_by_weights(report, returns_df, 0.75, 1.0, 1.125, 0.15, 4.0, 0.125, COST_BPS)
    print(f"\nBaseline v1.2: Calmar={bl['calmar']:.4f}, CAGR={bl['cagr']:.4f}, DD={bl['max_drawdown']:.4f}, Sharpe={bl['sharpe']:.4f}")
    print(f"  Total Ret={bl['total_return']:.4f}, Excess={bl['excess_return']:.4f}, Cost={bl['total_cost']:.4f}, Fin={bl['total_financing']:.4f}")

    all_results = [{"round": 0, "label": "byd_v1_2_baseline", **bl}]

    # ===== R1-10: Allocation Weights =====
    print(f"\n{'='*60}")
    print(f"R1-10: Allocation Weight Sweep ({len(DEFENSE_BYD_PCTS)}×{len(OFFENSE_BYD_PCTS)}={len(DEFENSE_BYD_PCTS)*len(OFFENSE_BYD_PCTS)} combos)")

    rn = 0
    for def_byd in DEFENSE_BYD_PCTS:
        for off_byd in OFFENSE_BYD_PCTS:
            if off_byd < def_byd:  # offense must have >= BYD than defense
                continue
            if rn >= 10:
                break
            if def_byd == 0.75 and off_byd == 1.0:
                continue  # baseline
            result = compute_by_weights(report, returns_df, def_byd, off_byd, 1.125, 0.15, 4.0, 0.125, COST_BPS)
            label = f"R{rn+1}_def{int(def_byd*100):d}_off{int(off_byd*100):d}"
            all_results.append({"round": rn + 1, "label": label, "def_byd": def_byd, "off_byd": off_byd, **result})
            rn += 1

    # ===== R11-18: Convex Momentum =====
    print(f"\n{'='*60}")
    print("R11-18: Convex Momentum Parameter Sweep")

    rn = 10
    for full_inc in FULL_INCREMENT_MOMENTUMS[:4]:
        for cp in CONVEX_POWERS[:4]:
            if rn >= 18:
                break
            if full_inc == 0.15 and cp == 4.0:
                continue
            result = compute_by_weights(report, returns_df, 0.75, 1.0, 1.125, full_inc, cp, 0.125, COST_BPS)
            label = f"R{rn+1}_momInc{int(full_inc*100):d}_pow{int(cp):d}"
            all_results.append({"round": rn + 1, "label": label, **result})
            rn += 1

    # ===== R19-25: Max Financed Increment + Expansion Max =====
    print(f"\n{'='*60}")
    print("R19-25: Financed Increment + Expansion Max")

    rn = 18
    for max_fin in MAX_FINANCED_INCREMENTS[:4]:
        for exp_max in EXPANSION_MAX_PCTS[:2]:
            if rn >= 25:
                break
            if max_fin == 0.125 and exp_max == 1.125:
                continue
            result = compute_by_weights(report, returns_df, 0.75, 1.0, exp_max, 0.15, 4.0, max_fin, COST_BPS)
            label = f"R{rn+1}_maxFin{int(max_fin*1000):d}_exp{int(exp_max*100):d}"
            all_results.append({"round": rn + 1, "label": label, **result})
            rn += 1

    # ===== R26-30: Combined Best =====
    print(f"\n{'='*60}")
    print("R26-30: Combined Best Configurations")

    # Find best from each category
    r1_10 = [r for r in all_results if 1 <= r.get("round", 0) <= 10]
    r11_18 = [r for r in all_results if 11 <= r.get("round", 0) <= 18]
    r19_25 = [r for r in all_results if 19 <= r.get("round", 0) <= 25]

    best_alloc = max(r1_10, key=lambda r: r["calmar"]) if r1_10 else {"def_byd": 0.75, "off_byd": 1.0}
    best_mom = max(r11_18, key=lambda r: r["calmar"]) if r11_18 else None
    best_fin = max(r19_25, key=lambda r: r["calmar"]) if r19_25 else None

    # Combined tests
    combined = [
        ("R26_best_alloc", best_alloc.get("def_byd", 0.75), best_alloc.get("off_byd", 1.0), 1.125, 0.15, 4.0, 0.125),
        ("R27_best_alloc_def_only", best_alloc.get("def_byd", 0.75), 1.0, 1.125, 0.15, 4.0, 0.125),
        ("R28_max_by_150", 0.5, 1.0, 1.5, 0.10, 6.0, 0.15),
        ("R29_conservative", 0.5, 0.875, 1.0, 0.20, 3.0, 0.10),
        ("R30_aggressive", 0.25, 1.125, 1.5, 0.10, 8.0, 0.20),
    ]

    for label, d, o, e, fi, cp, mf in combined:
        result = compute_by_weights(report, returns_df, d, o, e, fi, cp, mf, COST_BPS)
        all_results.append({"round": int(label[1:3]), "label": label, "def_byd": d, "off_byd": o, **result})

    # ===== Final Summary =====
    display = [{k: v for k, v in r.items() if k != 'net_returns'} for r in all_results]
    display.sort(key=lambda r: r["calmar"], reverse=True)

    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY: All {len(display)} Rounds Sorted by Calmar")
    print(f"{'Round':<6} {'Label':<40s} {'Calmar':>8s} {'CAGR':>8s} {'MaxDD':>8s} {'Sharpe':>8s} {'TotalRet':>8s} {'Excess':>8s} {'Cost':>8s}")
    print("-" * 120)
    for r in display:
        print(f"R{r['round']:<5} {r['label']:<40s} {r['calmar']:>8.4f} {r['cagr']:>8.4f} {r['max_drawdown']:>8.4f} {r['sharpe']:>8.4f} {r['total_return']:>8.4f} {r['excess_return']:>8.4f} {r['total_cost']:>8.4f}")

    best = display[0]
    print(f"\nBEST: R{best['round']} {best['label']}")
    print(f"  Calmar: {best['calmar']:.4f}")
    print(f"  CAGR:   {best['cagr']:.4f}")
    print(f"  Max DD: {best['max_drawdown']:.4f}")
    print(f"  Sharpe: {best['sharpe']:.4f}")

    bl_disp = next(r for r in display if r["round"] == 0)
    print(f"\nvs Baseline: Calmar {bl_disp['calmar']:.4f}→{best['calmar']:.4f} (+{(best['calmar']/bl_disp['calmar']-1)*100:.1f}%)")

    # Save
    output = {"experiment_id": "byd_30_round_v1", "configs": len(display),
              "baseline": bl_disp, "best": best, "all_results": display}
    out_path = Path("artifacts/evidence/byd_30_round_v1/results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
