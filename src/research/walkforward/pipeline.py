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


class WalkForwardDataError(ValueError):
    """A declared market session cannot be evaluated without inventing evidence."""


def _simulate_portfolio(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    bench_series: pd.Series,
    sessions: list[str],
    top_k: int,
    friction_per_turnover: float,
    *,
    liquidate_at_end: bool = True,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Daily close-to-close returns, with signals known before the execution close.

    Two preceding closes anchor the first evaluated day: score at t-2 selects
    the basket traded at t-1 close and held until t close. Starting/ending cash
    trades are charged explicitly. Costs are bps per one-way traded NAV.
    """
    if top_k <= 0 or top_k > len(scores.columns) or friction_per_turnover < 0:
        raise WalkForwardDataError("invalid_portfolio_parameters")
    if len(sessions) < 3 or sessions != sorted(set(sessions)):
        raise WalkForwardDataError("invalid_or_insufficient_simulation_sessions")
    if any(s not in scores.index or s not in prices.index or s not in bench_series.index for s in sessions):
        raise WalkForwardDataError("missing_declared_session")
    columns = list(scores.columns)
    score_arr = scores.loc[sessions, columns].to_numpy(dtype=float)
    price_arr = prices.loc[sessions, columns].to_numpy(dtype=float)
    bench_arr = bench_series.reindex(sessions).to_numpy(dtype=float)
    if (not np.isfinite(price_arr).all() or (price_arr <= 0).any()
            or not np.isfinite(bench_arr).all() or (bench_arr <= 0).any()):
        raise WalkForwardDataError("missing_or_invalid_candidate_or_benchmark_price")

    gross_returns: list[float] = []
    net_returns: list[float] = []
    turnovers: list[float] = []
    benchmark_returns: list[float] = []
    pretrade_weights: dict[int, float] = {}

    for i in range(2, len(sessions)):
        prior_scores = score_arr[i - 2]
        available = np.isfinite(prior_scores)
        if int(available.sum()) < top_k:
            raise WalkForwardDataError(f"insufficient_ranked_candidates_at_{sessions[i - 2]}")
        selected = np.argsort(np.where(available, prior_scores, -np.inf))[-top_k:]
        target = {int(j): 1.0 / top_k for j in selected}
        assets = set(pretrade_weights) | set(target)
        bought = sum(max(target.get(j, 0.0) - pretrade_weights.get(j, 0.0), 0.0) for j in assets)
        sold = sum(max(pretrade_weights.get(j, 0.0) - target.get(j, 0.0), 0.0) for j in assets)
        turnover = max(bought, sold)  # one-way traded NAV, incl. first purchase from cash
        asset_returns = price_arr[i, selected] / price_arr[i - 1, selected] - 1.0
        gross = float(np.mean(asset_returns))
        benchmark = float(bench_arr[i] / bench_arr[i - 1] - 1.0)
        if not np.isfinite(gross) or gross <= -1.0 or not np.isfinite(benchmark):
            raise WalkForwardDataError(f"invalid_realized_return_at_{sessions[i]}")
        net = gross - turnover * friction_per_turnover
        if net <= -1.0:
            raise WalkForwardDataError(f"invalid_net_return_at_{sessions[i]}")
        pretrade_weights = {
            int(j): float(target[int(j)] * (1.0 + ret) / (1.0 + gross))
            for j, ret in zip(selected, asset_returns, strict=True)
        }
        gross_returns.append(gross)
        net_returns.append(net)
        turnovers.append(turnover)
        benchmark_returns.append(benchmark)

    if liquidate_at_end:
        # Fold boundary convention: liquidate to cash at final close; next
        # independent fold buys from cash. Never omit the closing trade cost.
        exit_turnover = sum(pretrade_weights.values())
        turnovers[-1] += exit_turnover
        net_returns[-1] -= exit_turnover * friction_per_turnover
        if net_returns[-1] <= -1.0:
            raise WalkForwardDataError("invalid_liquidation_return")

    if len(net_returns) != len(sessions) - 2:
        raise WalkForwardDataError("simulation_session_count_mismatch")
    return gross_returns, net_returns, turnovers, benchmark_returns

def evaluate_walkforward_fold(
    fold: WalkForwardFold,
    config: WalkForwardConfig,
    root: Path | None = None,
) -> FoldResult:
    """Select on purged IS data; execute every declared OOS session without filling gaps."""
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()
    candidates = list(config.symbols)
    all_symbols = tuple(sorted(set((*config.symbols, config.benchmark))))
    if not (fold.train_start <= fold.train_end <= fold.train_cutoff
            and fold.train_end < fold.test_start <= fold.test_end <= fold.test_cutoff):
        return FoldResult(fold_id=fold.fold_id, status="blocked", blocked_reasons=("invalid_fold_dates",))

    def blocked(reason: str, **values: Any) -> FoldResult:
        return FoldResult(fold_id=fold.fold_id, status="blocked", blocked_reasons=(reason,), **values)

    train_req = DataSliceRequest(
        market=config.market, pool_id=config.pool_id, symbols=all_symbols,
        start_date=fold.train_start, end_date=fold.train_end,
        as_of_cutoff=fold.train_cutoff, price_mode=config.price_mode,
    )
    train_res = get_research_data_slice(train_req, root=repo_root)
    if not train_res.is_ready or train_res.data is None:
        reasons = _format_blocked_reasons(train_res.receipt.get("blocked_reasons"))
        return blocked(",".join(reasons) or "train_slice_unavailable")

    train_df = train_res.data
    z_rev_train, z_vol_train, train_prices = _compute_raw_features(train_df, candidates)
    train_bench = train_prices[config.benchmark]
    train_sessions = sorted(s for s in train_prices.index if fold.train_start <= s <= fold.train_end)
    purge = fold.purged_margin_days
    if purge < 0 or len(train_sessions) <= purge + 43:
        return blocked("insufficient_training_sessions_for_purge_and_feature_warmup")
    training_sessions = train_sessions[:-purge] if purge else train_sessions
    purged_sessions = train_sessions[-purge:] if purge else []
    purged_rows = int(train_df["time"].isin(purged_sessions).sum())
    # 20 returns require 21 bars; score t-2 must precede the t-1 execution close.
    selection_sessions = training_sessions[20:]
    friction = (config.cost_bps + config.slippage_bps) / 10000.0
    if not np.isfinite(friction) or friction < 0:
        return blocked("invalid_transaction_friction")
    param_rev = config.param_grid.get("w_rev", ())
    param_vol = config.param_grid.get("w_vol", ())
    param_k = config.param_grid.get("top_k", ())
    if not param_rev or not param_vol or not param_k:
        return blocked("empty_parameter_grid")

    best_sharpe = -float("inf")
    best_params: dict[str, Any] = {}
    try:
        for w_r in param_rev:
            for w_v in param_vol:
                trial_scores = float(w_r) * z_rev_train - float(w_v) * z_vol_train
                for raw_k in param_k:
                    if not float(raw_k).is_integer():
                        raise WalkForwardDataError("noninteger_top_k")
                    top_k = int(raw_k)
                    _, net, _, _ = _simulate_portfolio(
                        trial_scores, train_prices, train_bench, selection_sessions, top_k, friction
                    )
                    if len(net) < 20:
                        raise WalkForwardDataError("insufficient_in_sample_return_sessions")
                    net_arr = np.asarray(net, dtype=float)
                    vol = float(np.std(net_arr) * np.sqrt(252))
                    if vol <= 0:
                        continue
                    sharpe = float(np.mean(net_arr) * 252 / vol)
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = {"w_rev": float(w_r), "w_vol": float(w_v), "top_k": top_k}
    except (WalkForwardDataError, ValueError, TypeError) as exc:
        return blocked(f"in_sample_data_blocked:{exc}")

    if not best_params:
        return blocked("no_valid_in_sample_parameter_selection")
    optimal_scores = best_params["w_rev"] * z_rev_train - best_params["w_vol"] * z_vol_train
    fwd_5d = train_prices[candidates].shift(-5) / train_prices[candidates] - 1.0
    daily_ics: list[float] = []
    for t in training_sessions:
        if t not in optimal_scores.index or t not in fwd_5d.index:
            continue
        sc = optimal_scores.loc[t].dropna()
        fw = fwd_5d.loc[t].dropna()
        common = sc.index.intersection(fw.index)
        if len(common) >= 4:
            daily_ics.append(_compute_spearman_ic(sc[common].to_numpy(), fw[common].to_numpy()))
    in_sample_ic = float(np.mean(daily_ics)) if daily_ics else 0.0

    test_req = DataSliceRequest(
        market=config.market, pool_id=config.pool_id, symbols=all_symbols,
        start_date=fold.test_start, end_date=fold.test_end,
        as_of_cutoff=fold.test_cutoff, price_mode=config.price_mode,
    )
    test_res = get_research_data_slice(test_req, root=repo_root)
    if not test_res.is_ready or test_res.data is None:
        reasons = _format_blocked_reasons(test_res.receipt.get("blocked_reasons"))
        return blocked(",".join(reasons) or "test_slice_unavailable",
                       train_data_hash=train_res.receipt["data_hash"],
                       purged_rows_count=purged_rows, selected_parameters=best_params)

    test_df = test_res.data
    full_df = pd.concat([train_df, test_df], ignore_index=True)
    if full_df.duplicated(subset=["symbol", "time"]).any():
        return blocked("overlapping_train_test_rows")
    z_rev, z_vol, prices = _compute_raw_features(full_df, candidates)
    scores = best_params["w_rev"] * z_rev - best_params["w_vol"] * z_vol
    test_sessions = sorted(s for s in prices.index if fold.test_start <= s <= fold.test_end)
    if len(test_sessions) < 5 or len(train_sessions) < 2 or train_sessions[-1] >= test_sessions[0]:
        return blocked("insufficient_or_nonchronological_oos_sessions")
    # Two preceding training closes provide a causally executable first OOS trade.
    simulated_sessions = [*train_sessions[-2:], *test_sessions]
    try:
        gross, net, turnovers, bench = _simulate_portfolio(
            scores, prices, prices[config.benchmark], simulated_sessions,
            best_params["top_k"], friction,
        )
        _, gross_sensitivity, _, _ = _simulate_portfolio(
            scores, prices, prices[config.benchmark], simulated_sessions,
            best_params["top_k"], 0.0,
        )
        _, stress_sensitivity, _, _ = _simulate_portfolio(
            scores, prices, prices[config.benchmark], simulated_sessions,
            best_params["top_k"], 0.0015,
        )
    except WalkForwardDataError as exc:
        return blocked(f"oos_data_blocked:{exc}",
                       train_data_hash=train_res.receipt["data_hash"],
                       test_data_hash=test_res.receipt["data_hash"],
                       purged_rows_count=purged_rows, selected_parameters=best_params)

    if not (len(net) == len(gross) == len(bench) == len(test_sessions)):
        return blocked("incomplete_oos_return_coverage")
    net_arr, gross_arr, bench_arr = (np.asarray(v, dtype=float) for v in (net, gross, bench))
    cum_net = float(np.prod(1.0 + net_arr) - 1.0)
    cum_gross = float(np.prod(1.0 + gross_arr) - 1.0)
    cum_bench = float(np.prod(1.0 + bench_arr) - 1.0)
    ann_vol = float(np.std(net_arr) * np.sqrt(252))
    gross_vol = float(np.std(gross_arr) * np.sqrt(252))
    nav = np.concatenate(([1.0], np.cumprod(1.0 + net_arr)))
    max_dd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))

    return FoldResult(
        fold_id=fold.fold_id, status="ready",
        train_data_hash=train_res.receipt["data_hash"], test_data_hash=test_res.receipt["data_hash"],
        train_source_manifest_hashes=train_res.receipt["source_manifest_hashes"],
        test_source_manifest_hashes=test_res.receipt["source_manifest_hashes"],
        train_row_count=train_res.receipt["total_rows"], test_row_count=test_res.receipt["total_rows"],
        purged_rows_count=purged_rows, selected_parameters=best_params,
        in_sample_best_sharpe=round(best_sharpe, 4), in_sample_ic_mean=round(in_sample_ic, 4),
        out_of_sample_gross_return=round(cum_gross, 4),
        out_of_sample_net_return=round(cum_net, 4),
        benchmark_cumulative_return=round(cum_bench, 4),
        out_of_sample_net_excess_return=round(cum_net - cum_bench, 4),
        annualized_volatility=round(ann_vol, 4),
        sharpe_ratio=round(float(np.mean(net_arr) * 252 / (ann_vol + 1e-8)), 4),
        gross_sharpe_ratio=round(float(np.mean(gross_arr) * 252 / (gross_vol + 1e-8)), 4),
        max_drawdown=round(max_dd, 4),
        win_rate=round(float(np.mean(net_arr > 0)), 4),
        turnover_ratio=round(float(np.mean(turnovers)), 4),
        total_cost_drag=round(cum_gross - cum_net, 4),
        cost_sensitivity={
            "0_bps_gross": round(float(np.prod(1.0 + gross_sensitivity) - 1.0), 4),
            "standard_config": round(cum_net, 4),
            "15_bps_stress": round(float(np.prod(1.0 + stress_sensitivity) - 1.0), 4),
        },
        daily_sessions=tuple(test_sessions), daily_net_returns=tuple(net),
        daily_benchmark_returns=tuple(bench),
        pit_limitations=DEFAULT_PIT_LIMITATIONS,
    )

def _study_provenance(config: WalkForwardConfig) -> tuple[str, dict[str, str]]:
    """Bind the exact declared experiment and source bytes to the study receipt."""
    serialized = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    src_root = Path(__file__).resolve().parents[2]
    sources = {
        "walkforward_pipeline": Path(__file__),
        "walkforward_contracts": Path(__file__).with_name("contracts.py"),
        "research_data_slice": src_root / "data" / "research_slice.py",
    }
    hashes = {name: hashlib.sha256(source.read_bytes()).hexdigest() for name, source in sources.items()}
    return hashlib.sha256(serialized).hexdigest(), hashes

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
    config_hash, code_source_sha256 = _study_provenance(cfg)
    blocked_folds = [f for f in fold_results if f.status != "ready"]
    if blocked_folds:
        study_status = "blocked"
        blocked_reasons = tuple(
            f"Fold '{f.fold_id}' blocked: {', '.join(_format_blocked_reasons(f.blocked_reasons))}"
            for f in blocked_folds
        )
        study_payload = {
            "study_id": cfg.study_id,
            "config_hash": config_hash,
            "code_source_sha256": code_source_sha256,
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
            config_hash=config_hash,
            code_source_sha256=code_source_sha256,
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

    # Each fold restarts/ends in cash; the opening purchase and closing sale are costed.
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

        stitched_trajectory = np.concatenate(([1.0], np.cumprod(1.0 + stitched_arr)))
        stitched_peaks = np.maximum.accumulate(stitched_trajectory)
        stitched_drawdowns = (stitched_trajectory - stitched_peaks) / stitched_peaks
        overall_max_dd = float(np.min(stitched_drawdowns))
    else:
        overall_sharpe = float(np.mean([f.sharpe_ratio for f in fold_results]))
        overall_max_dd = float(min([f.max_drawdown for f in fold_results]))

    # Cost Sensitivity Aggregation
    overall_0bps = float(np.prod([1.0 + f.cost_sensitivity.get("0_bps_gross", 0.0) for f in fold_results]) - 1.0)
    overall_standard = float(np.prod([1.0 + f.cost_sensitivity["standard_config"] for f in fold_results]) - 1.0)
    overall_15bps = float(np.prod([1.0 + f.cost_sensitivity.get("15_bps_stress", 0.0) for f in fold_results]) - 1.0)

    cost_summary = {
        "0_bps_gross": round(overall_0bps, 4),
        "standard_config": round(overall_standard, 4),
        "15_bps_stress": round(overall_15bps, 4),
        "total_cost_drag_standard": round(overall_0bps - overall_standard, 4),
    }

    # Build canonical payload and cryptographic study hash
    study_payload = {
        "study_id": cfg.study_id,
        "config_hash": config_hash,
        "code_source_sha256": code_source_sha256,
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
        config_hash=config_hash,
        code_source_sha256=code_source_sha256,
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
