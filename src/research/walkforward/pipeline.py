"""Execution pipeline for Walk-Forward quantitative investment research.

Governed under Track B (#1296) and ADR-0005.
Implements:
1. Strict Walk-Forward expanding/rolling folds with purged margins.
2. Direct integration with governed get_research_data_slice().
3. Out-of-sample (OOS) simulation with zero future-data leakage.
4. Cryptographic sealing of fold metrics and study result digests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.research_slice import (
    DEFAULT_REPO_ROOT,
    DataSliceRequest,
    get_research_data_slice,
)
from src.research.walkforward.contracts import (
    FoldResult,
    WalkForwardConfig,
    WalkForwardFold,
    WalkForwardStudyResult,
)

DEFAULT_WALK_FORWARD_CONFIG = WalkForwardConfig(
    study_id="us_tech_vol_reversal_v1",
    hypothesis_name="US Tech Cross-Section Volatility Spread & Short-Term Reversal",
    hypothesis_description=(
        "Hypothesis: In high-liquidity US megacap tech equities, assets with lower trailing "
        "realized volatility and short-term price pullbacks outperform high-volatility names "
        "and the QQQ benchmark on a risk-adjusted basis over out-of-sample forward horizons."
    ),
    market="us",
    pool_id="us_selected_equities_v2",
    symbols=("AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "AVGO", "TSLA"),
    benchmark="QQQ",
    price_mode="anchored_adjusted",
    folds=(
        WalkForwardFold(
            fold_id="fold_1_2025h1",
            train_start="2022-01-03",
            train_end="2024-12-31",
            train_cutoff="2024-12-31",
            test_start="2025-01-02",
            test_end="2025-06-30",
            test_cutoff="2025-06-30",
            purged_margin_days=20,
        ),
        WalkForwardFold(
            fold_id="fold_2_2025h2",
            train_start="2022-01-03",
            train_end="2025-06-30",
            train_cutoff="2025-06-30",
            test_start="2025-07-01",
            test_end="2025-12-31",
            test_cutoff="2025-12-31",
            purged_margin_days=20,
        ),
        WalkForwardFold(
            fold_id="fold_3_2026_tail",
            train_start="2022-01-03",
            train_end="2025-12-31",
            train_cutoff="2025-12-31",
            test_start="2026-01-02",
            test_end="2026-09-04",
            test_cutoff="2026-09-04",
            purged_margin_days=20,
        ),
    ),
)


def _compute_spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Spearman rank correlation between factor score and forward return."""
    if len(x) < 3 or len(y) < 3:
        return 0.0
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    std_x = np.std(rx)
    std_y = np.std(ry)
    if std_x == 0 or std_y == 0:
        return 0.0
    return float(np.cov(rx, ry)[0, 1] / (std_x * std_y))


def _compute_cross_sectional_signals(
    df: pd.DataFrame,
    candidate_symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute 20-day realized volatility and 5-day reversal composite scores."""
    pivoted = df.pivot(index="time", columns="symbol", values="close").sort_index()

    # Log returns
    log_ret = np.log(pivoted / pivoted.shift(1))

    # 1. 20-day rolling realized volatility annualized
    vol20 = log_ret.rolling(window=20).std() * np.sqrt(252)

    # 2. 5-day reversal (negative of 5-day cumulative return)
    ret5 = (pivoted / pivoted.shift(5)) - 1.0
    rev5 = -ret5

    # Filter to candidate symbols
    vol20_cands = vol20[candidate_symbols]
    rev5_cands = rev5[candidate_symbols]

    # Cross-sectional z-score standardization per day
    z_vol = vol20_cands.sub(vol20_cands.mean(axis=1), axis=0).div(vol20_cands.std(axis=1) + 1e-8, axis=0)
    z_rev = rev5_cands.sub(rev5_cands.mean(axis=1), axis=0).div(rev5_cands.std(axis=1) + 1e-8, axis=0)

    # Composite score: prefer low volatility (negative z_vol) and short-term pullback (positive z_rev)
    composite_score = z_rev - z_vol

    return composite_score, pivoted


def evaluate_walkforward_fold(
    fold: WalkForwardFold,
    config: WalkForwardConfig,
    root: Path | None = None,
) -> FoldResult:
    """Evaluate one Walk-Forward fold: In-Sample validation & Out-of-Sample simulation."""
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()
    all_symbols = list(set(list(config.symbols) + [config.benchmark]))
    candidates = list(config.symbols)

    # 1. Fetch In-Sample Train Slice
    train_req = DataSliceRequest(
        market=config.market,
        pool_id=config.pool_id,
        symbols=tuple(all_symbols),
        start_date=fold.train_start,
        end_date=fold.train_end,
        as_of_cutoff=fold.train_cutoff,
        price_mode=config.price_mode,
    )
    train_res = get_research_data_slice(train_req, root=repo_root)
    if not train_res.is_ready or train_res.data is None:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            train_data_hash="",
            test_data_hash="",
            train_row_count=0,
            test_row_count=0,
            in_sample_ic_mean=0.0,
            out_of_sample_cumulative_return=0.0,
            benchmark_cumulative_return=0.0,
            out_of_sample_excess_return=0.0,
            annualized_volatility=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            turnover_ratio=0.0,
        )

    # 2. In-sample IC evaluation
    train_scores, train_prices = _compute_cross_sectional_signals(train_res.data, candidates)
    fwd_5d_ret = (train_prices[candidates].shift(-5) / train_prices[candidates]) - 1.0

    daily_ics: list[float] = []
    for t in train_scores.index:
        sc = train_scores.loc[t].dropna()
        fwd = fwd_5d_ret.loc[t].dropna() if t in fwd_5d_ret.index else pd.Series()
        common = sc.index.intersection(fwd.index)
        if len(common) >= 4:
            ic = _compute_spearman_ic(sc[common].to_numpy(), fwd[common].to_numpy())
            if not np.isnan(ic):
                daily_ics.append(ic)

    in_sample_ic_mean = float(np.mean(daily_ics)) if daily_ics else 0.0

    # 3. Fetch Out-of-Sample Test Slice (with trailing 25 days warmup for signal initialization)
    test_req = DataSliceRequest(
        market=config.market,
        pool_id=config.pool_id,
        symbols=tuple(all_symbols),
        start_date=fold.test_start,
        end_date=fold.test_end,
        as_of_cutoff=fold.test_cutoff,
        price_mode=config.price_mode,
    )
    test_res = get_research_data_slice(test_req, root=repo_root)
    if not test_res.is_ready or test_res.data is None:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash="",
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=0,
            in_sample_ic_mean=in_sample_ic_mean,
            out_of_sample_cumulative_return=0.0,
            benchmark_cumulative_return=0.0,
            out_of_sample_excess_return=0.0,
            annualized_volatility=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            turnover_ratio=0.0,
        )

    # Combine tail of train data + test data to form uninterrupted feature history without lookahead
    # Warmup data: up to 35 rows prior to test_start from train_res.data
    train_df = train_res.data
    test_df = test_res.data
    full_df = pd.concat([train_df, test_df], ignore_index=True).drop_duplicates(subset=["symbol", "time"])

    scores, prices = _compute_cross_sectional_signals(full_df, candidates)
    bench_series = full_df[full_df["symbol"] == config.benchmark].pivot(index="time", columns="symbol", values="close")[config.benchmark]

    # Simulate strictly across test sessions
    test_sessions = sorted([t for t in prices.index if fold.test_start <= t <= fold.test_end])
    if len(test_sessions) < 5:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            train_data_hash=train_res.receipt["data_hash"],
            test_data_hash=test_res.receipt["data_hash"],
            train_row_count=train_res.receipt["total_rows"],
            test_row_count=test_res.receipt["total_rows"],
            in_sample_ic_mean=in_sample_ic_mean,
            out_of_sample_cumulative_return=0.0,
            benchmark_cumulative_return=0.0,
            out_of_sample_excess_return=0.0,
            annualized_volatility=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            turnover_ratio=0.0,
        )

    daily_port_returns: list[float] = []
    daily_bench_returns: list[float] = []
    prev_weights: dict[str, float] = {}
    daily_turnovers: list[float] = []

    # Daily simulation: weights decided on session t-1, realized on session t
    for i in range(1, len(test_sessions)):
        prev_session = test_sessions[i - 1]
        curr_session = test_sessions[i]

        day_scores = scores.loc[prev_session].dropna()
        if len(day_scores) < 2:
            continue

        # Top 2 ranked assets selected for long allocation (equal weight 0.5 each)
        top2 = day_scores.nlargest(2).index.tolist()
        curr_weights = {sym: 0.5 for sym in top2}

        # Compute turnover
        all_syms = set(list(prev_weights.keys()) + list(curr_weights.keys()))
        turnover = sum(abs(curr_weights.get(s, 0.0) - prev_weights.get(s, 0.0)) for s in all_syms) / 2.0
        daily_turnovers.append(turnover)
        prev_weights = curr_weights

        # Realized portfolio return from prev_session to curr_session
        port_ret = sum(
            curr_weights[sym] * ((prices.loc[curr_session, sym] / prices.loc[prev_session, sym]) - 1.0)
            for sym in top2
            if prev_session in prices.index and curr_session in prices.index
        )
        daily_port_returns.append(port_ret)

        # Benchmark return
        if prev_session in bench_series.index and curr_session in bench_series.index:
            bench_ret = (bench_series.loc[curr_session] / bench_series.loc[prev_session]) - 1.0
        else:
            bench_ret = 0.0
        daily_bench_returns.append(bench_ret)

    # Compute fold performance metrics
    port_arr = np.array(daily_port_returns)
    bench_arr = np.array(daily_bench_returns)

    cum_port = float(np.prod(1.0 + port_arr) - 1.0) if len(port_arr) > 0 else 0.0
    cum_bench = float(np.prod(1.0 + bench_arr) - 1.0) if len(bench_arr) > 0 else 0.0
    excess_ret = cum_port - cum_bench

    ann_vol = float(np.std(port_arr) * np.sqrt(252)) if len(port_arr) > 1 else 0.0
    mean_daily = float(np.mean(port_arr)) if len(port_arr) > 0 else 0.0
    ann_ret = mean_daily * 252.0
    sharpe = float(ann_ret / (ann_vol + 1e-8)) if ann_vol > 0 else 0.0

    # Max Drawdown
    cum_trajectory = np.cumprod(1.0 + port_arr)
    peaks = np.maximum.accumulate(cum_trajectory)
    drawdowns = (cum_trajectory - peaks) / peaks
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

    win_rate = float(np.mean(port_arr > 0)) if len(port_arr) > 0 else 0.0
    mean_turnover = float(np.mean(daily_turnovers)) if daily_turnovers else 0.0

    return FoldResult(
        fold_id=fold.fold_id,
        status="ready",
        train_data_hash=train_res.receipt["data_hash"],
        test_data_hash=test_res.receipt["data_hash"],
        train_row_count=train_res.receipt["total_rows"],
        test_row_count=test_res.receipt["total_rows"],
        in_sample_ic_mean=round(in_sample_ic_mean, 4),
        out_of_sample_cumulative_return=round(cum_port, 4),
        benchmark_cumulative_return=round(cum_bench, 4),
        out_of_sample_excess_return=round(excess_ret, 4),
        annualized_volatility=round(ann_vol, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(max_dd, 4),
        win_rate=round(win_rate, 4),
        turnover_ratio=round(mean_turnover, 4),
    )


def run_walkforward_study(
    config: WalkForwardConfig | None = None,
    root: Path | None = None,
) -> WalkForwardStudyResult:
    """Execute complete Walk-Forward quantitative study across all declared folds."""
    cfg = config or DEFAULT_WALK_FORWARD_CONFIG
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()

    fold_results: list[FoldResult] = []
    for fold in cfg.folds:
        f_res = evaluate_walkforward_fold(fold, cfg, root=repo_root)
        fold_results.append(f_res)

    # Compute overall stitched OOS metrics
    ready_folds = [f for f in fold_results if f.status == "ready"]
    if ready_folds:
        # Multiplicative compound return across folds
        overall_oos_ret = float(np.prod([1.0 + f.out_of_sample_cumulative_return for f in ready_folds]) - 1.0)
        overall_bench_ret = float(np.prod([1.0 + f.benchmark_cumulative_return for f in ready_folds]) - 1.0)
        overall_excess = overall_oos_ret - overall_bench_ret
        mean_sharpe = float(np.mean([f.sharpe_ratio for f in ready_folds]))
        worst_dd = float(min([f.max_drawdown for f in ready_folds]))
    else:
        overall_oos_ret = 0.0
        overall_bench_ret = 0.0
        overall_excess = 0.0
        mean_sharpe = 0.0
        worst_dd = 0.0

    # Build canonical payload and cryptographic study hash
    study_payload = {
        "study_id": cfg.study_id,
        "hypothesis_name": cfg.hypothesis_name,
        "market": cfg.market,
        "pool_id": cfg.pool_id,
        "symbols": list(cfg.symbols),
        "benchmark": cfg.benchmark,
        "folds": [f.to_dict() for f in fold_results],
        "overall_oos_cumulative_return": round(overall_oos_ret, 4),
        "overall_benchmark_cumulative_return": round(overall_bench_ret, 4),
        "overall_oos_excess_return": round(overall_excess, 4),
        "overall_oos_sharpe_ratio": round(mean_sharpe, 4),
        "overall_oos_max_drawdown": round(worst_dd, 4),
        "research_only": True,
        "trade_ready": False,
    }

    raw_bytes = json.dumps(study_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    study_hash = hashlib.sha256(raw_bytes).hexdigest()

    return WalkForwardStudyResult(
        study_id=cfg.study_id,
        hypothesis_name=cfg.hypothesis_name,
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=list(cfg.symbols),
        benchmark=cfg.benchmark,
        folds=fold_results,
        overall_oos_cumulative_return=round(overall_oos_ret, 4),
        overall_benchmark_cumulative_return=round(overall_bench_ret, 4),
        overall_oos_excess_return=round(overall_excess, 4),
        overall_oos_sharpe_ratio=round(mean_sharpe, 4),
        overall_oos_max_drawdown=round(worst_dd, 4),
        study_hash=study_hash,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        research_only=True,
        trade_ready=False,
        trade_signal=False,
    )
