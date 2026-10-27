"""Execution pipeline for Walk-Forward quantitative investment research.

Governed under Track B (#1296) and ADR-0005.
Implements:
1. Complete OOS session integrity (anchor initialization covering session 1).
2. Strict fail-closed boundary enforcement (no silent skips or zero-fills).
3. Active purged margins with failure when train window <= margin.
4. Institutional-grade portfolio accounting with exact asset weight drift.
5. In-sample parameter optimization and freezing (Train -> Select -> Freeze -> OOS).
6. Comprehensive Experiment Receipt and git commit hash binding.
7. Continuous daily-stitched portfolio Sharpe and continuous maximum drawdown.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from exchange_calendars import get_calendar
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


class SimulationBlockError(Exception):
    """Raised when simulation encounters unrecoverable data integrity violations."""


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


def _get_git_commit(root: Path) -> str:
    """Read current git commit SHA for immutable experiment lineage. Fails closed if unavailable."""
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0 or not res.stdout.strip():
        raise RuntimeError(f"git_commit_unavailable: git rev-parse HEAD failed with code {res.returncode}")
    return res.stdout.strip()


def _get_code_source_sha256(root: Path) -> dict[str, str]:
    """Compute SHA-256 digests of all execution source files for cryptographic provenance."""
    sources = {
        "walkforward_pipeline": (root / "src" / "research" / "walkforward" / "pipeline.py").resolve(),
        "walkforward_contracts": (root / "src" / "research" / "walkforward" / "contracts.py").resolve(),
        "research_data_slice": (root / "src" / "data" / "research_slice.py").resolve(),
    }
    return {
        k: hashlib.sha256(p.read_bytes()).hexdigest()
        for k, p in sorted(sources.items())
    }


def _get_config_hash(cfg: WalkForwardConfig) -> str:
    """Compute deterministic SHA-256 digest of WalkForwardConfig."""
    serialized = json.dumps(cfg.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _get_exchange_calendar(market: str):
    """Retrieve governed exchange calendar for the given market."""
    calendar_name = {"us": "XNYS", "cn": "XSHG"}.get(market)
    if calendar_name is None:
        raise ValueError(f"unsupported_market_for_exchange_calendar: {market}")
    return get_calendar(calendar_name)


def _format_blocked_reasons(raw_reasons: Any) -> tuple[str, ...]:
    """Normalize raw slice blocker receipts into clean strings."""
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
    *,
    liquidate_at_end: bool = True,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Simulate daily execution strictly from session t-1 signal to session t realization.

    Institutional-grade accounting:
    1. At t-1, target weights w_{i, t-1} are set (1/k for top_k assets).
    2. Over (t-1, t], asset i realizes return r_{i, t}.
    3. Portfolio gross return is sum(w_{i, t-1} * r_{i, t}).
    4. At close of session t, asset weights have drifted to:
       w_{i, t}^{drift} = w_{i, t-1} * (1 + r_{i, t}) / (1 + r_{gross, t}).
    5. Turnover to rebalance from drifted weights to new target weights is:
       turnover_t = 0.5 * sum(|w_{i, t}^{target} - w_{i, t}^{drift}|).
    6. Cost drag is turnover_{t-1} * friction_per_turnover.
    7. Net return is r_{gross, t} - cost_drag.

    Fails closed on missing candidate prices, missing benchmark returns, or insufficient candidates.
    """
    if len(sessions) < 2:
        return [], [], [], []

    missing_scores = [s for s in sessions if s not in scores.index]
    if missing_scores:
        raise SimulationBlockError(f"missing_scores_for_sessions: {missing_scores[:3]}")
    missing_prices = [s for s in sessions if s not in prices.index]
    if missing_prices:
        raise SimulationBlockError(f"missing_prices_for_sessions: {missing_prices[:3]}")

    col_names = list(scores.columns)
    num_assets = len(col_names)
    score_arr = scores.loc[sessions].to_numpy()
    price_arr = prices.loc[sessions, col_names].to_numpy()
    bench_reindexed = bench_series.reindex(sessions).to_numpy()

    daily_gross_returns: list[float] = []
    daily_net_returns: list[float] = []
    daily_turnovers: list[float] = []
    daily_bench_returns: list[float] = []

    # Session 0: compute initial target weights from anchor signal
    s0_scores = score_arr[0]
    valid_mask0 = ~np.isnan(s0_scores)
    if int(np.sum(valid_mask0)) < top_k:
        raise SimulationBlockError(
            f"insufficient_candidates_for_top_k: anchor session {sessions[0]} has {int(np.sum(valid_mask0))} valid candidates, require {top_k}"
        )

    masked_s0 = np.where(valid_mask0, s0_scores, -1e9)
    top_indices0 = np.argsort(masked_s0)[-top_k:]
    curr_target_weights = np.zeros(num_assets, dtype=np.float64)
    curr_target_weights[top_indices0] = 1.0 / float(top_k)

    # Initial turnover from cash (all zero weights) is 1.0
    prev_turnover = 1.0

    for i in range(1, len(sessions)):
        prev_p = price_arr[i - 1]
        curr_p = price_arr[i]

        # Fail closed on invalid candidate prices
        if np.any(np.isnan(prev_p)) or np.any(np.isnan(curr_p)) or np.any(prev_p <= 0) or np.any(curr_p <= 0):
            raise SimulationBlockError(
                f"invalid_price_data: session {sessions[i]} price array contains NaN or non-positive value"
            )

        # Asset returns over (session i-1, session i]
        asset_rets = (curr_p / prev_p) - 1.0

        # Portfolio gross return
        gross_ret = float(np.sum(curr_target_weights * asset_rets))

        # Net return after transaction friction to establish position at session i-1
        cost_drag = prev_turnover * friction_per_turnover
        net_ret = gross_ret - cost_drag

        daily_gross_returns.append(gross_ret)
        daily_net_returns.append(net_ret)

        # Benchmark return (fail closed on missing benchmark data)
        prev_b = bench_reindexed[i - 1]
        curr_b = bench_reindexed[i]
        if np.isnan(prev_b) or np.isnan(curr_b) or prev_b <= 0 or curr_b <= 0:
            raise SimulationBlockError(
                f"missing_benchmark_data: session {sessions[i]} benchmark price invalid (prev={prev_b}, curr={curr_b})"
            )
        bench_ret = float((curr_b / prev_b) - 1.0)
        daily_bench_returns.append(bench_ret)

        # Account for asset weight drift at close of session i
        drifted_weights = (curr_target_weights * (1.0 + asset_rets)) / (1.0 + gross_ret)

        # If at final session of interval, record turnover, execute terminal liquidation if requested, and finish
        if i == len(sessions) - 1:
            daily_turnovers.append(prev_turnover)
            if liquidate_at_end:
                closing_turnover = float(np.sum(drifted_weights))
                terminal_cost_drag = closing_turnover * friction_per_turnover
                daily_net_returns[-1] -= terminal_cost_drag
                daily_turnovers[-1] += closing_turnover
            break

        # Compute next target weights from signals at close of session i
        curr_scores = score_arr[i]
        valid_mask_i = ~np.isnan(curr_scores)
        if int(np.sum(valid_mask_i)) < top_k:
            raise SimulationBlockError(
                f"insufficient_candidates_for_top_k: session {sessions[i]} has {int(np.sum(valid_mask_i))} valid candidates, require {top_k}"
            )

        masked_si = np.where(valid_mask_i, curr_scores, -1e9)
        top_indices_i = np.argsort(masked_si)[-top_k:]
        next_target_weights = np.zeros(num_assets, dtype=np.float64)
        next_target_weights[top_indices_i] = 1.0 / float(top_k)

        # Exact turnover to rebalance from drifted weights to new target weights
        rebalance_turnover = float(0.5 * np.sum(np.abs(next_target_weights - drifted_weights)))
        daily_turnovers.append(prev_turnover)

        curr_target_weights = next_target_weights
        prev_turnover = rebalance_turnover

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

    # 2. In-sample Purged Margin Execution (fail closed if train sessions <= margin)
    train_df = train_res.data
    z_rev_train, z_vol_train, train_prices = _compute_raw_features(train_df, candidates)
    train_bench = train_df[train_df["symbol"] == config.benchmark].pivot(index="time", columns="symbol", values="close")[config.benchmark]

    try:
        calendar = _get_exchange_calendar(config.market)
    except Exception as exc:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=(f"unsupported_exchange_calendar: {exc}",),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
        )

    all_train_sessions = sorted([t for t in train_prices.index if fold.train_start <= t <= fold.train_end])
    expected_train_sessions = [
        d.strftime("%Y-%m-%d") for d in calendar.sessions_in_range(fold.train_start, fold.train_end)
    ]
    if all_train_sessions != expected_train_sessions:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=(
                f"missing_or_extra_train_exchange_sessions: expected {len(expected_train_sessions)}, got {len(all_train_sessions)}",
            ),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
        )

    purged_margin = max(0, fold.purged_margin_days)
    if purged_margin > 0:
        if len(all_train_sessions) <= purged_margin:
            return FoldResult(
                fold_id=fold.fold_id,
                status="blocked",
                blocked_reasons=("insufficient_train_sessions_for_purged_margin",),
                train_data_hash=train_res.receipt["data_hash"],
                train_row_count=train_res.receipt["total_rows"],
            )
        effective_train_sessions = all_train_sessions[:-purged_margin]
        purged_sessions = all_train_sessions[-purged_margin:]
    else:
        effective_train_sessions = list(all_train_sessions)
        purged_sessions = []
    purged_rows_count = len(train_df[train_df["time"].isin(purged_sessions)])

    # Exclude technical indicator warmup sessions (20-day volatility / 5-day reversal)
    valid_score_sessions = set(z_rev_train.dropna().index.intersection(z_vol_train.dropna().index))
    train_sim_sessions = [s for s in effective_train_sessions if s in valid_score_sessions]
    if len(train_sim_sessions) < 2:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=("insufficient_train_sessions_after_warmup",),
            train_data_hash=train_res.receipt["data_hash"],
            train_row_count=train_res.receipt["total_rows"],
            purged_rows_count=purged_rows_count,
        )

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
                try:
                    _, net_rets, _, _ = _simulate_portfolio(
                        scores=trial_score,
                        prices=train_prices,
                        bench_series=train_bench,
                        sessions=train_sim_sessions,
                        top_k=k,
                        friction_per_turnover=standard_friction,
                    )
                except SimulationBlockError:
                    continue
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
    for t in train_sim_sessions:
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

    # Session Integrity: verify exchange calendar coverage and identify the anchor session prior to test_start
    expected_test_sessions = [
        d.strftime("%Y-%m-%d") for d in calendar.sessions_in_range(fold.test_start, fold.test_end)
    ]
    test_sessions = sorted([t for t in full_prices.index if fold.test_start <= t <= fold.test_end])
    if test_sessions != expected_test_sessions:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=(
                f"missing_or_extra_oos_exchange_sessions: expected {len(expected_test_sessions)}, got {len(test_sessions)}",
            ),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash=test_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=test_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
        )

    prior_sessions = sorted([t for t in full_prices.index if t < fold.test_start and t <= fold.train_cutoff])
    if not prior_sessions:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=("missing_prior_anchor_session",),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash=test_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=test_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
        )

    anchor_session = prior_sessions[-1]
    simulation_sessions = [anchor_session] + test_sessions

    # 7. Out-of-Sample Simulation with Selected Frozen Parameters
    try:
        daily_gross, daily_net, daily_turnovers, daily_bench = _simulate_portfolio(
            scores=oos_scores,
            prices=full_prices,
            bench_series=bench_series,
            sessions=simulation_sessions,
            top_k=best_params["top_k"],
            friction_per_turnover=standard_friction,
        )
        _, net_0bps, _, _ = _simulate_portfolio(
            scores=oos_scores,
            prices=full_prices,
            bench_series=bench_series,
            sessions=simulation_sessions,
            top_k=best_params["top_k"],
            friction_per_turnover=0.0,
        )
        _, net_15bps, _, _ = _simulate_portfolio(
            scores=oos_scores,
            prices=full_prices,
            bench_series=bench_series,
            sessions=simulation_sessions,
            top_k=best_params["top_k"],
            friction_per_turnover=0.0015,
        )
    except SimulationBlockError as err:
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=(str(err),),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash=test_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=test_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
        )

    # Fail closed if simulated daily returns count does not match declared OOS sessions count
    if len(daily_net) != len(test_sessions):
        return FoldResult(
            fold_id=fold.fold_id,
            status="blocked",
            blocked_reasons=(f"incomplete_simulation_sessions: got {len(daily_net)}, expected {len(test_sessions)}",),
            train_data_hash=train_res.receipt.get("data_hash", ""),
            test_data_hash=test_res.receipt.get("data_hash", ""),
            train_row_count=train_res.receipt.get("total_rows", 0),
            test_row_count=test_res.receipt.get("total_rows", 0),
            purged_rows_count=purged_rows_count,
            selected_parameters=best_params,
            in_sample_best_sharpe=round(best_sharpe, 4),
            in_sample_ic_mean=round(in_sample_ic_mean, 4),
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
        oos_sessions_count=len(test_sessions),
        pit_limitations=DEFAULT_PIT_LIMITATIONS,
    )


def run_walkforward_study(
    config: WalkForwardConfig | None = None,
    root: Path | None = None,
) -> WalkForwardStudyResult:
    """Execute complete Walk-Forward study across declared folds with fail-closed integrity."""
    cfg = config or DEFAULT_WALK_FORWARD_CONFIG
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()
    git_commit = _get_git_commit(repo_root)
    code_source_sha256 = _get_code_source_sha256(repo_root)
    config_hash = _get_config_hash(cfg)

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
            "config_hash": config_hash,
            "code_source_sha256": code_source_sha256,
            "config": cfg.to_dict(),
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
            git_commit=git_commit,
            config_hash=config_hash,
            code_source_sha256=code_source_sha256,
            experiment_receipt=cfg.to_dict(),
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

    # Build canonical payload and cryptographic study hash (bound to full config and git commit)
    study_payload = {
        "study_id": cfg.study_id,
        "status": "ready",
        "blocked_reasons": [],
        "hypothesis_name": cfg.hypothesis_name,
        "market": cfg.market,
        "pool_id": cfg.pool_id,
        "symbols": list(cfg.symbols),
        "benchmark": cfg.benchmark,
        "config_hash": config_hash,
        "code_source_sha256": code_source_sha256,
        "config": cfg.to_dict(),
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
        git_commit=git_commit,
        config_hash=config_hash,
        code_source_sha256=code_source_sha256,
        experiment_receipt=cfg.to_dict(),
        pit_limitations=DEFAULT_PIT_LIMITATIONS,
        research_only=True,
        trade_ready=False,
        trade_signal=False,
    )
