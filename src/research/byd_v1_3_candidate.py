"""BYD V1.3 Candidate — Min-Hold + Bear-Adaptive Defense.

Drop-in candidate that extends the existing V1.2 infrastructure with:
  1. Min-hold 20d on risk-on/off state transitions
  2. Bear-adaptive defense (55% BYD / 45% ETF in confirmed bear markets)
  3. Optimized expansion: 15% max increment, convex_power=2

The module uses the same data pipeline, execution engine, and evaluation
windows as the formal V1.2 model. All metrics are directly comparable.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    AllocationResult,
    evaluation_table,
    metrics,
    prepare_common_dataset,
)
from src.research.byd_515180_execution import (
    execute_next_common_open,
)
from src.research.byd_v1_2_convex_momentum import momentum_scale
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
)

# — V1.3 Parameters ——————————————————————————————————————————————————————

V13_MIN_HOLD_DAYS = 20
V13_BEAR_DEFENSE_BYD = 0.55      # 55% BYD in bear (vs 75% baseline)
V13_BEAR_DEFENSE_ETF = 0.45       # 45% ETF in bear (vs 25% baseline)
V13_EXPANSION_PCT = 0.15          # max 15% financed (vs 12.5%)
V13_CONVEX_POWER = 2.0            # convex power 2 (vs 4 — gentler ramp)
V13_FULL_INCREMENT_MOMENTUM = 0.15  # same as V1.2

BASELINE_NAME = "byd_v1_2_convex_momentum_budget_v1"
CANDIDATE_NAME = "byd_v1_3_min_hold_bear_defense"


# — Stateful min-hold ————————————————————————————————————————————————————


def _stateful_min_hold(
    entry: pd.Series,
    exit_: pd.Series,
    min_hold: int,
) -> pd.Series:
    """Hysteresis with minimum holding period constraint."""
    active = False
    hold_counter = 0
    values: list[float] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active:
            hold_counter += 1
        if active and bool(exit_now) and hold_counter >= min_hold:
            active = False
            hold_counter = 0
        elif not active and bool(enter_now):
            active = True
            hold_counter = 0
        values.append(1.0 if active else 0.0)
    return pd.Series(values, index=entry.index, dtype=float)


def _stateful_expansion_entry_exit(
    entry: pd.Series,
    exit_: pd.Series,
) -> pd.Series:
    """Standard hysteresis (no min-hold) for expansion — unchanged from V1.2."""
    active = False
    values: list[bool] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        values.append(active)
    return pd.Series(values, index=entry.index, name="trend_expansion_active")


# — V1.3 Signal Builder ——————————————————————————————————————————————————


def build_v13_signals(dataset: pd.DataFrame) -> pd.DataFrame:
    """Build V1.3 base signals with min-hold + bear-adaptive defense.

    Returns DataFrame with base_byd_weight (V1.3 version).
    """
    close = dataset["close"]
    sma_120 = close.rolling(120, min_periods=120).mean()
    mom_20 = close.pct_change(20)
    mom_60 = close.pct_change(60)

    # — Risk-on/off with min-hold —————————————————————————————————————
    risk_on_entry = close.gt(sma_120) & mom_20.gt(0.0)
    risk_off_exit = close.lt(sma_120) & mom_60.lt(0.0)

    base_risk_on = _stateful_min_hold(
        risk_on_entry, risk_off_exit, min_hold=V13_MIN_HOLD_DAYS
    )

    # — Bear market detection —————————————————————————————————————————
    sma_200 = close.rolling(200, min_periods=200).mean()
    sma_60 = close.rolling(60, min_periods=60).mean()
    is_bear = close.lt(sma_200) & sma_60.lt(sma_200)

    # — Base BYD weight ———————————————————————————————————————————————
    base_byd = pd.Series(0.75, index=dataset.index, dtype=float)
    base_byd[base_risk_on > 0.5] = 1.0  # risk-on → 100% BYD
    base_byd[(base_risk_on < 0.5) & is_bear] = V13_BEAR_DEFENSE_BYD  # bear defense

    return pd.DataFrame(
        {
            "base_byd_weight": base_byd,
            "base_risk_on": base_risk_on,
            "is_bear": is_bear.astype(bool),
        },
        index=dataset.index,
    )


# — V1.3 Decision Builder ————————————————————————————————————————————————


def build_v13_decisions(
    common: pd.DataFrame,
    v13_signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Build V1.3 weight decisions with optimized expansion.

    Returns (decisions dict, ledger DataFrame).
    """
    base = v13_signals["base_byd_weight"].astype(float)

    # — Expansion state (same conditions as V1.2) —————————————————————
    # V1.3 base can be 1.0, 0.75 (normal defense), or 0.55 (bear defense).
    # Exit when base drops below 1.0 (to ANY defense level).
    entry = (
        base.eq(1.0)
        & common["market_state"].eq("bull")
        & common["vol_state"].eq("low")
        & common["mom_20"].gt(0.0)
        & common["mom_60"].gt(0.0)
        & common["drawdown_252"].gt(-0.10)
    )
    exit_ = (
        base.lt(1.0)
        | common["market_state"].ne("bull")
        | common["vol_state"].eq("high")
        | common["mom_20"].le(0.0)
    )

    expansion_active = _stateful_expansion_entry_exit(entry, exit_)

    # — Convex momentum scale (V1.3 optimized) ————————————————————————
    scale = momentum_scale(
        common["mom_20"],
        full_increment_momentum=V13_FULL_INCREMENT_MOMENTUM,
        convex_power=V13_CONVEX_POWER,
    )
    increment = expansion_active.astype(float) * V13_EXPANSION_PCT * scale

    # — V1.2 baseline decisions (for comparison) ——————————————————————
    # V1.2 uses standard base (75% defense, no min-hold)
    base_v12 = v13_signals["base_byd_weight"].copy()
    base_v12[base_v12 < 0.99] = 0.75  # reset to standard defense for V1.2 comparison
    # Actually we need separate V1.2 signals. Let's compute them.
    close = common["close"]
    sma_120 = close.rolling(120, min_periods=120).mean()
    mom_20_v12 = common["mom_20"]
    mom_60_v12 = common["mom_60"]

    risk_on_entry_v12 = close.gt(sma_120) & mom_20_v12.gt(0.0)
    risk_off_exit_v12 = close.lt(sma_120) & mom_60_v12.lt(0.0)
    # Standard V1.2 hysteresis (no min-hold)
    base_v12_risk_on = _stateful_expansion_entry_exit(risk_on_entry_v12, risk_off_exit_v12)
    base_v12_byd = pd.Series(0.75, index=common.index, dtype=float)
    base_v12_byd[base_v12_risk_on > 0.5] = 1.0

    # V1.2 expansion
    entry_v12 = (
        base_v12_byd.eq(1.0)
        & common["market_state"].eq("bull")
        & common["vol_state"].eq("low")
        & mom_20_v12.gt(0.0)
        & mom_60_v12.gt(0.0)
        & common["drawdown_252"].gt(-0.10)
    )
    exit_v12 = (
        base_v12_byd.eq(0.75)
        | common["market_state"].ne("bull")
        | common["vol_state"].eq("high")
        | mom_20_v12.le(0.0)
    )
    expansion_v12 = _stateful_expansion_entry_exit(entry_v12, exit_v12)
    scale_v12 = momentum_scale(mom_20_v12, full_increment_momentum=0.15, convex_power=4.0)
    increment_v12 = expansion_v12.astype(float) * 0.125 * scale_v12

    def make_weights(byd_base, exp_active, inc, etf_mode="v12"):
        byd = byd_base + inc
        byd = byd.clip(upper=1.0 + max(V13_EXPANSION_PCT, 0.125))
        etf = pd.Series(0.0, index=common.index, dtype=float)
        if etf_mode == "v12":
            defense_mask = (byd_base < 0.99) & (exp_active < 0.5)
            etf[defense_mask] = 0.25
        elif etf_mode == "v13":
            # Normal defense: 75% BYD + 25% ETF
            normal_def = (byd_base >= 0.74) & (byd_base <= 0.76) & (exp_active < 0.5)
            etf[normal_def] = 0.25
            # Bear defense: 55% BYD + 45% ETF
            bear_def = (byd_base < 0.74) & (exp_active < 0.5)
            etf[bear_def] = V13_BEAR_DEFENSE_ETF
        cash = 1.0 - byd - etf
        return pd.DataFrame(
            {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
            index=common.index,
        )

    decisions = {
        BASELINE_NAME: make_weights(base_v12_byd, expansion_v12, increment_v12, "v12"),
        CANDIDATE_NAME: make_weights(base, expansion_active, increment, "v13"),
    }

    ledger = pd.DataFrame(
        {
            "base_byd_weight_v12": base_v12_byd,
            "base_byd_weight_v13": base,
            "expansion_active_v12": expansion_v12.astype(bool),
            "expansion_active_v13": expansion_active.astype(bool),
            "momentum_scale_v12": scale_v12,
            "momentum_scale_v13": scale,
            "financed_increment_v12": increment_v12,
            "financed_increment_v13": increment,
        },
        index=common.index,
    )

    # Validate
    for name, frame in decisions.items():
        if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
            raise AssertionError(f"{name} weights do not sum to 1.0")
        if (frame["byd_weight"] < -1e-12).any() or (frame["etf_weight"] < -1e-12).any():
            raise AssertionError(f"{name} has negative weights")

    return decisions, ledger


# — Backtest runner ———————————————————————————————————————————————————————


def run_v13_backtest(
    common: pd.DataFrame,
    decisions: dict[str, pd.DataFrame],
    cost_bps: float,
    annual_financing_rate: float,
) -> dict[str, AllocationResult]:
    """Execute both V1.2 baseline and V1.3 candidate."""
    results = {}
    for name, decision in decisions.items():
        executed = execute_next_common_open(decision, common["common_open_eligible"])
        byd_w = executed["position_byd_weight"]
        etf_w = executed["position_etf_weight"]
        cash_w = executed["position_cash_weight"]

        gross = (
            byd_w * common["byd_open_return"]
            + etf_w * common["etf_open_return"]
        )
        turnover = executed.diff().abs().sum(axis=1)
        turnover.iloc[0] = 0.0
        cost = turnover * cost_bps / 10_000.0

        borrowed = np.maximum(-cash_w, 0.0)
        financing_cost = borrowed * annual_financing_rate / 252.0

        daily = pd.concat([decision.add_prefix("decision_"), executed], axis=1)
        daily["common_open_eligible"] = common["common_open_eligible"]
        daily["byd_return"] = common["byd_open_return"]
        daily["etf_return"] = common["etf_open_return"]
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = cost
        daily["financing_cost"] = financing_cost
        daily["borrowed_weight"] = borrowed
        daily["net_return"] = gross - cost - financing_cost
        daily = daily.iloc[:-1].copy()

        changes = executed.ne(executed.shift(1)).any(axis=1)
        trades = daily.loc[
            changes.reindex(daily.index).fillna(False),
            [
                "position_byd_weight",
                "position_etf_weight",
                "position_cash_weight",
                "turnover_units",
                "cost",
                "common_open_eligible",
            ],
        ].copy()

        results[name] = AllocationResult(
            name=name, daily=daily, trades=trades.reset_index()
        )

    return results


# — Evaluation ————————————————————————————————————————————————————————————


def evaluate_v13(
    primary: dict[str, AllocationResult],
    stress: dict[str, AllocationResult],
) -> dict[str, Any]:
    """Full evaluation: metrics, period comparison, diagnostics."""
    primary_eval = evaluation_table(primary, PRIMARY_COST_BPS)
    stress_eval = evaluation_table(stress, STRESS_COST_BPS)

    comparison_rows = []
    for scenario, results, cost in [
        ("primary", primary, PRIMARY_COST_BPS),
        ("stress", stress, STRESS_COST_BPS),
    ]:
        for name in [BASELINE_NAME, CANDIDATE_NAME]:
            result = results[name]
            for window, (start, end) in WINDOWS.items():
                block = result.daily.loc[pd.Timestamp(start): pd.Timestamp(end)]
                if block.empty:
                    continue
                m = metrics(block)
                m.update({
                    "scenario": scenario,
                    "model": name,
                    "window": window,
                    "cost_bps": cost,
                    "financed_sessions": int(
                        block.loc[block.index, "borrowed_weight"].gt(0.0).sum()
                    ),
                    "transaction_cost_paid": float(
                        block.loc[block.index, "cost"].sum()
                    ),
                    "financing_cost_paid": float(
                        block.loc[block.index, "financing_cost"].sum()
                    ),
                })
                comparison_rows.append(m)

    comparison = pd.DataFrame(comparison_rows)

    # Compute deltas
    for scenario in ["primary", "stress"]:
        for window in WINDOWS:
            base_row = comparison[
                (comparison["scenario"] == scenario)
                & (comparison["model"] == BASELINE_NAME)
                & (comparison["window"] == window)
            ]
            cand_row = comparison[
                (comparison["scenario"] == scenario)
                & (comparison["model"] == CANDIDATE_NAME)
                & (comparison["window"] == window)
            ]
            if len(base_row) == 1 and len(cand_row) == 1:
                for metric in ["cagr", "sharpe", "max_drawdown", "calmar"]:
                    delta = float(cand_row[metric].iloc[0] - base_row[metric].iloc[0])
                    print(f"  [{scenario}][{window}] {metric}: "
                          f"V1.2={base_row[metric].iloc[0]:.4f}, "
                          f"V1.3={cand_row[metric].iloc[0]:.4f}, "
                          f"Δ={delta:+.4f}")

    # Period-level relative wealth
    period_relative = {}
    for period, (start, end) in WINDOWS.items():
        if period == "full_overlap":
            continue
        v12_w = float(
            (1.0 + primary[BASELINE_NAME].daily.loc[start:end, "net_return"].dropna()).prod()
        )
        v13_w = float(
            (1.0 + primary[CANDIDATE_NAME].daily.loc[start:end, "net_return"].dropna()).prod()
        )
        period_relative[period] = {
            "v12_terminal_wealth": v12_w,
            "v13_terminal_wealth": v13_w,
            "relative": v13_w / v12_w - 1.0,
        }

    return {
        "comparison_table": comparison_rows,
        "period_relative": period_relative,
        "primary_eval": primary_eval.to_dict("records"),
        "stress_eval": stress_eval.to_dict("records"),
    }


# — Diagnostics ———————————————————————————————————————————————————————————


def run_diagnostics(
    common: pd.DataFrame,
    v13_signals: pd.DataFrame,
    primary: dict[str, AllocationResult],
) -> dict[str, Any]:
    """Compute V1.3-specific diagnostics."""
    v13_daily = primary[CANDIDATE_NAME].daily
    v12_daily = primary[BASELINE_NAME].daily

    # BYD weight distribution comparison
    diag = {
        "v13_mean_byd_weight": float(v13_daily["position_byd_weight"].mean()),
        "v12_mean_byd_weight": float(v12_daily["position_byd_weight"].mean()),
        "v13_mean_etf_weight": float(v13_daily["position_etf_weight"].mean()),
        "v12_mean_etf_weight": float(v12_daily["position_etf_weight"].mean()),
        "v13_n_financed": int(v13_daily["borrowed_weight"].gt(0.0).sum()),
        "v12_n_financed": int(v12_daily["borrowed_weight"].gt(0.0).sum()),
        "v13_bear_days": int(v13_signals["is_bear"].sum()),
    }

    # Trade count comparison
    v13_trades = len(primary[CANDIDATE_NAME].trades)
    v12_trades = len(primary[BASELINE_NAME].trades)
    diag["v13_trades"] = v13_trades
    diag["v12_trades"] = v12_trades
    diag["trade_reduction_pct"] = (
        (v12_trades - v13_trades) / max(v12_trades, 1) * 100
    )

    return diag


# — Main —————————————————————————————————————————————————————————————————


def main():
    import argparse

    parser = argparse.ArgumentParser(description="BYD V1.3 backtest")
    parser.add_argument("--byd-root", type=str,
                        default=str(PROJECT_ROOT / "data" / "research" / "byd_canonical_v1_extracted"))
    parser.add_argument("--etf-root", type=str, default="")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    byd_root = Path(args.byd_root)
    etf_root = Path(args.etf_root) if args.etf_root else None

    print("=" * 70)
    print("BYD V1.3 Candidate — Full Backtest")
    print("=" * 70)
    print(f"BYD root: {byd_root}")
    print(f"Min hold: {V13_MIN_HOLD_DAYS}d")
    print(f"Bear defense: {V13_BEAR_DEFENSE_BYD:.0%} BYD / {V13_BEAR_DEFENSE_ETF:.0%} ETF")
    print(f"Expansion: {V13_EXPANSION_PCT:.1%} max, convex_power={V13_CONVEX_POWER}")

    # — Load data ——————————————————————————————————————————————————————
    print("\n--- Loading Data ---")

    if etf_root is None:
        import base64, io, zipfile
        b64_path = PROJECT_ROOT / "data" / "research" / "515180_canonical_v1_artifact.zip.b64"
        etf_root = PROJECT_ROOT / "data" / "research" / "_etf_extracted"
        if b64_path.exists():
            if not etf_root.exists() or not (etf_root / "manifest.json").exists():
                data = base64.b64decode(b64_path.read_text())
                zf = zipfile.ZipFile(io.BytesIO(data))
                etf_root.mkdir(exist_ok=True)
                zf.extractall(etf_root)
                print(f"Extracted ETF to: {etf_root}")
        else:
            raise FileNotFoundError(f"ETF b64 not found at {b64_path}")

    common, signals, event_ledger = prepare_common_dataset(byd_root, etf_root)
    print(f"Common dataset: {len(common)} rows, "
          f"{common.index[0].date()} → {common.index[-1].date()}")

    # — Build V1.3 signals ————————————————————————————————————————————
    print("\n--- Building V1.3 Signals ---")
    v13_signals = build_v13_signals(common)
    bear_pct = v13_signals["is_bear"].mean() * 100
    risk_on_pct = v13_signals["base_risk_on"].mean() * 100
    print(f"Bear market: {bear_pct:.1f}% of days")
    print(f"Risk-on: {risk_on_pct:.1f}% of days")
    print(f"Mean base BYD weight: {v13_signals['base_byd_weight'].mean():.3f}")

    # — Build decisions ————————————————————————————————————————————————
    print("\n--- Building Decisions ---")
    decisions, ledger = build_v13_decisions(common, v13_signals)

    # — Run backtest ———————————————————————————————————————————————————
    print("\n--- Primary Scenario (20bps, 6% financing) ---")
    primary = run_v13_backtest(common, decisions, PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE)

    print("\n--- Stress Scenario (40bps, 10% financing) ---")
    stress = run_v13_backtest(common, decisions, STRESS_COST_BPS, STRESS_FINANCING_RATE)

    # — Evaluate ————————————————————————————————————————————————————————
    print("\n" + "=" * 70)
    print("V1.2 vs V1.3 — Results")
    print("=" * 70)
    eval_results = evaluate_v13(primary, stress)

    # — Diagnostics —————————————————————————————————————————————————————
    diag = run_diagnostics(common, v13_signals, primary)
    print(f"\n--- Diagnostics ---")
    print(f"  V1.2 trades: {diag['v12_trades']}, V1.3 trades: {diag['v13_trades']} "
          f"({diag['trade_reduction_pct']:.0f}% reduction)")
    print(f"  V1.2 mean BYD: {diag['v12_mean_byd_weight']:.3f}, "
          f"V1.3 mean BYD: {diag['v13_mean_byd_weight']:.3f}")
    print(f"  V1.2 mean ETF: {diag['v12_mean_etf_weight']:.3f}, "
          f"V1.3 mean ETF: {diag['v13_mean_etf_weight']:.3f}")
    print(f"  V1.2 financed: {diag['v12_n_financed']}, "
          f"V1.3 financed: {diag['v13_n_financed']}")
    print(f"  V1.3 bear days: {diag['v13_bear_days']}")

    # Period relative
    print(f"\n--- Period Relative Wealth (V1.3 / V1.2 - 1) ---")
    for period, data in eval_results["period_relative"].items():
        print(f"  {period}: {data['relative']:+.4f} "
              f"(V1.2={data['v12_terminal_wealth']:.4f}, V1.3={data['v13_terminal_wealth']:.4f})")

    # — Save ————————————————————————————————————————————————————————————
    if args.output:
        output_dir = Path(args.output)
    else:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "data" / "research" / "byd_v2_experiments" / f"v13_candidate_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "metadata": {
            "candidate": CANDIDATE_NAME,
            "baseline": BASELINE_NAME,
            "min_hold_days": V13_MIN_HOLD_DAYS,
            "bear_defense_byd": V13_BEAR_DEFENSE_BYD,
            "expansion_pct": V13_EXPANSION_PCT,
            "convex_power": V13_CONVEX_POWER,
        },
        "evaluation": eval_results,
        "diagnostics": diag,
        "v13_signals_summary": {
            "bear_pct": bear_pct,
            "risk_on_pct": risk_on_pct,
            "mean_base_byd": float(v13_signals["base_byd_weight"].mean()),
        },
    }

    # Serialize primary daily for reproducibility
    for name in [BASELINE_NAME, CANDIDATE_NAME]:
        daily = primary[name].daily
        daily.to_csv(output_dir / f"{name}_daily.csv", float_format="%.8f")

    with open(output_dir / "v13_evaluation.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nResults saved to: {output_dir}")
    return output


if __name__ == "__main__":
    main()
