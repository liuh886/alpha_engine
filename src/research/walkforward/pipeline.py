"""Execution pipeline for Walk-Forward quantitative investment research.

Governed under Track B (#1296) and ADR-0005.
Implements:
1. Strict Walk-Forward expanding/rolling folds with active purged margins.
2. In-sample parameter optimization and freezing (Train -> Select -> Freeze -> OOS).
3. Transaction cost, slippage, and turnover drag sensitivity analysis.
4. Direct integration with governed get_research_data_slice().
5. Fail-closed fold integrity (any fold block halts overall study publication).
6. Continuous daily-stitched portfolio Sharpe and continuous maximum drawdown.
7. Cryptographic sealing of fold metrics and study result digests.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.data.research_slice import (
    DEFAULT_REPO_ROOT,
    DataSliceRequest,
    get_research_data_slice,
)
from src.research.walkforward.contracts import (
    DEFAULT_PIT_LIMITATIONS,
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
    cost_bps=3.0,  # 3 bps commission
    slippage_bps=5.0,  # 5 bps slippage (8 bps total single-turnover friction)
    param_grid={
        "w_rev": (0.5, 1.0, 1.5),
        "w_vol": (0.5, 1.0, 1.5),
        "top_k": (2.0, 3.0),
    },
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


def _format_blocked_reasons(raw_reasons: Any) -> tuple[str, ...]:
    """Normalize raw slice blocker receipts into strings."""
    formatted: list[str] = []
    if isinstance(raw_reasons, (list, tuple)):
        for r in raw_reasons:
            if isinstance(r, dict):
                code = r.get("code") or r.get("reason") or str(r)
                formatted.append(str(code))
            else:
                formatted.append(str(r))
    elif raw_reasons:
        formatted.append(str(raw_reasons))
    return tuple(formatted)


def _compute_spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Spearman rank correlation using scipy.stats.spearmanr.

    Handles degenerate cases: constant inputs, NaN values, or < 3 samples return 0.0.
    """
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = spearmanr(x, y)
        stat = getattr(res, "statistic", getattr(res, "correlation", None))
        if stat is None or np.isnan(stat):
            return 0.0
        return float(stat)


def _compute_raw_features(
    df: pd.DataFrame,
    candidate_symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute standardized 5-day reversal and 20-day realized volatility z-scores."""
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

    return z_rev, z_vol, pivoted


def _simulate_portfolio(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    bench_series: pd.Series,
    sessions: list[str],
    top_k: int,
    friction_per_turnover: float,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Simulate daily execution strictly from session t-1 signal to session t realization (vectorized)."""
    valid_sessions = [s for s in sessions if s in scores.index and s in prices.index]
    if len(valid_sessions) < 2:
        return [], [], [], []

    # Pre-slice to numpy arrays for millisecond execution
    col_names = list(scores.columns)
    score_arr = scores.loc[valid_sessions].to_numpy()
    price_arr = prices.loc[valid_sessions, col_names].to_numpy()
    bench_reindexed = bench_series.reindex(valid_sessions).to_numpy()

    daily_gross_returns: list[float] = []
    daily_net_returns: list[float] = []
    daily_turnovers: list[float] = []
    daily_bench_returns: list[float] = []

    prev_top_set: set[int] = set()

    for i in range(1, len(valid_sessions)):
        prev_scores = score_arr[i - 1]
        valid_mask = ~np.isnan(prev_scores)
        valid_cnt = int(np.sum(valid_mask))
        if valid_cnt < top_k:
            continue

        # Top k assets selected based on session t-1 signal
        if valid_cnt == len(prev_scores):
            top_indices = np.argsort(prev_scores)[-top_k:]
        else:
            masked_scores = np.where(valid_mask, prev_scores, -1e9)
            top_indices = np.argsort(masked_scores)[-top_k:]

        top_set = set(top_indices)

        # Turnover calculation
        if prev_top_set:
            turnover = len(top_set - prev_top_set) / float(top_k)
        else:
            turnover = 1.0
        daily_turnovers.append(turnover)
        prev_top_set = top_set

        # Realized portfolio return from session t-1 to t
        prev_p = price_arr[i - 1, top_indices]
        curr_p = price_arr[i, top_indices]
        gross_ret = float(np.mean((curr_p / prev_p) - 1.0))
        cost_drag = turnover * friction_per_turnover
        net_ret = gross_ret - cost_drag

        daily_gross_returns.append(gross_ret)
        daily_net_returns.append(net_ret)

        # Benchmark return
        prev_b = bench_reindexed[i - 1]
        curr_b = bench_reindexed[i]
        if not np.isnan(prev_b) and not np.isnan(curr_b) and prev_b != 0:
            bench_ret = float((curr_b / prev_b) - 1.0)
        else:
            bench_ret = 0.0
        daily_bench_returns.append(bench_ret)

    return daily_gross_returns, daily_net_returns, daily_turnovers, daily_bench_returns


def evaluate_walkforward_fold(
    fold: WalkForwardFold,
    config: WalkForwardConfig,
    root: Path | None = None,
) -> FoldResult:
    """Evaluate one Walk-Forward fold: In-Sample selection, Purge execution, and OOS simulation."""
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
            blocked_reasons=_format_blocked_reasons(train_res.receipt.get("blocked_reasons", ["train_slice_unavailable"])),
        )

    # 2. In-sample Purged Margin Execution
    train_df = train_res.data
    z_rev_train, z_vol_train, train_prices = _compute_raw_features(train_df, candidates)
    train_bench = train_df[train_df["symbol"] == config.benchmark].pivot(index="time", columns="symbol", values="close")[config.benchmark]

    all_train_sessions = sorted([t for t in train_prices.index if fold.train_start <= t <= fold.train_end])
    purged_margin = max(0, fold.purged_margin_days)
    if purged_margin > 0 and len(all_train_sessions) > purged_margin:
        effective_train_sessions = all_train_sessions[:-purged_margin]
        purged_sessions = all_train_sessions[-purged_margin:]
        purged_rows_count = len(train_df[train_df["time"].isin(purged_sessions)])
    else:
        effective_train_sessions = all_train_sessions
        purged_rows_count = 0

    # 3. In-Sample Parameter Selection (Grid Search over IS Purged Window)
    standard_friction = (config.cost_bps + config.slippage_bps) / 10000.0
    best_sharpe = -999.0
    best_params: dict[str, Any] = {"w_rev": 1.0, "w_vol": 1.0, "top_k": 2}

    w_rev_candidates = config.param_grid.get("w_rev", (1.0,))
    w_vol_candidates = config.param_grid.get("w_vol", (1.0,))
    top_k_candidates = [int(k) for k in config.param_grid.get("top_k", (2.0,))]

    for w_r in w_rev_candidates:
        for w_v in w_vol_candidates:
            trial_score = (w_r * z_rev_train) - (w_v * z_vol_train)
            for k in top_k_candidates:
                _, net_rets, _, _ = _simulate_portfolio(
                    scores=trial_score,
                    prices=train_prices,
                    bench_series=train_bench,
                    sessions=effective_train_sessions,
                    top_k=k,
                    friction_per_turnover=standard_friction,
                )
                if len(net_rets) > 20:
                    arr = np.array(net_rets)
                    vol = float(np.std(arr) * np.sqrt(252))
                    mean_ret = float(np.mean(arr)) * 252.0
                    trial_sharpe = float(mean_ret / (vol + 1e-8)) if vol > 0 else -999.0
                    if trial_sharpe > best_sharpe:
                        best_sharpe = trial_sharpe
                        best_params = {"w_rev": float(w_r), "w_vol": float(w_v), "top_k": int(k)}

    # 4. In-Sample Spearman IC (on optimal factor scores across effective IS window)
    optimal_train_scores = (best_params["w_rev"] * z_rev_train) - (best_params["w_vol"] * z_vol_train)
    fwd_5d_ret = (train_prices[candidates].shift(-5) / train_prices[candidates]) - 1.0

    daily_ics: list[float] = []
    for t in effective_train_sessions:
        if t in optimal_train_scores.index and t in fwd_5d_ret.index:
            sc = optimal_train_scores.loc[t].dropna()
            fwd = fwd_5d_ret.loc[t].dropna()
            common = sc.index.intersection(fwd.index)
            if len(common) >= 4:
                ic = _compute_spearman_ic(sc[common].to_numpy(), fwd[common].to_numpy())
                daily_ics.append(ic)

    in_sample_ic_mean = float(np.mean(daily_ics)) if daily_ics else 0.0

    # 5. Fetch Out-of-Sample Test Slice
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
            blocked_reasons=_format_blocked_reasons(test_res.receipt.get("blocked_reasons", ["test_slice_unavailable"])),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
        )

    # 6. Splicing Warmup Lookback from IS Tail without Future Data Leakage
    test_df = test_res.data
    full_df = pd.concat([train_df, test_df], ignore_index=True).drop_duplicates(subset=["symbol", "time"])

    z_rev_full, z_vol_full, full_prices = _compute_raw_features(full_df, candidates)
    bench_series = full_df[full_df["symbol"] == config.benchmark].pivot(index="time", columns="symbol", values="close")[config.benchmark]

    oos_scores = (best_params["w_rev"] * z_rev_full) - (best_params["w_vol"] * z_vol_full)
    test_sessions = sorted([t for t in full_prices.index if fold.test_start <= t <= fold.test_end])
    if len(test_sessions) < 5:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=("insufficient_test_sessions",),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash=test_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=test_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
        )

    # 7. Out-of-Sample Simulation with Selected Frozen Parameters
    daily_gross, daily_net, daily_turnovers, daily_bench = _simulate_portfolio(
        scores=oos_scores,
        prices=full_prices,
        bench_series=bench_series,
        sessions=test_sessions,
        top_k=best_params["top_k"],
        friction_per_turnover=standard_friction,
    )

    # Cost sensitivity runs: 0 bps (gross), 8 bps (standard), 15 bps (stress)
    _, net_0bps, _, _ = _simulate_portfolio(
        scores=oos_scores,
        prices=full_prices,
        bench_series=bench_series,
        sessions=test_sessions,
        top_k=best_params["top_k"],
        friction_per_turnover=0.0,
    )
    _, net_15bps, _, _ = _simulate_portfolio(
        scores=oos_scores,
        prices=full_prices,
        bench_series=bench_series,
        sessions=test_sessions,
        top_k=best_params["top_k"],
        friction_per_turnover=0.0015,
    )

    gross_arr = np.array(daily_gross)
    net_arr = np.array(daily_net)
    bench_arr = np.array(daily_bench)

    cum_gross = float(np.prod(1.0 + gross_arr) - 1.0) if len(gross_arr) > 0 else 0.0
    cum_net = float(np.prod(1.0 + net_arr) - 1.0) if len(net_arr) > 0 else 0.0
    cum_bench = float(np.prod(1.0 + bench_arr) - 1.0) if len(bench_arr) > 0 else 0.0
    net_excess = cum_net - cum_bench

    ann_vol = float(np.std(net_arr) * np.sqrt(252)) if len(net_arr) > 1 else 0.0
    mean_daily_net = float(np.mean(net_arr)) if len(net_arr) > 0 else 0.0
    sharpe_net = float((mean_daily_net * 252.0) / (ann_vol + 1e-8)) if ann_vol > 0 else 0.0

    mean_daily_gross = float(np.mean(gross_arr)) if len(gross_arr) > 0 else 0.0
    gross_vol = float(np.std(gross_arr) * np.sqrt(252)) if len(gross_arr) > 1 else 0.0
    sharpe_gross = float((mean_daily_gross * 252.0) / (gross_vol + 1e-8)) if gross_vol > 0 else 0.0

    # Max Drawdown
    cum_trajectory = np.cumprod(1.0 + net_arr)
    peaks = np.maximum.accumulate(cum_trajectory)
    drawdowns = (cum_trajectory - peaks) / peaks
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

    win_rate = float(np.mean(net_arr > 0)) if len(net_arr) > 0 else 0.0
    mean_turnover = float(np.mean(daily_turnovers)) if daily_turnovers else 0.0

    cum_net_0bps = float(np.prod(1.0 + np.array(net_0bps)) - 1.0) if len(net_0bps) > 0 else 0.0
    cum_net_15bps = float(np.prod(1.0 + np.array(net_15bps)) - 1.0) if len(net_15bps) > 0 else 0.0

    return FoldResult(
        fold_id=fold.fold_id,
        status="ready",
        blocked_reasons=(),
        train_data_hash=train_res.receipt["data_hash"],
        test_data_hash=test_res.receipt["data_hash"],
        train_row_count=train_res.receipt["total_rows"],
        test_row_count=test_res.receipt["total_rows"],
        purged_rows_count=purged_rows_count,
        selected_parameters=best_params,
        in_sample_best_sharpe=round(best_sharpe, 4),
        in_sample_ic_mean=round(in_sample_ic_mean, 4),
        out_of_sample_gross_return=round(cum_gross, 4),
        out_of_sample_net_return=round(cum_net, 4),
        benchmark_cumulative_return=round(cum_bench, 4),
        out_of_sample_net_excess_return=round(net_excess, 4),
        annualized_volatility=round(ann_vol, 4),
        sharpe_ratio=round(sharpe_net, 4),
        gross_sharpe_ratio=round(sharpe_gross, 4),
        max_drawdown=round(max_dd, 4),
        win_rate=round(win_rate, 4),
        turnover_ratio=round(mean_turnover, 4),
        total_cost_drag=round(cum_gross - cum_net, 4),
        cost_sensitivity={
            "0_bps_gross": round(cum_net_0bps, 4),
            "8_bps_standard": round(cum_net, 4),
            "15_bps_stress": round(cum_net_15bps, 4),
        },
        daily_net_returns=tuple(daily_net),
        pit_limitations=DEFAULT_PIT_LIMITATIONS,
    )


def run_walkforward_study(
    config: WalkForwardConfig | None = None,
    root: Path | None = None,
) -> WalkForwardStudyResult:
    """Execute complete Walk-Forward study across declared folds with fail-closed integrity."""
    cfg = config or DEFAULT_WALK_FORWARD_CONFIG
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()

    fold_results: list[FoldResult] = []
    for fold in cfg.folds:
        f_res = evaluate_walkforward_fold(fold, cfg, root=repo_root)
        fold_results.append(f_res)

    # Fail-closed check: ALL declared folds must be ready
    blocked_folds = [f for f in fold_results if f.status != "ready"]
    if blocked_folds:
        study_status = "blocked"
        blocked_reasons = tuple(
            f"Fold '{f.fold_id}' blocked: {', '.join(_format_blocked_reasons(f.blocked_reasons))}"
            for f in blocked_folds
        )
        study_payload = {
            "study_id": cfg.study_id,
            "status": study_status,
            "blocked_reasons": list(blocked_reasons),
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "folds": [f.to_dict() for f in fold_results],
            "overall_oos_gross_return": 0.0,
            "overall_oos_net_return": 0.0,
            "overall_benchmark_cumulative_return": 0.0,
            "overall_oos_net_excess_return": 0.0,
            "overall_oos_sharpe_ratio": 0.0,
            "overall_oos_max_drawdown": 0.0,
            "cost_sensitivity_summary": {},
            "research_only": True,
            "trade_ready": False,
        }
        raw_bytes = json.dumps(study_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        study_hash = hashlib.sha256(raw_bytes).hexdigest()

        return WalkForwardStudyResult(
            study_id=cfg.study_id,
            status=study_status,
            blocked_reasons=blocked_reasons,
            hypothesis_name=cfg.hypothesis_name,
            market=cfg.market,
            pool_id=cfg.pool_id,
            symbols=list(cfg.symbols),
            benchmark=cfg.benchmark,
            folds=fold_results,
            overall_oos_gross_return=0.0,
            overall_oos_net_return=0.0,
            overall_benchmark_cumulative_return=0.0,
            overall_oos_net_excess_return=0.0,
            overall_oos_sharpe_ratio=0.0,
            overall_oos_max_drawdown=0.0,
            cost_sensitivity_summary={},
            study_hash=study_hash,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            pit_limitations=DEFAULT_PIT_LIMITATIONS,
            research_only=True,
            trade_ready=False,
            trade_signal=False,
        )

    # Multiplicative compound returns across contiguous OOS folds
    overall_gross_ret = float(np.prod([1.0 + f.out_of_sample_gross_return for f in fold_results]) - 1.0)
    overall_net_ret = float(np.prod([1.0 + f.out_of_sample_net_return for f in fold_results]) - 1.0)
    overall_bench_ret = float(np.prod([1.0 + f.benchmark_cumulative_return for f in fold_results]) - 1.0)
    overall_net_excess = overall_net_ret - overall_bench_ret

    # Continuous daily stitched net Sharpe and maximum drawdown
    all_oos_daily_nets: list[float] = []
    for f in fold_results:
        all_oos_daily_nets.extend(f.daily_net_returns)

    if len(all_oos_daily_nets) > 1:
        stitched_arr = np.array(all_oos_daily_nets)
        stitched_vol = float(np.std(stitched_arr) * np.sqrt(252))
        stitched_mean = float(np.mean(stitched_arr)) * 252.0
        overall_sharpe = float(stitched_mean / (stitched_vol + 1e-8))

        stitched_trajectory = np.cumprod(1.0 + stitched_arr)
        stitched_peaks = np.maximum.accumulate(stitched_trajectory)
        stitched_drawdowns = (stitched_trajectory - stitched_peaks) / stitched_peaks
        overall_max_dd = float(np.min(stitched_drawdowns))
    else:
        overall_sharpe = float(np.mean([f.sharpe_ratio for f in fold_results]))
        overall_max_dd = float(min([f.max_drawdown for f in fold_results]))

    # Cost Sensitivity Aggregation
    overall_0bps = float(np.prod([1.0 + f.cost_sensitivity.get("0_bps_gross", 0.0) for f in fold_results]) - 1.0)
    overall_8bps = float(np.prod([1.0 + f.cost_sensitivity.get("8_bps_standard", 0.0) for f in fold_results]) - 1.0)
    overall_15bps = float(np.prod([1.0 + f.cost_sensitivity.get("15_bps_stress", 0.0) for f in fold_results]) - 1.0)

    cost_summary = {
        "0_bps_gross": round(overall_0bps, 4),
        "8_bps_standard": round(overall_8bps, 4),
        "15_bps_stress": round(overall_15bps, 4),
        "total_cost_drag_bps_8": round(overall_0bps - overall_8bps, 4),
    }

    # Build canonical payload and cryptographic study hash
    study_payload = {
        "study_id": cfg.study_id,
        "status": "ready",
        "blocked_reasons": [],
        "hypothesis_name": cfg.hypothesis_name,
        "market": cfg.market,
        "pool_id": cfg.pool_id,
        "symbols": list(cfg.symbols),
        "benchmark": cfg.benchmark,
        "folds": [f.to_dict() for f in fold_results],
        "overall_oos_gross_return": round(overall_gross_ret, 4),
        "overall_oos_net_return": round(overall_net_ret, 4),
        "overall_benchmark_cumulative_return": round(overall_bench_ret, 4),
        "overall_oos_net_excess_return": round(overall_net_excess, 4),
        "overall_oos_sharpe_ratio": round(overall_sharpe, 4),
        "overall_oos_max_drawdown": round(overall_max_dd, 4),
        "cost_sensitivity_summary": cost_summary,
        "research_only": True,
        "trade_ready": False,
    }

    raw_bytes = json.dumps(study_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    study_hash = hashlib.sha256(raw_bytes).hexdigest()

    return WalkForwardStudyResult(
        study_id=cfg.study_id,
        status="ready",
        blocked_reasons=(),
        hypothesis_name=cfg.hypothesis_name,
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=list(cfg.symbols),
        benchmark=cfg.benchmark,
        folds=fold_results,
        overall_oos_gross_return=round(overall_gross_ret, 4),
        overall_oos_net_return=round(overall_net_ret, 4),
        overall_benchmark_cumulative_return=round(overall_bench_ret, 4),
        overall_oos_net_excess_return=round(overall_net_excess, 4),
        overall_oos_sharpe_ratio=round(overall_sharpe, 4),
        overall_oos_max_drawdown=round(overall_max_dd, 4),
        cost_sensitivity_summary=cost_summary,
        study_hash=study_hash,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        pit_limitations=DEFAULT_PIT_LIMITATIONS,
        research_only=True,
        trade_ready=False,
        trade_signal=False,
    )
