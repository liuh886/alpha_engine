"""Pure backtest functions extracted from src/backtest_strategy.py.

All functions here are free of I/O, logging, and qlib initialisation so they
can be called directly from a Jupyter notebook for interactive research, and
also composed inside run_backtest() for production use.

Design contract
---------------
- Inputs are plain pandas objects (Series / DataFrame).
- No side effects: no writes, no prints, no qlib calls.
- run_backtest() in backtest_strategy.py owns I/O, qlib init, and reporting.
- Notebooks own data loading; they call these functions for logic.

Entry points
------------
    select_topn_with_guardrail(scores, topk, prices, ma60)
    compute_portfolio_returns(holdings_by_date, daily_rets, bench_ret, initial_cash)
    compute_turnover(holdings_by_date)
    max_drawdown(equity_curve)
    build_backtest_summary(hist_df, bench_ret, initial_cash)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_topn_with_guardrail(
    scores: pd.Series,
    topk: int,
    prices: pd.Series | None = None,
    ma60: pd.Series | None = None,
) -> list[str]:
    """Select up to topk instruments from a cross-sectional score Series.

    Replicates the dual-filter logic already in run_backtest():
      1. Sort descending by score, take head(topk) candidates.
      2. Drop candidates with score <= 0  (trend filter).
      3. Drop candidates where price <= MA60 (trend guard).

    Args:
        scores: pd.Series indexed by instrument (ticker).
        topk: Maximum number of positions.
        prices: Optional close price Series indexed by instrument.
            If None, the price>MA60 filter is skipped.
        ma60: Optional 60-day MA Series indexed by instrument.
            If None, the price>MA60 filter is skipped.

    Returns:
        List of selected tickers (may be shorter than topk).
    """
    candidates = scores.sort_values(ascending=False).head(topk)

    valid: list[str] = []
    for ticker, score in candidates.items():
        if score <= 0:
            continue
        if prices is not None and ma60 is not None:
            price = prices.get(ticker, np.nan)
            ma = ma60.get(ticker, np.nan)
            if pd.isna(price) or pd.isna(ma) or price <= ma:
                continue
        valid.append(ticker)
    return valid


def select_topn_no_guardrail(
    scores: pd.Series,
    topk: int,
) -> list[str]:
    """Select bottom-topk names without any guardrail (used for short / spread leg).

    Args:
        scores: pd.Series indexed by instrument.
        topk: Number of names to select.

    Returns:
        List of selected tickers sorted by ascending score.
    """
    return scores.sort_values(ascending=True).head(topk).index.tolist()


# ---------------------------------------------------------------------------
# Portfolio simulation
# ---------------------------------------------------------------------------

def compute_portfolio_returns(
    holdings_by_date: dict[pd.Timestamp, list[str]],
    daily_rets: pd.DataFrame,
    bench_ret: pd.Series,
    initial_cash: float = 10_000.0,
    transaction_cost: float = 0.0005,
) -> pd.DataFrame:
    """Simulate equal-weight portfolio given pre-computed daily holdings.

    Replicates the day-loop in run_backtest() as a pure function.

    Args:
        holdings_by_date: {date: [ticker, ...]} mapping as produced by the
            selection step. Date is the *start-of-day* holdings (trade
            executed at previous close, consistent with existing code).
        daily_rets: Wide DataFrame of daily returns (index=date, columns=tickers).
        bench_ret: Series of daily benchmark returns.
        initial_cash: Starting portfolio value.
        transaction_cost: One-way cost applied on any change in holdings.

    Returns:
        DataFrame with columns:
            portfolio_value, benchmark_value, holdings (str),
            daily_return, excess_alpha
    """
    portfolio_value = initial_cash
    bench_cum = initial_cash
    trading_days = sorted(holdings_by_date)
    prev_holdings: list[str] = []
    records = []

    for i, date in enumerate(trading_days):
        current_holdings = holdings_by_date[date]

        if i == 0:
            records.append(_make_record(
                date, portfolio_value, initial_cash, current_holdings, 0.0
            ))
            prev_holdings = current_holdings
            continue

        # Apply P&L from previous day's holdings
        day_pnl = 0.0
        topk = max(len(prev_holdings), 1)
        weight = 1.0 / topk
        for ticker in prev_holdings:
            ret = daily_rets.loc[date, ticker] if ticker in daily_rets.columns else 0.0
            day_pnl += (0.0 if pd.isna(ret) else ret) * weight

        portfolio_value *= (1 + day_pnl)

        # Transaction cost on rebalance
        if set(current_holdings) != set(prev_holdings):
            portfolio_value *= (1 - transaction_cost)

        # Benchmark tracking
        b = bench_ret.get(date, 0.0)
        bench_cum *= (1 + (0.0 if pd.isna(b) else b))

        records.append(_make_record(
            date, portfolio_value, bench_cum, current_holdings, day_pnl
        ))
        prev_holdings = current_holdings

    hist_df = pd.DataFrame(records).set_index("date")
    hist_df["excess_alpha"] = (
        hist_df["daily_return"] - bench_ret.reindex(hist_df.index).fillna(0)
    )
    return hist_df


def _make_record(
    date: pd.Timestamp,
    portfolio_value: float,
    benchmark_value: float,
    holdings: list[str],
    daily_return: float,
) -> dict:
    return {
        "date": date,
        "portfolio_value": portfolio_value,
        "benchmark_value": benchmark_value,
        "holdings": ", ".join(holdings),
        "daily_return": daily_return,
    }


# ---------------------------------------------------------------------------
# Risk & diagnostics
# ---------------------------------------------------------------------------

def compute_turnover(holdings_by_date: dict[pd.Timestamp, list[str]]) -> pd.Series:
    """Approximate one-way daily turnover from holdings overlap.

    turnover_t = 1 - |prev ∩ curr| / max(|curr|, 1)
    """
    dates = sorted(holdings_by_date)
    result = {}
    prev: set[str] = set()
    for d in dates:
        curr = set(holdings_by_date[d])
        if not prev:
            result[d] = np.nan
        else:
            overlap = len(prev & curr) / max(len(curr), 1)
            result[d] = 1.0 - overlap
        prev = curr
    return pd.Series(result, name="turnover")


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown from an equity-value (not return) series."""
    peak = equity_curve.cummax()
    dd = equity_curve / peak - 1.0
    return float(dd.min())


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestSummary:
    total_return: float
    benchmark_return: float
    excess_return: float
    annualized_alpha: float
    sharpe: float
    max_drawdown: float
    avg_daily_turnover: float
    hit_rate: float


def build_backtest_summary(
    hist_df: pd.DataFrame,
    bench_ret: pd.Series,
    initial_cash: float = 10_000.0,
    turnover: pd.Series | None = None,
) -> BacktestSummary:
    """Compute summary statistics from the output of compute_portfolio_returns()."""
    final_value = hist_df["portfolio_value"].iloc[-1]
    final_bench = hist_df["benchmark_value"].iloc[-1]

    total_ret = final_value / initial_cash - 1.0
    bench_total_ret = final_bench / initial_cash - 1.0
    excess = total_ret - bench_total_ret

    alpha_series = hist_df["excess_alpha"].dropna()
    ret_series = hist_df["daily_return"].dropna()
    ann = 252
    mean_alpha = float(alpha_series.mean()) if not alpha_series.empty else np.nan
    sharpe = (
        float(ret_series.mean() / (ret_series.std() + 1e-12) * np.sqrt(ann))
        if not ret_series.empty else np.nan
    )

    mdd = max_drawdown(hist_df["portfolio_value"])
    hit = float((alpha_series > 0).mean()) if not alpha_series.empty else np.nan
    avg_turn = (
        float(turnover.dropna().mean())
        if turnover is not None and not turnover.dropna().empty
        else np.nan
    )

    return BacktestSummary(
        total_return=total_ret,
        benchmark_return=bench_total_ret,
        excess_return=excess,
        annualized_alpha=mean_alpha * ann,
        sharpe=sharpe,
        max_drawdown=mdd,
        avg_daily_turnover=avg_turn,
        hit_rate=hit,
    )
