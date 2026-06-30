"""TopN rolling backtest for winner-bucket strategies.

This module provides a notebook-friendly, pure-function backtest engine for
winner-bucket research:

- Input signal is a cross-sectional ranking score or winner probability
  (`winner_prob`, `winner_score`, etc.) by (date, ticker).
- Daily select TopN names (Top5 / Top10 / Top20).
- Each daily sleeve is held for a fixed horizon (default 10 trading days).
- Portfolio return is the equally-weighted average of all active sleeves.
- Evaluation focuses on benchmark-relative alpha first, then spread / risk.

Design principles:
- Pure functions, no I/O, notebook-first.
- Explicit signal-date / holding-window semantics.
- No hidden transaction-cost model; turnover is reported for downstream use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestSummary:
    top_n: int
    holding_days: int
    annualized_alpha: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    avg_daily_turnover: float
    hit_rate: float
    mean_daily_alpha: float
    mean_daily_spread: float | None = None


def select_top_n(signal_df: pd.DataFrame, score_col: str, top_n: int) -> pd.DataFrame:
    """Select top-N names per date from a scored universe."""
    required = {"date", "ticker", score_col}
    missing = required - set(signal_df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    ranked = signal_df.sort_values(["date", score_col], ascending=[True, False])
    return ranked.groupby("date", group_keys=False).head(top_n).copy()


def build_daily_sleeves(selected_df: pd.DataFrame, holding_days: int = 10) -> pd.DataFrame:
    """Expand each selected trade into a sleeve active over its holding window."""
    if not {"date", "ticker"}.issubset(selected_df.columns):
        raise ValueError("selected_df must contain date and ticker")

    unique_dates = pd.Index(sorted(selected_df["date"].unique()))
    date_to_idx = {d: i for i, d in enumerate(unique_dates)}
    idx_to_date = {i: d for i, d in enumerate(unique_dates)}

    records: list[dict] = []
    for row in selected_df[["date", "ticker"]].itertuples(index=False):
        start_idx = date_to_idx[row.date]
        for offset in range(holding_days):
            active_idx = start_idx + offset
            if active_idx >= len(unique_dates):
                break
            records.append(
                {
                    "entry_date": row.date,
                    "active_date": idx_to_date[active_idx],
                    "ticker": row.ticker,
                    "sleeve_age": offset,
                }
            )
    return pd.DataFrame(records)


def compute_portfolio_returns(
    sleeves_df: pd.DataFrame,
    realized_returns: pd.DataFrame,
    bench_returns: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute equal-weighted daily portfolio returns from active sleeves."""
    if sleeves_df.empty:
        raise ValueError("sleeves_df is empty")

    rtn_long = realized_returns.stack(future_stack=True).reset_index()
    rtn_long.columns = ["active_date", "ticker", "asset_return"]

    merged = sleeves_df.merge(rtn_long, on=["active_date", "ticker"], how="left")
    daily = (
        merged.groupby("active_date")
        .agg(
            portfolio_return=("asset_return", "mean"),
            n_positions=("ticker", "nunique"),
        )
        .sort_index()
    )

    if bench_returns is not None:
        bench = bench_returns.rename("bench_return")
        daily = daily.join(bench, how="left")
        daily["excess_alpha"] = daily["portfolio_return"] - daily["bench_return"]
    else:
        daily["bench_return"] = np.nan
        daily["excess_alpha"] = np.nan

    return daily


def compute_turnover(selected_df: pd.DataFrame) -> pd.Series:
    """Approximate daily one-way turnover from selection overlap."""
    baskets = {d: set(g["ticker"].tolist()) for d, g in selected_df.groupby("date")}
    dates = sorted(baskets)
    turnover = {}
    prev = None
    for d in dates:
        curr = baskets[d]
        if prev is None or len(curr) == 0:
            turnover[d] = np.nan
        else:
            overlap = len(prev.intersection(curr)) / max(len(curr), 1)
            turnover[d] = 1.0 - overlap
        prev = curr
    return pd.Series(turnover, name="turnover").sort_index()


def max_drawdown(return_series: pd.Series) -> float:
    """Compute max drawdown from daily return series."""
    equity = (1.0 + return_series.fillna(0.0)).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def summarize_backtest(
    portfolio_df: pd.DataFrame,
    turnover: pd.Series,
    top_n: int,
    holding_days: int,
    spread_series: pd.Series | None = None,
) -> BacktestSummary:
    """Produce a compact summary object for reporting."""
    alpha = portfolio_df["excess_alpha"].dropna()
    ret = portfolio_df["portfolio_return"].dropna()

    ann_factor = 252
    mean_alpha = float(alpha.mean()) if not alpha.empty else np.nan
    mean_ret = float(ret.mean()) if not ret.empty else np.nan
    sharpe = (
        float((ret.mean() / (ret.std() + 1e-12)) * np.sqrt(ann_factor))
        if not ret.empty
        else np.nan
    )

    return BacktestSummary(
        top_n=top_n,
        holding_days=holding_days,
        annualized_alpha=mean_alpha * ann_factor,
        annualized_return=mean_ret * ann_factor,
        sharpe=sharpe,
        max_drawdown=max_drawdown(ret) if not ret.empty else np.nan,
        avg_daily_turnover=float(turnover.dropna().mean()) if not turnover.dropna().empty else np.nan,
        hit_rate=float((alpha > 0).mean()) if not alpha.empty else np.nan,
        mean_daily_alpha=mean_alpha,
        mean_daily_spread=float(spread_series.mean())
        if spread_series is not None and not spread_series.empty
        else None,
    )


def run_topn_rolling_backtest(
    signal_df: pd.DataFrame,
    realized_returns: pd.DataFrame,
    bench_returns: pd.Series,
    score_col: str = "winner_prob",
    top_n: int = 10,
    holding_days: int = 10,
    bottom_signal_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, BacktestSummary]:
    """End-to-end TopN rolling backtest."""
    top_sel = select_top_n(signal_df, score_col=score_col, top_n=top_n)
    sleeves = build_daily_sleeves(top_sel, holding_days=holding_days)
    portfolio_df = compute_portfolio_returns(sleeves, realized_returns, bench_returns)
    turnover = compute_turnover(top_sel)

    if bottom_signal_df is None:
        tmp = signal_df.copy()
        tmp["_neg_score"] = -tmp[score_col]
        bottom_sel = select_top_n(tmp, score_col="_neg_score", top_n=top_n)
    else:
        bottom_sel = select_top_n(bottom_signal_df, score_col=score_col, top_n=top_n)

    bottom_sleeves = build_daily_sleeves(bottom_sel[["date", "ticker"]], holding_days=holding_days)
    bottom_df = compute_portfolio_returns(bottom_sleeves, realized_returns, bench_returns)
    spread_series = (portfolio_df["portfolio_return"] - bottom_df["portfolio_return"]).dropna()

    summary = summarize_backtest(
        portfolio_df=portfolio_df,
        turnover=turnover,
        top_n=top_n,
        holding_days=holding_days,
        spread_series=spread_series,
    )
    portfolio_df = portfolio_df.copy()
    portfolio_df["turnover"] = turnover.reindex(portfolio_df.index)
    portfolio_df["top_bottom_spread"] = spread_series.reindex(portfolio_df.index)
    return portfolio_df, summary
