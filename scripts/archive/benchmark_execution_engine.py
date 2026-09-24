"""Benchmark: SignalExecutionEngine vs run_vectorized_backtest on real CN data.

Compares:
  1. Baseline: run_vectorized_backtest() — simple TOP-K equal weight
  2. Grade-weighted: SignalExecutionEngine — differentiated position sizing
  3. Grade + Regime: SignalExecutionEngine with regime filter enabled
  4. Grade + Regime + Short: Full long/short with regime filter
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import pandas as pd
import structlog
from qlib.data import D

from src.common.paths import ARTIFACTS_DIR
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine
from src.research.vectorized_backtest import run_vectorized_backtest

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MARKET = "cn"
BENCHMARK_SYMBOL = "000300"
TEST_START = "2025-01-01"
TEST_END = "2026-06-18"
TOP_K = 15
REBALANCE_DAYS = 10
COST_BPS = 20.0


def load_artifact_predictions_and_returns() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load pre-computed predictions from artifact CSV and returns from Qlib.

    Uses the largest artifact predictions file (d1721b6e...) which has
    209 instruments, 2025-01-02 to 2026-06-18.
    """
    # Init Qlib
    cfg = build_qlib_init_cfg(None, market=MARKET)
    safe_qlib_init(cfg)

    # Find the largest prediction artifact
    artifact_dir = ARTIFACTS_DIR / "artifacts" / "d1721b6e77f4499ea7e9907c47f1a38c"
    if not artifact_dir.exists():
        # Fallback to any artifact with predictions
        candidates = sorted(ARTIFACTS_DIR.glob("artifacts/*/predictions.csv"))
        if not candidates:
            raise FileNotFoundError("No prediction artifacts found")
        artifact_dir = candidates[-1].parent

    logger.info("Loading artifact predictions", path=str(artifact_dir))

    # Load predictions
    pred_df = pd.read_csv(artifact_dir / "predictions.csv")
    # Convert numeric instrument IDs to zero-padded ticker symbols
    pred_df["instrument"] = pred_df["instrument"].apply(lambda x: str(int(x)).zfill(6))
    pred_df["datetime"] = pd.to_datetime(pred_df["datetime"])
    predictions = pred_df.set_index(["datetime", "instrument"]).sort_index()
    logger.info("Predictions loaded", shape=predictions.shape)

    # Load forward returns from Qlib (absolute 10-day returns)
    symbols = sorted(pred_df["instrument"].unique().tolist())
    logger.info("Loading returns", n_symbols=len(symbols))
    returns_raw = D.features(
        symbols,
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(returns_raw, pd.DataFrame) and len(returns_raw.columns) > 0:
        returns_raw.columns = ["return"]
    logger.info("Returns loaded", shape=returns_raw.shape)

    # Load CSI300 benchmark
    bench_raw = D.features(
        [BENCHMARK_SYMBOL],
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time=TEST_START,
        end_time=TEST_END,
    )
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench_returns = bench_raw.xs(BENCHMARK_SYMBOL, level="instrument")
    else:
        bench_returns = bench_raw
    if isinstance(bench_returns, pd.DataFrame):
        bench_returns.columns = ["benchmark"]
    logger.info("Benchmark loaded", shape=bench_returns.shape)

    return predictions, returns_raw, bench_returns


def run_benchmarks(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> dict:
    """Run all four engine configurations and return comparison."""
    results = {}

    # --- 1. Baseline: Simple TOP-K equal-weight (vectorized) ---
    logger.info("Benchmark 1/4: Vectorized TOP-K equal-weight")
    t0 = time.perf_counter()
    vec_result = run_vectorized_backtest(
        predictions=predictions,
        returns=returns,
        benchmark_returns=benchmark,
        topk=TOP_K,
        rebalance_days=REBALANCE_DAYS,
        initial_capital=10000.0,
        cost_bps=COST_BPS,
        non_overlapping=True,
    )
    results["1_vec_topk_equal"] = {
        "result": vec_result,
        "wall_seconds": time.perf_counter() - t0,
        "description": f"简单TOP-{TOP_K}等权（基准）",
    }

    # --- 2. Grade-weighted, long-only, no regime filter ---
    logger.info("Benchmark 2/4: Grade-weighted long-only")
    config_longs = SignalExecutionConfig(
        market=MARKET,
        step_size=5,
        long_fraction=1.0,
        short_fraction=0.0,
        rebalance_days=REBALANCE_DAYS,
        enable_regime_filter=False,
        buy_cost_bps=COST_BPS / 2,
        sell_cost_bps=COST_BPS / 2,
    )
    engine_longs = SignalExecutionEngine(config_longs)
    t0 = time.perf_counter()
    result_longs = engine_longs.execute(predictions, returns, benchmark)
    results["2_grade_long_only"] = {
        "result": result_longs,
        "wall_seconds": time.perf_counter() - t0,
        "description": "分级权重纯多头（AAA=3x, AA=2x, A=1x）",
    }

    # --- 3. Grade-weighted + regime filter, long-only ---
    logger.info("Benchmark 3/4: Grade-weighted + Regime filter")
    config_regime = SignalExecutionConfig(
        market=MARKET,
        step_size=5,
        long_fraction=1.0,
        short_fraction=0.0,
        rebalance_days=REBALANCE_DAYS,
        enable_regime_filter=True,
        buy_cost_bps=COST_BPS / 2,
        sell_cost_bps=COST_BPS / 2,
    )
    engine_regime = SignalExecutionEngine(config_regime)
    t0 = time.perf_counter()
    result_regime = engine_regime.execute(predictions, returns, benchmark)
    results["3_grade_regime_long"] = {
        "result": result_regime,
        "wall_seconds": time.perf_counter() - t0,
        "description": "分级权重 + 市场状态过滤（纯多头）",
        "diagnostics": result_regime._diagnostics.summary()  # type: ignore[attr-defined]
        if hasattr(result_regime, "_diagnostics")
        else {},
    }

    # --- 4. Full: Grade-weighted + regime + short side ---
    logger.info("Benchmark 4/4: Full long/short + Regime")
    config_full = SignalExecutionConfig(
        market=MARKET,
        step_size=5,
        long_fraction=0.8,
        short_fraction=0.2,
        rebalance_days=REBALANCE_DAYS,
        enable_regime_filter=True,
        buy_cost_bps=COST_BPS / 2,
        sell_cost_bps=COST_BPS / 2,
    )
    engine_full = SignalExecutionEngine(config_full)
    t0 = time.perf_counter()
    result_full = engine_full.execute(predictions, returns, benchmark)
    results["4_grade_regime_ls"] = {
        "result": result_full,
        "wall_seconds": time.perf_counter() - t0,
        "description": "完整：分级权重 + 状态过滤 + 做空端（80%多/20%空）",
        "diagnostics": result_full._diagnostics.summary()  # type: ignore[attr-defined]
        if hasattr(result_full, "_diagnostics")
        else {},
    }

    return results


def print_comparison(results: dict) -> None:
    """Print side-by-side comparison of all engine runs."""
    header = (
        f"{'Engine':<40} {'Excess':>8} {'Total':>8} "
        f"{'Bench':>8} {'Sharpe':>7} {'MaxDD':>7} {'Vol':>7} "
        f"{'IC':>6} {'Time':>6}"
    )
    print("\n" + "=" * len(header))
    print("SignalExecutionEngine Benchmark — Real CN Data")
    print(
        f"Period: {TEST_START} → {TEST_END} | "
        f"TopK≈{TOP_K} | Rebalance={REBALANCE_DAYS}d | Cost={COST_BPS}bps"
    )
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for key, data in results.items():
        r = data["result"]
        desc = data["description"]
        wall = data["wall_seconds"]
        print(
            f"{desc:<40} "
            f"{r.excess_return:>7.2%} "
            f"{r.total_return:>7.2%} "
            f"{r.benchmark_return:>7.2%} "
            f"{r.sharpe_ratio:>6.2f} "
            f"{r.max_drawdown:>6.2%} "
            f"{r.volatility:>6.2%} "
            f"{r.mean_ic:>5.3f} "
            f"{wall:>5.1f}s"
        )

    print("-" * len(header))

    # Highlight improvement
    vec_excess = results["1_vec_topk_equal"]["result"].excess_return
    for key in ["2_grade_long_only", "3_grade_regime_long", "4_grade_regime_ls"]:
        r = results[key]["result"]
        improvement = r.excess_return - vec_excess
        desc = results[key]["description"]
        print(f"  → {desc}: 超额改善 {improvement:+.2%}")

    # Print diagnostics for regime-aware runs
    for key in ["3_grade_regime_long", "4_grade_regime_ls"]:
        if "diagnostics" in results[key]:
            d = results[key]["diagnostics"]
            desc = results[key]["description"]
            print(f"\n  [{desc}] 状态诊断:")
            for k, v in d.items():
                print(f"    {k}: {v}")


def main() -> None:
    predictions, returns, benchmark = load_artifact_predictions_and_returns()

    print("\n训练数据维度:")
    print(f"  predictions: {predictions.shape}")
    print(f"  returns:     {returns.shape}")
    print(f"  benchmark:   {benchmark.shape}")

    results = run_benchmarks(predictions, returns, benchmark)
    print_comparison(results)

    # Save results
    output_path = ARTIFACTS_DIR / "benchmark_comparison.json"
    serializable = {}
    for key, data in results.items():
        r = data["result"]
        entry = {
            "description": data["description"],
            "wall_seconds": data["wall_seconds"],
            **r.to_dict(),
        }
        if "diagnostics" in data:
            entry["diagnostics"] = data["diagnostics"]
        serializable[key] = entry

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\n结果已保存至: {output_path}")


if __name__ == "__main__":
    main()
