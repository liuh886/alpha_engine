"""Pure backtest functions extracted from ``src.backtest_strategy``."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestSummary:
    """Compact summary statistics for a backtest run."""

    total_return: float
    benchmark_return: float
    excess_return: float
    annualized_alpha: float
    sharpe: float
    max_drawdown: float
    avg_daily_turnover: float
    hit_rate: float


def select_topn_with_guardrail(
    scores: pd.Series,
    topk: int,
    prices: pd.Series | None = None,
    ma60: pd.Series | None = None,
) -> list[str]:
    """Select up to ``topk`` names using score > 0 and optional price > MA60 filters."""
    if topk <= 0 or scores.empty:
        return []

    candidates = scores.dropna().sort_values(ascending=False).head(topk)
    selected: list[str] = []
    for ticker, score in candidates.items():
        if score <= 0:
            continue
        if prices is not None and ma60 is not None:
            price = prices.get(ticker, np.nan)
            moving_average = ma60.get(ticker, np.nan)
            if pd.isna(price) or pd.isna(moving_average) or price <= moving_average:
                continue
        selected.append(str(ticker))
    return selected


def select_topn_no_guardrail(scores: pd.Series, topk: int) -> list[str]:
    """Select the lowest-scored ``topk`` names for a BottomN diagnostic leg."""
    if topk <= 0 or scores.empty:
        return []
    return [str(ticker) for ticker in scores.dropna().sort_values(ascending=True).head(topk).index]


def compute_portfolio_returns(
    holdings_by_date: dict[pd.Timestamp, list[str]],
    daily_rets: pd.DataFrame,
    bench_ret: pd.Series,
    initial_cash: float = 10_000.0,
    transaction_cost: float = 0.0005,
) -> pd.DataFrame:
    """Simulate an equal-weight portfolio from pre-computed daily holdings."""
    portfolio_value = float(initial_cash)
    benchmark_value = float(initial_cash)
    previous_holdings: list[str] = []
    records: list[dict[str, object]] = []

    for index, date in enumerate(sorted(holdings_by_date)):
        current_holdings = holdings_by_date[date]
        day_pnl = 0.0

        if index > 0:
            day_pnl = _mean_return_for_names(daily_rets, date, previous_holdings)
            portfolio_value *= 1.0 + day_pnl
            if set(current_holdings) != set(previous_holdings):
                portfolio_value *= 1.0 - transaction_cost

            benchmark_return = bench_ret.get(date, 0.0)
            benchmark_return = 0.0 if pd.isna(benchmark_return) else float(benchmark_return)
            benchmark_value *= 1.0 + benchmark_return

        records.append(
            _make_record(
                date=date,
                portfolio_value=portfolio_value,
                benchmark_value=benchmark_value,
                holdings=current_holdings,
                daily_return=day_pnl,
            )
        )
        previous_holdings = current_holdings

    hist_df = pd.DataFrame(records).set_index("date")
    hist_df["excess_alpha"] = hist_df["daily_return"] - bench_ret.reindex(hist_df.index).fillna(0.0)
    return hist_df


def _mean_return_for_names(daily_rets: pd.DataFrame, date: pd.Timestamp, names: list[str]) -> float:
    if not names:
        return 0.0
    available = [name for name in names if name in daily_rets.columns]
    if not available:
        return 0.0
    return float(daily_rets.loc[date, available].fillna(0.0).mean())


def _make_record(
    date: pd.Timestamp,
    portfolio_value: float,
    benchmark_value: float,
    holdings: list[str],
    daily_return: float,
) -> dict[str, object]:
    return {
        "date": date,
        "portfolio_value": portfolio_value,
        "benchmark_value": benchmark_value,
        "holdings": ", ".join(holdings),
        "daily_return": daily_return,
    }


def compute_turnover(holdings_by_date: dict[pd.Timestamp, list[str]]) -> pd.Series:
    """Approximate one-way daily turnover from holdings overlap."""
    result: dict[pd.Timestamp, float] = {}
    previous: set[str] = set()
    for date in sorted(holdings_by_date):
        current = set(holdings_by_date[date])
        if not previous:
            result[date] = np.nan
        else:
            overlap = len(previous & current) / max(len(current), 1)
            result[date] = 1.0 - overlap
        previous = current
    return pd.Series(result, name="turnover")


def max_drawdown(equity_curve: pd.Series) -> float:
    """Return maximum drawdown from an equity-value series."""
    peak = equity_curve.cummax()
    drawdown = equity_curve / peak - 1.0
    return float(drawdown.min())


def build_backtest_summary(
    hist_df: pd.DataFrame,
    bench_ret: pd.Series,
    initial_cash: float = 10_000.0,
    turnover: pd.Series | None = None,
) -> BacktestSummary:
    """Compute summary statistics from ``compute_portfolio_returns`` output."""
    del bench_ret
    total_return = float(hist_df["portfolio_value"].iloc[-1] / initial_cash - 1.0)
    benchmark_return = float(hist_df["benchmark_value"].iloc[-1] / initial_cash - 1.0)
    alpha_series = hist_df["excess_alpha"].dropna()
    return_series = hist_df["daily_return"].dropna()

    mean_alpha = float(alpha_series.mean()) if not alpha_series.empty else np.nan
    sharpe = (
        float(return_series.mean() / (return_series.std() + 1e-12) * np.sqrt(252))
        if not return_series.empty
        else np.nan
    )
    avg_turnover = (
        float(turnover.dropna().mean())
        if turnover is not None and not turnover.dropna().empty
        else np.nan
    )

    return BacktestSummary(
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        annualized_alpha=mean_alpha * 252,
        sharpe=sharpe,
        max_drawdown=max_drawdown(hist_df["portfolio_value"]),
        avg_daily_turnover=avg_turnover,
        hit_rate=float((alpha_series > 0).mean()) if not alpha_series.empty else np.nan,
    )
