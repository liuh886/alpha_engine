"""TopN rolling backtest helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestSummary:
    """Summary values for one TopN run."""

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
    """Select top-N rows per date."""
    required = {"date", "ticker", score_col}
    missing = required - set(signal_df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if top_n <= 0:
        return signal_df.iloc[0:0].copy()

    ranked = signal_df.dropna(subset=[score_col]).sort_values(
        ["date", score_col, "ticker"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    return ranked.groupby("date", group_keys=False).head(top_n).copy()


def build_daily_sleeves(selected_df: pd.DataFrame, holding_days: int = 10) -> pd.DataFrame:
    """Expand selected names into active sleeve rows."""
    if holding_days <= 0:
        raise ValueError("holding_days must be positive")
    if not {"date", "ticker"}.issubset(selected_df.columns):
        raise ValueError("selected_df must contain date and ticker")

    dates = pd.Index(sorted(selected_df["date"].unique()))
    date_to_pos = {date: pos for pos, date in enumerate(dates)}
    pos_to_date = {pos: date for pos, date in enumerate(dates)}
    rows: list[dict[str, object]] = []

    for row in selected_df[["date", "ticker"]].itertuples(index=False):
        start_pos = date_to_pos[row.date]
        for age in range(holding_days):
            active_pos = start_pos + age
            if active_pos >= len(dates):
                break
            rows.append(
                {
                    "entry_date": row.date,
                    "active_date": pos_to_date[active_pos],
                    "ticker": row.ticker,
                    "sleeve_age": age,
                }
            )
    return pd.DataFrame(rows)


def compute_portfolio_returns(
    sleeves_df: pd.DataFrame,
    realized_returns: pd.DataFrame,
    bench_returns: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute equal-weighted returns for active sleeves."""
    if sleeves_df.empty:
        raise ValueError("sleeves_df is empty")

    returns = realized_returns.copy()
    returns.index.name = "active_date"
    returns.columns.name = "ticker"
    returns_long = returns.reset_index().melt(
        id_vars=["active_date"],
        var_name="ticker",
        value_name="asset_return",
    )
    merged = sleeves_df.merge(returns_long, on=["active_date", "ticker"], how="left")
    daily = (
        merged.groupby("active_date")
        .agg(portfolio_return=("asset_return", "mean"), n_positions=("ticker", "nunique"))
        .sort_index()
    )

    if bench_returns is None:
        daily["bench_return"] = np.nan
        daily["excess_alpha"] = np.nan
    else:
        daily = daily.join(bench_returns.rename("bench_return"), how="left")
        daily["excess_alpha"] = daily["portfolio_return"] - daily["bench_return"]
    return daily


def compute_turnover(selected_df: pd.DataFrame) -> pd.Series:
    """Compute one-way turnover from date-level selected baskets."""
    baskets = {date: set(group["ticker"].tolist()) for date, group in selected_df.groupby("date")}
    values: dict[pd.Timestamp, float] = {}
    previous: set[str] | None = None

    for date in sorted(baskets):
        current = baskets[date]
        if previous is None or not current:
            values[date] = np.nan
        else:
            values[date] = 1.0 - len(previous & current) / max(len(current), 1)
        previous = current
    return pd.Series(values, name="turnover").sort_index()


def max_drawdown(return_series: pd.Series) -> float:
    """Compute max drawdown from a daily return series."""
    equity = (1.0 + return_series.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def summarize_backtest(
    portfolio_df: pd.DataFrame,
    turnover: pd.Series,
    top_n: int,
    holding_days: int,
    spread_series: pd.Series | None = None,
) -> BacktestSummary:
    """Build summary metrics for one TopN run."""
    alpha = portfolio_df["excess_alpha"].dropna()
    returns = portfolio_df["portfolio_return"].dropna()
    mean_alpha = float(alpha.mean()) if not alpha.empty else np.nan
    mean_return = float(returns.mean()) if not returns.empty else np.nan
    sharpe = (
        float(returns.mean() / (returns.std() + 1e-12) * np.sqrt(252))
        if not returns.empty
        else np.nan
    )
    avg_turnover = float(turnover.dropna().mean()) if not turnover.dropna().empty else np.nan
    mean_spread = (
        float(spread_series.mean())
        if spread_series is not None and not spread_series.empty
        else None
    )

    return BacktestSummary(
        top_n=top_n,
        holding_days=holding_days,
        annualized_alpha=mean_alpha * 252,
        annualized_return=mean_return * 252,
        sharpe=sharpe,
        max_drawdown=max_drawdown(returns) if not returns.empty else np.nan,
        avg_daily_turnover=avg_turnover,
        hit_rate=float((alpha > 0).mean()) if not alpha.empty else np.nan,
        mean_daily_alpha=mean_alpha,
        mean_daily_spread=mean_spread,
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
    """Run TopN and BottomN rolling backtests and return portfolio plus summary."""
    top_selected = select_top_n(signal_df, score_col=score_col, top_n=top_n)
    top_sleeves = build_daily_sleeves(top_selected, holding_days=holding_days)
    portfolio_df = compute_portfolio_returns(top_sleeves, realized_returns, bench_returns)
    turnover = compute_turnover(top_selected)

    if bottom_signal_df is None:
        bottom_source = signal_df.copy()
        bottom_source["_negative_score"] = -bottom_source[score_col]
        bottom_selected = select_top_n(bottom_source, score_col="_negative_score", top_n=top_n)
    else:
        bottom_selected = select_top_n(bottom_signal_df, score_col=score_col, top_n=top_n)

    bottom_sleeves = build_daily_sleeves(bottom_selected[["date", "ticker"]], holding_days)
    bottom_df = compute_portfolio_returns(bottom_sleeves, realized_returns, bench_returns)
    spread_series = (portfolio_df["portfolio_return"] - bottom_df["portfolio_return"]).dropna()

    summary = summarize_backtest(
        portfolio_df=portfolio_df,
        turnover=turnover,
        top_n=top_n,
        holding_days=holding_days,
        spread_series=spread_series,
    )
    output = portfolio_df.copy()
    output["turnover"] = turnover.reindex(output.index)
    output["top_bottom_spread"] = spread_series.reindex(output.index)
    return output, summary
