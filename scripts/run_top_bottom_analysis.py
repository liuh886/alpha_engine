"""Run TOP/BOTTOM 5/10/15/20 backtest analysis for all registered models.

For each model with predictions/labels:
- Runs layered vectorized backtest at TOP5, TOP10, TOP15, TOP20
- Runs BOTTOM5, BOTTOM10, BOTTOM15, BOTTOM20 (inverse confirmation)
- Compares against benchmark (QQQ for US, CSI300 for CN)
- Saves results to artifacts/dashboard/top_bottom_analysis.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import pandas as pd

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.vectorized_backtest import run_vectorized_backtest


def load_predictions(artifact_dir: Path) -> tuple[pd.DataFrame, str] | None:
    """Load predictions and detect market. Returns (predictions, market) or None."""
    pred_path = artifact_dir / "predictions.csv"
    manifest_path = artifact_dir / "manifest.json"

    if not pred_path.exists():
        return None

    pred_df = pd.read_csv(pred_path)
    # Normalize instrument IDs
    pred_df["instrument"] = pred_df["instrument"].apply(_normalize)
    pred_df["datetime"] = pd.to_datetime(pred_df["datetime"])
    predictions = pred_df.set_index(["datetime", "instrument"]).sort_index()

    market = "cn"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            market = manifest.get("market", "cn")
        except Exception:
            pass

    return predictions, market


def _normalize(raw: str) -> str:
    raw = str(raw).strip()
    try:
        return str(int(raw)).zfill(6)
    except ValueError:
        return raw.upper()


def run_analysis():
    """Run the full TOP/BOTTOM analysis for all artifact_directories."""
    bundle_dir = ARTIFACTS_DIR / "artifacts"
    if not bundle_dir.exists():
        print("No artifacts/artifacts directory")
        return

    artifact_dirs = sorted(
        [d for d in bundle_dir.iterdir() if d.is_dir() and (d / "predictions.csv").exists()]
    )
    print(f"Found {len(artifact_dirs)} artifact directories with predictions")

    k_values = [5, 10, 15, 20]
    all_results: dict[str, dict] = {}

    for art_dir in artifact_dirs:
        data = load_predictions(art_dir)
        if data is None:
            continue
        predictions, market = data
        run_id = art_dir.name

        # Load manifest for model info
        manifest = {}
        mf_path = art_dir / "manifest.json"
        if mf_path.exists():
            try:
                manifest = json.loads(mf_path.read_text())
            except Exception:
                pass

        bench_symbol = "QQQ" if market == "us" else "000300"
        safe_qlib_init(build_qlib_init_cfg(None, market=market))

        from qlib.data import D

        # Get date range
        pred_dates = predictions.index.get_level_values("datetime")
        instruments = sorted(predictions.index.get_level_values("instrument").unique().tolist())
        test_start = str(pred_dates.min().date())
        test_end = str(pred_dates.max().date())

        # Load real forward returns
        raw_returns = D.features(
            instruments,
            ["Ref($close, -10) / Ref($close, -1) - 1"],
            start_time=test_start,
            end_time=test_end,
        )
        real_returns = raw_returns.copy()
        if isinstance(real_returns, pd.DataFrame):
            real_returns.columns = ["return"]
            if real_returns.index.names == ["instrument", "datetime"]:
                real_returns = real_returns.swaplevel().sort_index()

        # Load benchmark
        try:
            bench_raw = D.features(
                [bench_symbol],
                ["Ref($close, -10) / Ref($close, -1) - 1"],
                start_time=test_start,
                end_time=test_end,
            )
            if isinstance(bench_raw.index, pd.MultiIndex):
                bench = bench_raw.xs(bench_symbol, level="instrument")
            else:
                bench = bench_raw
            if isinstance(bench, pd.DataFrame):
                bench.columns = ["benchmark"]
        except Exception:
            bench = None

        model_results = {
            "model_id": manifest.get("model_id", f"artifact_{run_id[:16]}"),
            "run_id": run_id,
            "market": market,
            "benchmark": bench_symbol,
            "test_period": f"{test_start} → {test_end}",
            "n_instruments": len(instruments),
            "n_dates": len(pred_dates.unique()),
            "created_at": datetime.now().isoformat(),
            "top_results": {},
            "bottom_results": {},
        }

        for k in k_values:
            # TOP K
            top = run_vectorized_backtest(
                predictions, real_returns, bench,
                topk=k, rebalance_days=10, initial_capital=10000.0,
                cost_bps=20.0, non_overlapping=False,
            )
            model_results["top_results"][str(k)] = {
                "total_return": round(top.total_return, 6),
                "excess_return": round(top.excess_return, 6),
                "sharpe_ratio": round(top.sharpe_ratio, 4),
                "max_drawdown": round(top.max_drawdown, 4),
                "annual_return": round(top.annual_return, 4),
                "volatility": round(top.volatility, 4),
                "mean_ic": round(top.mean_ic, 4),
                "n_periods": top.n_periods,
            }

            # BOTTOM K (inverse: predict bottom instead of top)
            neg_predictions = predictions.copy()
            neg_predictions["score"] = -neg_predictions["score"]
            bot = run_vectorized_backtest(
                neg_predictions, real_returns, bench,
                topk=k, rebalance_days=10, initial_capital=10000.0,
                cost_bps=20.0, non_overlapping=False,
            )
            model_results["bottom_results"][str(k)] = {
                "total_return": round(bot.total_return, 6),
                "excess_return": round(bot.excess_return, 6),
                "sharpe_ratio": round(bot.sharpe_ratio, 4),
                "max_drawdown": round(bot.max_drawdown, 4),
                "annual_return": round(bot.annual_return, 4),
                "volatility": round(bot.volatility, 4),
                "mean_ic": round(bot.mean_ic, 4),
                "n_periods": bot.n_periods,
            }

        all_results[run_id] = model_results
        print(f"  {run_id[:16]}... ({market}) TOP5→20 + BOT5→20 done")

    # Save results
    output_path = DASHBOARD_DB_PATH.parent / "top_bottom_analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(
        {
            "generated_at": datetime.now().isoformat(),
            "models": list(all_results.values()),
        },
        indent=2, ensure_ascii=False,
    ))
    print(f"Saved {len(all_results)} model analyses to {output_path}")


if __name__ == "__main__":
    run_analysis()
