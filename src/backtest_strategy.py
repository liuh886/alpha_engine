"""Backtest strategy runner.

Supports the experimental LGBMRegressor + T+10 spread path while keeping the
existing CLI entry point. The implementation uses the current ``src.core`` API
names so notebook validation and the backtest runner share the same primitives.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import fire
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import qlib
from plotly.subplots import make_subplots
from qlib.data import D

from src.common.config_utils import load_watchlist
from src.common.logging import get_logger
from src.core import compute_spread, generate_scores, select_bottomk, select_topk

logger = get_logger(__name__)


def _load_pickle_model(model_path: str | Path):
    path = Path(model_path)
    with path.open("rb") as f:
        return pickle.load(f)


def _score_slice(scores: pd.Series, date) -> pd.Series:
    date_level = "datetime" if "datetime" in scores.index.names else 0
    return scores.xs(date, level=date_level).dropna()


def generate_interactive_report(
    hist_df: pd.DataFrame,
    benchmark: str,
    prices: pd.DataFrame,
    ticker_profits: dict[str, float],
    trade_logs: dict,
    model_info: dict | None = None,
    spread_series: pd.Series | None = None,
    report_path: str = "reports/backtest_report.html",
) -> None:
    logger.info("Generating interactive report with trade details")

    sorted_tickers = sorted(ticker_profits.items(), key=lambda x: x[1], reverse=True)
    top_15 = [ticker for ticker, _ in sorted_tickers[:15]]
    groups = [top_15[0:5], top_15[5:10], top_15[10:15]]

    main_title = "AI Trading Assistant: Backtest Report"
    if model_info:
        model_desc = (
            f"Model: {model_info.get('algorithm', 'Unknown')} | "
            f"Train: {model_info.get('train_period', 'N/A')} | "
            f"Label: {model_info.get('label', 'N/A')}"
        )
        main_title = f"{main_title}<br><sup>{model_desc}</sup>"

    include_spread = spread_series is not None and not spread_series.empty
    n_rows = 5 if include_spread else 4
    row_heights = [0.35, 0.15, 0.17, 0.17, 0.16] if include_spread else [0.4, 0.2, 0.2, 0.2]
    titles = (
        [
            "Equity Curve",
            "TopK-BottomK Spread",
            "Top 1-5 Winners",
            "Top 6-10 Winners",
            "Top 11-15 Winners",
        ]
        if include_spread
        else ["Equity Curve", "Top 1-5 Winners", "Top 6-10 Winners", "Top 11-15 Winners"]
    )

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=titles,
    )

    fig.add_trace(
        go.Scatter(
            x=hist_df.index,
            y=hist_df["portfolio_value"],
            name="TopK Long Strategy",
            line=dict(color="#00ff88", width=2),
            hovertemplate="Value: $%{y:,.0f}<br>Holdings: %{customdata}<extra></extra>",
            customdata=hist_df["holdings"],
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=hist_df.index,
            y=hist_df["benchmark_value"],
            name=f"Benchmark ({benchmark})",
            line=dict(color="rgba(255, 255, 255, 0.5)", width=2, dash="dot"),
        ),
        row=1,
        col=1,
    )

    row_offset = 0
    if include_spread:
        row_offset = 1
        cumulative_spread = (1 + spread_series.fillna(0.0)).cumprod() - 1
        fig.add_trace(
            go.Scatter(
                x=cumulative_spread.index,
                y=cumulative_spread * 100,
                name="Cumulative Spread (%)",
                line=dict(color="#ff9900", width=2),
                fill="tozeroy",
                fillcolor="rgba(255, 153, 0, 0.1)",
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text="Spread (%)", row=2, col=1)

    colors = ["#ff7f0e", "#1f77b4", "#2ca02c", "#d62728", "#9467bd"]
    for group_idx, group in enumerate(groups):
        row_idx = group_idx + 2 + row_offset
        for color_idx, ticker in enumerate(group):
            if ticker not in prices.columns:
                continue
            raw_price = prices[ticker].dropna()
            if raw_price.empty:
                continue

            base_price = raw_price.iloc[0]
            price_series = raw_price / base_price * 100
            pct_from_start = (raw_price / base_price - 1) * 100
            total_profit = ticker_profits.get(ticker, 0.0) * 100
            color = colors[color_idx % len(colors)]

            fig.add_trace(
                go.Scatter(
                    x=price_series.index,
                    y=price_series,
                    name=f"{ticker} (${raw_price.iloc[-1]:.2f}, {total_profit:+.1f}%)",
                    line=dict(width=1.5, color=color),
                    legendgroup=f"group{row_idx}",
                    showlegend=True,
                    hovertemplate=f"{ticker} - $%{{customdata[0]:.2f}} - %{{customdata[1]:+.2f}}%<extra></extra>",
                    customdata=np.stack((raw_price, pct_from_start), axis=-1),
                ),
                row=row_idx,
                col=1,
            )

            held_days = sorted(date for date, holdings in trade_logs.items() if ticker in holdings)
            if not held_days:
                continue

            buys_x: list = []
            buys_y: list = []
            sells_x: list = []
            sells_y: list = []
            all_days = sorted(hist_df.index)
            in_position = False
            for pos, current_day in enumerate(all_days):
                is_held = current_day in held_days
                if is_held and not in_position:
                    if current_day in price_series.index:
                        buys_x.append(current_day)
                        buys_y.append(price_series.loc[current_day])
                    in_position = True
                elif not is_held and in_position:
                    prev_day = all_days[pos - 1]
                    if prev_day in price_series.index:
                        sells_x.append(prev_day)
                        sells_y.append(price_series.loc[prev_day])
                    in_position = False

            if buys_x:
                fig.add_trace(
                    go.Scatter(
                        x=buys_x,
                        y=buys_y,
                        mode="markers",
                        name=f"{ticker} Buy",
                        marker=dict(symbol="triangle-up", size=10, color="green"),
                        showlegend=False,
                        legendgroup=f"group{row_idx}",
                        hoverinfo="skip",
                    ),
                    row=row_idx,
                    col=1,
                )
            if sells_x:
                fig.add_trace(
                    go.Scatter(
                        x=sells_x,
                        y=sells_y,
                        mode="markers",
                        name=f"{ticker} Sell",
                        marker=dict(symbol="triangle-down", size=10, color="red"),
                        showlegend=False,
                        legendgroup=f"group{row_idx}",
                        hoverinfo="skip",
                    ),
                    row=row_idx,
                    col=1,
                )

    fig.update_layout(title=main_title, height=250 * n_rows, template="plotly_dark", hovermode="x unified")
    for row in range(2 + row_offset, n_rows + 1):
        fig.update_yaxes(title_text="Price (Base 100)", row=row, col=1)

    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(report_path)
    logger.info("Interactive report saved", report_path=report_path)


def run_backtest(
    start_date: str = "2025-10-23",
    end_date: str = "2026-01-23",
    initial_cash: float = 10_000,
    topk: int = 10,
    bottomk: int = 10,
    holding_days: int = 10,
    benchmark: str = "QQQ",
    model_path: str = "models/us_regressor.pkl",
    report_path: str = "reports/backtest_report.html",
) -> dict:
    """Run a TopK long strategy plus BottomK spread diagnostic path."""
    logger.info("Starting backtest", start_date=start_date, end_date=end_date)
    logger.info("Parameters", topk=topk, bottomk=bottomk, holding_days=holding_days)
    logger.info("Benchmark", benchmark=benchmark)
    logger.info("Model", path=model_path)

    qlib.init(provider_uri="data/watchlist")

    watchlist = load_watchlist("configs/watchlist.yaml")
    watchlist_tickers = watchlist.get("us", [])

    instruments_path = Path("data/watchlist") / "instruments" / "all.txt"
    all_instruments: list[str] = []
    if instruments_path.exists():
        with instruments_path.open() as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    all_instruments.append(parts[0])

    strategy_instruments = [ticker for ticker in watchlist_tickers if ticker in all_instruments]
    if not strategy_instruments:
        raise ValueError("No US watchlist tickers were found in data/watchlist/instruments/all.txt")

    market_instruments = list(dict.fromkeys(strategy_instruments + [benchmark]))
    logger.info("Universe", num_stocks=len(strategy_instruments))

    model = _load_pickle_model(model_path)
    logger.info("Loaded model", model_type=type(model).__name__)

    from qlib.contrib.data.handler import Alpha158

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "fit_start_time": start_date,
        "fit_end_time": start_date,
        "instruments": strategy_instruments,
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
        "label": ["Ref($close, -10) / $close - 1"],
    }

    dh = Alpha158(**handler_kwargs)
    logger.info("Fetching data for inference")
    df_data = dh.fetch(selector=(start_date, end_date), col_set="feature")

    logger.info("Generating regressor scores")
    pred_scores = generate_scores(model, df_data)

    logger.info("Fetching market data and MA60")
    fields = ["$close", "$open", "$high", "$low", "Mean($close, 60)"]
    names = ["close", "open", "high", "low", "ma60"]
    market_data = D.features(market_instruments, fields, start_time=start_date, end_time=end_date)
    market_data.columns = names

    close_prices = market_data["close"].unstack(level="instrument")
    ma60_data = market_data["ma60"].unstack(level="instrument")
    daily_rets = close_prices.pct_change()
    bench_ret = daily_rets[benchmark] if benchmark in daily_rets.columns else pd.Series(0.0, index=daily_rets.index)

    portfolio_value = float(initial_cash)
    history: list[dict] = []
    trading_days = sorted(daily_rets.index)
    current_long: list[str] = []
    current_short: list[str] = []

    ticker_profits = {ticker: 0.0 for ticker in strategy_instruments}
    trade_logs: dict = {}
    long_ret_daily: dict = {}
    short_ret_daily: dict = {}

    for i, date in enumerate(trading_days):
        trade_logs[date] = list(current_long)

        day_pnl = 0.0
        if i > 0:
            if current_long:
                valid_long = [ticker for ticker in current_long if ticker in daily_rets.columns]
                if valid_long:
                    long_rets = daily_rets.loc[date, valid_long].fillna(0.0)
                    day_pnl = float(long_rets.mean())
                    long_ret_daily[date] = day_pnl
                    for ticker, ret in long_rets.items():
                        ticker_profits[ticker] = ticker_profits.get(ticker, 0.0) + float(ret)
                else:
                    long_ret_daily[date] = 0.0
            else:
                long_ret_daily[date] = 0.0

            if current_short:
                valid_short = [ticker for ticker in current_short if ticker in daily_rets.columns]
                short_ret_daily[date] = (
                    float(daily_rets.loc[date, valid_short].fillna(0.0).mean())
                    if valid_short
                    else 0.0
                )
            else:
                short_ret_daily[date] = 0.0

            portfolio_value *= 1 + day_pnl

        if i % holding_days == 0:
            try:
                today_scores = _score_slice(pred_scores, date)
            except KeyError:
                current_long = []
                current_short = []
            else:
                close_today = close_prices.loc[date] if date in close_prices.index else None
                ma60_today = ma60_data.loc[date] if date in ma60_data.index else None
                next_long = select_topk(
                    today_scores,
                    k=topk,
                    guardrail=True,
                    prices=close_today,
                    ma=ma60_today,
                    min_score=0.0,
                )
                next_short = select_bottomk(today_scores, k=bottomk)

                if set(next_long) != set(current_long):
                    portfolio_value *= 1 - 0.0005
                current_long = next_long
                current_short = next_short

        benchmark_value = initial_cash * (1 + bench_ret.loc[:date].fillna(0.0)).cumprod().iloc[-1]
        history.append(
            {
                "date": date,
                "portfolio_value": portfolio_value,
                "benchmark_value": benchmark_value,
                "holdings": ", ".join(current_long),
                "daily_return": day_pnl,
            }
        )

    hist_df = pd.DataFrame(history).set_index("date")
    if hist_df.empty:
        raise ValueError("Backtest produced no history rows; check data availability and date range")

    total_ret = hist_df["portfolio_value"].iloc[-1] / initial_cash - 1
    bench_total_ret = hist_df["benchmark_value"].iloc[-1] / initial_cash - 1

    long_ret_series = pd.Series(long_ret_daily, name="long").sort_index()
    short_ret_series = pd.Series(short_ret_daily, name="short").reindex(long_ret_series.index).fillna(0.0)
    bench_daily = bench_ret.reindex(long_ret_series.index).fillna(0.0)
    spread_metrics = compute_spread(long_ret_series, short_ret_series, bench_daily)

    model_info = {
        "algorithm": type(model).__name__,
        "train_period": "see configs/us_lgbm_regressor_10d_workflow.yaml",
        "label": "T+10 Forward Return (Regressor)",
    }

    logger.info("Backtest Results")
    logger.info("Final portfolio value", value=f"${hist_df['portfolio_value'].iloc[-1]:,.2f}")
    logger.info("Strategy return", pct=f"{total_ret * 100:.2f}%")
    logger.info("Benchmark return", benchmark=benchmark, pct=f"{bench_total_ret * 100:.2f}%")
    logger.info("Spread Sharpe", value=f"{spread_metrics['spread_sharpe']:.2f}")

    generate_interactive_report(
        hist_df,
        benchmark,
        close_prices,
        ticker_profits,
        trade_logs,
        model_info=model_info,
        spread_series=spread_metrics["spread_series"],
        report_path=report_path,
    )

    return {
        "hist_df": hist_df,
        "spread_metrics": spread_metrics,
        "model_info": model_info,
        "long_ret_series": long_ret_series,
        "short_ret_series": short_ret_series,
    }


if __name__ == "__main__":
    fire.Fire(run_backtest)
