"""TOP/BOTTOM signal quality analysis — the definitive test.

For each CN model artifact and freshly trained variants, compute:
  - TOP-K:  average forward return of the K highest-scored stocks
  - BOTTOM-K: average forward return of the K lowest-scored stocks
  - TOP-BOTTOM spread: signal strength
  - Cumulative TOP-K and BOTTOM-K portfolio returns

A valid model must have:
  - TOP-K > BOTTOM-K consistently (positive spread)
  - TOP-K > benchmark (generates alpha)
  - BOTTOM-K < benchmark (correctly identifies losers)

This is model-agnostic — no strategy framework, just raw signal → return mapping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import numpy as np
import pandas as pd
from scipy.stats import pearsonr


def load_model_predictions(art_dir: Path) -> tuple[pd.DataFrame, str, str] | None:
    """Load predictions from an artifact directory. Returns (predictions_df, market, tag)."""
    pred_path = art_dir / "predictions.csv"
    mf_path = art_dir / "manifest.json"
    if not pred_path.exists():
        return None

    manifest = json.loads(mf_path.read_text()) if mf_path.exists() else {}
    market = manifest.get("market", "cn")
    tag = manifest.get("tag", manifest.get("model_id", art_dir.name[:16]))

    pred = pd.read_csv(pred_path)
    # Handle numeric IDs (CN) and ticker symbols (US)
    try:
        pred["instrument"] = pred["instrument"].apply(lambda x: str(int(x)).zfill(6))
    except (ValueError, TypeError):
        pred["instrument"] = pred["instrument"].astype(str)

    pred["datetime"] = pd.to_datetime(pred["datetime"])
    pred = pred.set_index(["datetime", "instrument"]).sort_index()
    return pred, market, tag


def compute_top_bottom_returns(
    predictions: pd.DataFrame,
    top_k: int = 15,
    rebalance_days: int = 10,
    forward_days: int = 10,
) -> dict:
    """Compute TOP-K and BOTTOM-K forward returns using REAL price data.

    For each rebalance date:
    1. Rank stocks by model score
    2. Select top-K and bottom-K
    3. Look up their ACTUAL forward return over `forward_days`
    4. Compute equal-weight average

    Returns dict with per-period returns and cumulative stats.
    """
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    safe_qlib_init(build_qlib_init_cfg(None, market="cn"))
    from qlib.data import D

    # Get instruments and date range
    instruments = sorted(predictions.index.get_level_values("instrument").unique().tolist())
    all_dates = sorted(predictions.index.get_level_values("datetime").unique())
    rebalance_dates = all_dates[::rebalance_days]

    if len(rebalance_dates) < 3:
        return {"error": "Too few rebalance dates"}

    # Load forward returns (actual future returns)
    ret_expr = f"Ref($close, -{forward_days}) / Ref($close, -1) - 1"
    start = str(rebalance_dates[0].date())
    end = str(rebalance_dates[-1].date())
    ret_raw = D.features(instruments, [ret_expr], start_time=start, end_time=end)
    if ret_raw.index.names == ["instrument", "datetime"]:
        ret_raw = ret_raw.swaplevel().sort_index()

    # Load benchmark
    bench_raw = D.features(["000300"], [ret_expr], start_time=start, end_time=end)
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench = bench_raw.xs("000300", level="instrument")
    else:
        bench = bench_raw

    # Load actual close prices for cumulative return calculation
    close_raw = D.features(instruments, ["$close"], start_time=start, end_time=end)
    if close_raw.index.names == ["instrument", "datetime"]:
        close_raw = close_raw.swaplevel().sort_index()

    top_returns = []
    bottom_returns = []
    bench_returns = []
    top_cum_ret = 1.0
    bottom_cum_ret = 1.0
    bench_cum_ret = 1.0

    top_cum_vals = [1.0]
    bottom_cum_vals = [1.0]
    bench_cum_vals = [1.0]

    for i, date in enumerate(rebalance_dates):
        if date not in predictions.index:
            continue

        # Get scores for this date
        scores = predictions.loc[date].iloc[:, 0].dropna().sort_values(ascending=False)

        if len(scores) < top_k * 2:
            continue

        top_stocks = scores.head(top_k).index.tolist()
        bottom_stocks = scores.tail(top_k).index.tolist()

        # Get forward returns for these stocks
        # Forward return: close[t+forward_days] / close[t] - 1
        # We need to find the price at date and at date+forward_days
        top_ret = 0.0
        bottom_ret = 0.0
        valid_top = 0
        valid_bottom = 0

        for sym in top_stocks:
            try:
                close_s = close_raw.xs(sym, level="instrument").iloc[:, 0]
                if date in close_s.index:
                    idx = close_s.index.get_loc(date)
                    future_idx = idx + forward_days
                    if future_idx < len(close_s):
                        entry = float(close_s.iloc[idx])
                        exit_p = float(close_s.iloc[future_idx])
                        if entry > 0:
                            top_ret += (exit_p - entry) / entry
                            valid_top += 1
            except Exception:
                continue

        for sym in bottom_stocks:
            try:
                close_s = close_raw.xs(sym, level="instrument").iloc[:, 0]
                if date in close_s.index:
                    idx = close_s.index.get_loc(date)
                    future_idx = idx + forward_days
                    if future_idx < len(close_s):
                        entry = float(close_s.iloc[idx])
                        exit_p = float(close_s.iloc[future_idx])
                        if entry > 0:
                            bottom_ret += (exit_p - entry) / entry
                            valid_bottom += 1
            except Exception:
                continue

        top_avg = top_ret / max(valid_top, 1)
        bottom_avg = bottom_ret / max(valid_bottom, 1)
        top_returns.append(top_avg)
        bottom_returns.append(bottom_avg)

        # Get benchmark forward return
        try:
            bench_close = bench_raw.xs("000300", level="instrument").iloc[:, 0] if isinstance(bench_raw.index, pd.MultiIndex) else bench_raw.iloc[:, 0]
            # This is already the forward return expression, so just use it directly
            if date in bench.index:
                br = float(bench.loc[date].iloc[0]) if isinstance(bench.loc[date], pd.DataFrame) else float(bench.loc[date])
                bench_returns.append(br)
            else:
                bench_returns.append(0.0)
        except Exception:
            bench_returns.append(0.0)

        top_cum_ret *= (1.0 + top_avg)
        bottom_cum_ret *= (1.0 + bottom_avg)
        # Use the actual benchmark return loaded above
        if bench_returns:
            bench_cum_ret *= (1.0 + bench_returns[-1])

        top_cum_vals.append(top_cum_ret)
        bottom_cum_vals.append(bottom_cum_ret)
        bench_cum_vals.append(bench_cum_ret)

    if not top_returns:
        return {"error": "No valid returns computed"}

    top_arr = np.array(top_returns)
    bottom_arr = np.array(bottom_returns)
    spread_arr = top_arr - bottom_arr
    bench_arr = np.array(bench_returns) if bench_returns else np.zeros_like(top_arr)

    # Cumulative stats
    top_total = top_cum_ret - 1.0
    bottom_total = bottom_cum_ret - 1.0
    bench_total = bench_cum_ret - 1.0
    spread_total = top_total - bottom_total

    # Per-period stats
    top_win_rate = np.mean(top_arr > 0)
    bottom_win_rate = np.mean(bottom_arr < 0)  # For bottom, we WANT negative returns
    spread_positive = np.mean(spread_arr > 0)

    # Annualized
    periods_per_year = 252 / rebalance_days
    top_ann = (1 + top_total) ** (periods_per_year / len(top_returns)) - 1 if len(top_returns) > 0 else 0
    spread_sharpe = np.mean(spread_arr) / np.std(spread_arr) * np.sqrt(periods_per_year) if np.std(spread_arr) > 1e-10 else 0

    return {
        "n_periods": len(top_returns),
        "top_total_return": top_total,
        "bottom_total_return": bottom_total,
        "benchmark_total_return": bench_total,
        "top_bottom_spread": spread_total,
        "top_annual_return": top_ann,
        "spread_sharpe": spread_sharpe,
        "top_win_rate": top_win_rate,
        "bottom_win_rate": bottom_win_rate,
        "spread_positive_rate": spread_positive,
        "top_mean_return": float(np.mean(top_arr)),
        "bottom_mean_return": float(np.mean(bottom_arr)),
        "spread_mean_return": float(np.mean(spread_arr)),
        "top_cum_vals": [float(x) for x in top_cum_vals],
        "bottom_cum_vals": [float(x) for x in bottom_cum_vals],
        "bench_cum_vals": [float(x) for x in bench_cum_vals],
        "rebalance_dates": [str(d.date()) for d in rebalance_dates[:len(top_returns)]],
    }


def main():
    artifacts_root = ROOT / "artifacts" / "artifacts"

    # 1. Analyze all existing Qlib-trained artifacts
    print("=" * 80)
    print("  TOP/BOTTOM Signal Quality Analysis — All CN Models")
    print("=" * 80)
    print(f"  {'Model':<42} {'TOP':>8} {'BOT':>8} {'Spread':>8} {'Bench':>8} {'S Sharpe':>7} {'T Win':>6} {'B Win':>6}")
    print("-" * 80)

    results = []
    for art_dir in sorted(artifacts_root.glob("*/")):
        data = load_model_predictions(art_dir)
        if data is None:
            continue
        predictions, market, tag = data
        if market != "cn":
            continue

        print(f"  Analyzing {tag[:40]}...", end=" ", flush=True)
        tb = compute_top_bottom_returns(predictions, top_k=15, rebalance_days=10, forward_days=10)
        if "error" in tb:
            print(f"ERROR: {tb['error']}")
            continue

        print("done")
        results.append((tag, tb))

        print(f"  {tag:<42} {tb['top_total_return']:>7.2%} {tb['bottom_total_return']:>7.2%} "
              f"{tb['top_bottom_spread']:>7.2%} {tb['benchmark_total_return']:>7.2%} "
              f"{tb['spread_sharpe']:>6.2f} {tb['top_win_rate']:>5.0%} {tb['bottom_win_rate']:>5.0%}")

    print("-" * 80)

    # 2. Check per-period consistency for the best model
    if results:
        best = max(results, key=lambda x: x[1]["top_bottom_spread"])
        print(f"\n  ★ Best model: {best[0]} (spread={best[1]['top_bottom_spread']:.2%})")
        tb = best[1]
        print(f"\n  Per-period TOP returns (first 10):")
        print(f"  {[f'{x:.2%}' for x in tb['top_cum_vals'][1:11]]}")

    # 3. Diagnose: compute sign consistency
    print(f"\n  === Sign Direction Analysis ===")
    for tag, tb in sorted(results, key=lambda x: x[1]["top_bottom_spread"], reverse=True):
        spread_sign = "+" if tb["top_bottom_spread"] > 0 else "-"
        signal_quality = "✅ VALID" if tb["top_bottom_spread"] > 0.05 else \
                         "⚠️ WEAK" if tb["top_bottom_spread"] > 0 else \
                         "❌ INVERTED"
        print(f"  {signal_quality} {tag[:45]}: spread={tb['top_bottom_spread']:+.2%} "
              f"TOP={tb['top_total_return']:+.2%} BOT={tb['bottom_total_return']:+.2%}")

    # 4. Save results
    output = {
        "generated_at": datetime.now().isoformat(),
        "top_k": 15,
        "rebalance_days": 10,
        "forward_days": 10,
        "results": {tag: {k: v for k, v in tb.items() if k not in ("top_cum_vals", "bottom_cum_vals", "bench_cum_vals", "rebalance_dates")}
                     for tag, tb in results},
    }
    out_path = ROOT / "artifacts" / "top_bottom_analysis.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
