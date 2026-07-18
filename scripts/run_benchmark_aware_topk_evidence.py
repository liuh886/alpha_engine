"""Generate benchmark-aware Top-K OOS portfolio evidence for the frozen #86 best candidate.

This runner evaluates the frozen 50/50 blend of the momentum_volatility_volume daily
ranker and inverted historical 10D momentum through benchmark-aware Top-K / Bottom-K /
Top-K-minus-Bottom-K lenses across half-year rolling windows.

Output (under ``artifacts/evidence/benchmark_aware_topk/``):

* ``per_window/`` — one JSON per window with Top-K long, Bottom-K long, and
  Top-minus-Bottom diagnostic metrics.
* ``aggregate_summary.json`` — across-window summary statistics.
* ``evidence_manifest.json`` — diagnostic-only manifest.

Labels:
  *Top-K long-only*    → executable-style research portfolio.
  *Bottom-K long-only* → cost-aware, ranked-by-negated-score.
  *Top-K-minus-Bottom-K* → diagnostic only; not trade-ready.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.benchmark_aware_topk import evaluate_benchmark_aware_topk
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerFeatureGroup,
    RankerGridCandidate,
)
from src.research.rolling_windows import (
    filter_windows_by_available_range,
    half_year_rolling_windows,
    purge_training_tail,
)
from src.research.stable_signal_blend import BlendWeight, build_two_signal_blend

# ── frozen #86 best configuration (same as run_best_blend_universe_robustness) ─
FROZEN_FEATURE_GROUP = RankerFeatureGroup(
    name="momentum_volatility_volume",
    expressions=(
        "$close/Ref($close,5)-1",
        "$close/Ref($close,10)-1",
        "$close/Ref($close,20)-1",
        "Std($close/Ref($close,1)-1,10)",
        "Std($close/Ref($close,1)-1,20)",
        "$volume/Ref($volume,10)-1",
        "$volume/Mean($volume,20)-1",
    ),
)
FROZEN_CALIBRATION = RankerCalibration(
    n_gain_bins=5,
    num_boost_round=100,
    num_leaves=31,
    min_data_in_leaf=10,
    learning_rate=0.05,
)
FROZEN_RANKER = RankerGridCandidate(
    feature_group=FROZEN_FEATURE_GROUP,
    calibration=FROZEN_CALIBRATION,
)
FROZEN_BLEND_WEIGHT = BlendWeight(ranker_weight=0.50, momentum_weight=0.50)

# ── helpers ──────────────────────────────────────────────────────────────────


def _load_session(root: Path, data_root: Path | None = None) -> dict[str, Any]:
    """Load session config, preferring *data_root* when explicitly supplied."""
    config_root = data_root if data_root is not None else root
    path = config_root / "data" / "session_config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "market": "us",
        "symbols": [
            "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN",
            "META", "TSLA", "AVGO", "COST", "NFLX",
        ],
        "benchmark": "QQQ",
        "train_start": "2021-01-01",
        "test_end": "2026-06-18",
        "topk": 3,
    }


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        frame = frame.swaplevel().sort_index()
    return frame


def _init_qlib(market: str, provider_uri: str) -> None:
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market=market,
            provider_uri_default=provider_uri,
        )
    )


# ── per-window evaluation ────────────────────────────────────────────────────


def _evaluate_window(
    window: Any,
    symbols: list[str],
    benchmark: str,
    market: str,
    topk: int,
    expression_columns: dict[str, str],
    feature_exprs: list[str],
    baseline_expr: str,
) -> dict[str, Any] | None:
    """Train frozen #86 ranker on window train, evaluate on window test.

    Returns a dict with both the ``BenchmarkAwareTopKResult`` metrics and
    metadata, or ``None`` if the window is skipped.
    """
    from qlib.data import D

    # ── load features and returns ────────────────────────────────────────
    features_all = D.features(
        symbols, feature_exprs,
        start_time=window.train_start, end_time=window.test_end,
    )
    raw_all = D.features(
        symbols, [CANONICAL_10D_RETURN_EXPR],
        start_time=window.train_start, end_time=window.test_end,
    )
    features_all = _normalize_index(features_all).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [expression_columns[expr] for expr in feature_exprs]

    raw_all = _normalize_index(raw_all)
    raw_all.columns = ["return"]
    raw_all.attrs["provenance"] = "raw_forward_return"
    raw_all.attrs["horizon"] = 10
    raw_all.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    dates = features_all.index.get_level_values("datetime")
    train_mask = (dates >= pd.Timestamp(window.train_start)) & (
        dates <= pd.Timestamp(window.train_end)
    )
    test_mask = (dates >= pd.Timestamp(window.test_start)) & (
        dates <= pd.Timestamp(window.test_end)
    )

    features_train, returns_train = purge_training_tail(
        features_all.loc[train_mask].copy(),
        raw_all.loc[train_mask].copy(),
        holding_days=10,
    )
    features_test = features_all.loc[test_mask].copy()
    returns_test = raw_all.loc[test_mask].copy()
    returns_test.attrs.update(raw_all.attrs)

    # ── train frozen ranker ──────────────────────────────────────────────
    cols = [expression_columns[expr] for expr in feature_exprs]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, cols], returns_train
    )
    ranker = fit_lgbm_daily_ranker(
        x_rank, y_rank, groups,
        n_gain_bins=FROZEN_CALIBRATION.n_gain_bins,
        params=FROZEN_CALIBRATION.params(),
        num_boost_round=FROZEN_CALIBRATION.num_boost_round,
    )
    ranker_scores = predict_lgbm_daily_ranker(ranker, features_test.loc[:, cols])

    # ── historical momentum baseline ─────────────────────────────────────
    momentum = D.features(
        symbols, [baseline_expr],
        start_time=window.test_start, end_time=window.test_end,
    )
    momentum = _normalize_index(momentum)
    momentum.columns = ["score"]
    momentum.attrs["provenance"] = "factor_baseline"
    momentum.attrs["expression"] = baseline_expr

    # ── build 50/50 blend (frozen #86) ───────────────────────────────────
    blend = build_two_signal_blend(
        ranker_scores, momentum,
        weight=FROZEN_BLEND_WEIGHT,
        invert_momentum=True,
    )

    # ── load benchmark returns (QQQ) ─────────────────────────────────────
    bench_raw = D.features(
        [benchmark], [CANONICAL_10D_RETURN_EXPR],
        start_time=window.test_start, end_time=window.test_end,
    )
    if isinstance(bench_raw.index, pd.MultiIndex):
        bench_raw = bench_raw.xs(benchmark, level="instrument")
    benchmark_returns = bench_raw.copy()
    if isinstance(benchmark_returns, pd.DataFrame):
        benchmark_returns.columns = ["return"]
    benchmark_returns.attrs["provenance"] = "raw_forward_return"
    benchmark_returns.attrs["horizon"] = 10
    benchmark_returns.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    if benchmark_returns.empty:
        print(f"  [skip] {window.label}: empty benchmark returns")
        return None

    # ── evaluate ─────────────────────────────────────────────────────────
    result = evaluate_benchmark_aware_topk(
        blend,
        returns_test,
        benchmark_returns,
        top_n=topk,
        rebalance_days=10,
    )

    return {
        "window": window.to_dict(),
        "candidate": "blend:ranker_momentum:momentum_volatility_volume:"
                     "gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5",
        "result": result.to_dict(),
    }


# ── main ─────────────────────────────────────────────────────────────────────


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    first_test_year: int = 2024,
    last_test_year: int = 2026,
) -> dict[str, Any]:
    session = _load_session(root, data_root=data_root)
    market = str(session["market"])
    symbols = list(session["symbols"])
    benchmark = str(session["benchmark"])
    train_start = str(session["train_start"])
    test_end = str(session["test_end"])
    requested_topk = int(session.get("topk", 3))

    if len(symbols) < 2:
        raise ValueError("at least two symbols required")
    topk = min(requested_topk, len(symbols) - 1)
    if topk <= 0:
        raise ValueError("topk must be positive")

    # ── data root resolution ─────────────────────────────────────────────
    effective_data_root = data_root if data_root is not None else root
    provider_uri = str(effective_data_root / "data" / "watchlist")

    _init_qlib(market, provider_uri)
    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(start_time=train_start, end_time=test_end, freq="day")
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in configured session range")

    available_end = min(
        pd.Timestamp(test_end), calendar.max()
    ).strftime("%Y-%m-%d")

    windows = filter_windows_by_available_range(
        half_year_rolling_windows(
            start_year=int(train_start[:4]),
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        ),
        available_start=train_start,
        available_end=available_end,
    )
    if not windows:
        raise ValueError("no complete rolling windows covered by available Qlib range")

    # ── feature expressions ──────────────────────────────────────────────
    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    dollar = chr(36)
    baseline_expr = f"{dollar}close/Ref({dollar}close,10)-1"

    # ── output directories ───────────────────────────────────────────────
    base_out = root / "artifacts" / "evidence" / "benchmark_aware_topk"
    per_window_dir = base_out / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)

    # ── per-window loop ──────────────────────────────────────────────────
    print("\nFrozen #86 benchmark-aware Top-K evidence")
    print(f"  market:             {market}")
    print(f"  symbols:            {symbols}")
    print(f"  benchmark:          {benchmark}")
    print(f"  topk:               {topk}")
    print("  blend:              50/50 ranker + inverted momentum")
    print(f"  data root:          {effective_data_root}")
    print(f"  windows:            {len(windows)} "
          f"({first_test_year}–{last_test_year})")
    print(f"  output:             {base_out}")
    print()

    window_results: list[dict[str, Any]] = []
    for window in windows:
        print(f"  {window.label}  train={window.train_start}→{window.train_end}  "
              f"test={window.test_start}→{window.test_end}")
        # Fail closed: any per-window error propagates as a hard failure
        per_window = _evaluate_window(
            window, symbols, benchmark, market, topk,
            expression_columns, feature_exprs, baseline_expr,
        )

        if per_window is None:
            continue

        # Write per-window artifact
        window_path = per_window_dir / f"{window.label}.json"
        window_path.write_text(
            json.dumps(per_window, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

        # Print key metrics
        top = per_window["result"]["top_k_long"]
        tmb = per_window["result"]["top_minus_bottom"]
        print(f"    Top-K long:      ret={top['total_return']:.4f}  "
              f"xs={top['excess_return']:.4f}  SR={top['sharpe_ratio']:.2f}  "
              f"MDD={top['max_drawdown']:.4f}")
        print(f"    Top-minus-Bottom: ret={tmb['total_return']:.4f}  "
              f"SR={tmb['sharpe_ratio']:.2f}  MDD={tmb['max_drawdown']:.4f}  "
              f"[diagnostic only]")

        window_results.append(per_window)

    # Fail closed: zero successful windows is an error, not a skipped success
    if not window_results:
        raise ValueError("no windows produced valid results")

    # ── aggregate summary ────────────────────────────────────────────────
    top_excess_returns = [
        r["result"]["top_k_long"]["excess_return"] for r in window_results
    ]
    top_sharpes = [
        r["result"]["top_k_long"]["sharpe_ratio"] for r in window_results
    ]
    top_mdds = [
        r["result"]["top_k_long"]["max_drawdown"] for r in window_results
    ]
    tmb_sharpes = [
        r["result"]["top_minus_bottom"]["sharpe_ratio"] for r in window_results
    ]
    tmb_mdds = [
        r["result"]["top_minus_bottom"]["max_drawdown"] for r in window_results
    ]
    tmb_total_returns = [
        r["result"]["top_minus_bottom"]["total_return"] for r in window_results
    ]

    # Compounded returns across all windows (chain all period returns)
    all_top_period_returns = [
        pr for r in window_results
        for pr in r["result"]["top_k_long"]["period_returns"]
    ]
    cp = float(np.prod(1.0 + np.asarray(all_top_period_returns, dtype=float)) - 1.0)

    all_bench_period_returns = [
        pr for r in window_results
        for pr in r["result"]["top_k_long"]["benchmark_period_returns"]
    ]
    cb = float(np.prod(1.0 + np.asarray(all_bench_period_returns, dtype=float)) - 1.0)
    ce = (1.0 + cp) / (1.0 + cb) - 1.0

    positive_excess_window_ratio = float(
        np.mean([x > 0 for x in top_excess_returns])
    )

    aggregate = {
        "schema_version": "1.0",
        "candidate": (
            "blend:ranker_momentum:momentum_volatility_volume:"
            "gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5"
        ),
        "frozen_config": "#86 — 50/50 ranker + inverted 10D momentum",
        "market": market,
        "benchmark": benchmark,
        "topk": topk,
        "n_windows_evaluated": len(window_results),
        "n_windows_total": len(windows),
        "research_only": True,
        "trade_ready": False,
        "top_k_long": {
            "label": "executable_style_research_portfolio",
            "research_only": True,
            "trade_ready": False,
            "mean_excess_return": float(np.mean(top_excess_returns)),
            "mean_sharpe_ratio": float(np.mean(top_sharpes)),
            "mean_max_drawdown": float(np.mean(top_mdds)),
            "worst_drawdown": float(min(top_mdds)),
            "positive_excess_window_ratio": positive_excess_window_ratio,
            "compounded_portfolio_return": cp,
            "compounded_benchmark_return": cb,
            "compounded_excess_return": ce,
            "window_excess_returns": top_excess_returns,
        },
        "top_minus_bottom": {
            "label": "research_only_diagnostic",
            "research_only": True,
            "trade_ready": False,
            "mean_sharpe_ratio": float(np.mean(tmb_sharpes)),
            "worst_drawdown": float(min(tmb_mdds)),
            "positive_window_ratio": float(
                np.mean([x > 0 for x in tmb_total_returns])
            ),
            "window_sharpes": tmb_sharpes,
            "caveats": [
                "Top-K-minus-Bottom-K is derived from aligned net period "
                "returns of two independent long-only legs.",
                "It does NOT model borrow availability, borrow cost, "
                "short-sale feasibility, or margin requirements.",
                "It is NOT trade-ready.",
                "Top-K long-only is the stronger research candidate for "
                "any future executable path.",
            ],
        },
    }

    aggregate_path = base_out / "aggregate_summary.json"
    aggregate_path.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # ── evidence manifest ─────────────────────────────────────────────────
    manifest = {
        "schema_version": "1.0",
        "evidence_type": "benchmark_aware_topk",
        "diagnostic_only": True,
        "research_only": True,
        "trade_ready": False,
        "promotion_eligible": False,
        "rationale": (
            "Benchmark-aware Top-K evidence provides OOS portfolio economics "
            "relative to a canonical benchmark. Top-K long-only is labelled "
            "as executable-style research; Top-K-minus-Bottom-K is explicitly "
            "diagnostic-only. Lifecycle promotion requires a spec-bound run "
            "and canonical PromotionDecision."
        ),
        "n_windows_evaluated": len(window_results),
        "n_windows_total": len(windows),
        "frozen_candidate": "#86 — 50/50 momentum_volatility_volume ranker + "
                           "inverted 10D momentum",
        "output_labels": {
            "top_k_long": "executable_style_research_portfolio",
            "bottom_k_long": "cost_aware_bottom_k_long_only",
            "top_minus_bottom": "research_only_diagnostic — NOT trade-ready",
        },
    }
    manifest_path = base_out / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return {
        "aggregate_path": str(aggregate_path),
        "manifest_path": str(manifest_path),
        "per_window_dir": str(per_window_dir),
        "aggregate": aggregate,
        "manifest": manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the benchmark-aware Top-K evidence runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Project root directory (for config + output artifacts)",
    )
    parser.add_argument(
        "--data-root", type=Path, default=None,
        help="Separate data root for market data (default: same as --root). "
             "Use when running from a clean worktree with read-only access "
             "to the original workspace data.",
    )
    parser.add_argument(
        "--first-test-year", type=int, default=2024,
        help="First OOS test year",
    )
    parser.add_argument(
        "--last-test-year", type=int, default=2026,
        help="Last OOS test year",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run(
        args.root,
        data_root=args.data_root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
    )
    print(f"\n  aggregate:  {result['aggregate_path']}")
    print(f"  manifest:   {result['manifest_path']}")
    print(f"  per-window: {result['per_window_dir']}")


if __name__ == "__main__":
    main()
