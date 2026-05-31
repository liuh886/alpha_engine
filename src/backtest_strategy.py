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

logger = get_logger(__name__)


def generate_interactive_report(
    hist_df,
    benchmark,
    prices,
    ticker_profits,
    trade_logs,
    model_info=None,
    report_path="reports/backtest_report.html",
):
    logger.info("Generating interactive report with trade details")

    # Identify Top Winners
    sorted_tickers = sorted(ticker_profits.items(), key=lambda x: x[1], reverse=True)
    top_15 = [t for t, p in sorted_tickers[:15]]

    groups = [top_15[0:5], top_15[5:10], top_15[10:15]]

    # Construct Title with Model Info
    main_title = "AI Trading Assistant: Backtest Report"
    if model_info:
        model_desc = f"Model: {model_info.get('algorithm', 'Unknown')} | Train: {model_info.get('train_period', 'N/A')} | Label: {model_info.get('label', 'N/A')}"
        main_title = f"{main_title}<br><sup>{model_desc}</sup>"

    titles = ["Equity Curve", "Top 1-5 Winners", "Top 6-10 Winners", "Top 11-15 Winners"]

    # Create figure with 4 rows
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.4, 0.2, 0.2, 0.2],
        subplot_titles=titles,
    )

    # --- Row 1: Equity Curve ---
    fig.add_trace(
        go.Scatter(
            x=hist_df.index,
            y=hist_df["portfolio_value"],
            name="AI Strategy",
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

    # --- Rows 2-4: Stock Charts with Markers ---
    colors = ["#ff7f0e", "#1f77b4", "#2ca02c", "#d62728", "#9467bd"]  # distinct colors

    for i, group in enumerate(groups):
        row_idx = i + 2
        for j, ticker in enumerate(group):
            if ticker not in prices.columns:
                continue

            # Plot Price Line (Normalized to 100)
            raw_price = prices[ticker].dropna()
            if raw_price.empty:
                continue

            base_price = raw_price.iloc[0]
            price_series = (raw_price / base_price) * 100
            last_price = raw_price.iloc[-1]
            total_profit = ticker_profits[ticker] * 100

            # Calculate daily % change from start for tooltip
            pct_from_start = (raw_price / base_price - 1) * 100

            color = colors[j % len(colors)]

            fig.add_trace(
                go.Scatter(
                    x=price_series.index,
                    y=price_series,
                    name=f"{ticker} (${last_price:.2f}, {total_profit:+.1f}%)",
                    line=dict(width=1.5, color=color),
                    legendgroup=f"group{row_idx}",
                    showlegend=True,
                    hovertemplate=f"{ticker} - $%{{customdata[0]:.2f}} - %{{customdata[1]:+.2f}}%<extra></extra>",
                    customdata=np.stack((raw_price, pct_from_start), axis=-1),
                ),
                row=row_idx,
                col=1,
            )

            # Add Buy/Sell Markers
            buys_x, buys_y = [], []
            sells_x, sells_y = [], []

            held_days = []
            for date, holdings in trade_logs.items():
                if ticker in holdings:
                    held_days.append(date)

            if not held_days:
                continue

            held_days = sorted(held_days)
            all_days = sorted(hist_df.index)

            in_position = False
            for d in all_days:
                is_held = d in held_days
                if is_held and not in_position:
                    if d in price_series.index:
                        buys_x.append(d)
                        buys_y.append(price_series.loc[d])
                    in_position = True
                elif not is_held and in_position:
                    prev_d_idx = all_days.index(d) - 1
                    if prev_d_idx >= 0:
                        prev_d = all_days[prev_d_idx]
                        if prev_d in price_series.index:
                            sells_x.append(prev_d)
                            sells_y.append(price_series.loc[prev_d])
                    in_position = False

            # Add Markers
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

    fig.update_layout(title=main_title, height=1200, template="plotly_dark", hovermode="x unified")

    # Update Y-axes for subplots to show percentage scale
    for i in range(2, 5):
        fig.update_yaxes(title_text="Price (Base 100)", row=i, col=1)

    fig.write_html(report_path)
    logger.info("Interactive report saved", report_path=report_path)


def run_backtest(
    start_date="2025-10-23", end_date="2026-01-23", initial_cash=10000, topk=5, benchmark="QQQ"
):
    logger.info("Starting backtest", start_date=start_date, end_date=end_date)
    logger.info("Initial cash", initial_cash=initial_cash)
    logger.info("Strategy: CLASSIFIER SNIPER (Prob > 0.55 + MA60 Filter)")
    logger.info("Benchmark", benchmark=benchmark)

    # 1. Initialize Qlib
    qlib.init(provider_uri="data/watchlist")

    # 2. Load Watchlist & Instruments
    watchlist = load_watchlist("configs/watchlist.yaml")
    us_tickers = watchlist.get("us", [])
    if benchmark not in us_tickers:
        us_tickers.append(benchmark)

    target_instruments = []
    data_dir = "data/watchlist"
    instruments_path = Path(data_dir) / "instruments" / "all.txt"
    all_instruments = []
    if instruments_path.exists():
        with open(instruments_path) as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    all_instruments.append(parts[0])

    for t in us_tickers:
        if t in all_instruments:
            target_instruments.append(t)

    logger.info("Universe", num_stocks=len(target_instruments))

    # 3. Load Model
    # Use the CLASSIFIER model
    with open("models/us_classifier.pkl", "rb") as f:
        model = pickle.load(f)
    logger.info("Loaded model", model_type=str(type(model)))

    # 4. Data
    from qlib.contrib.data.handler import Alpha158

    # Label: T+20
    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "fit_start_time": start_date,
        "fit_end_time": start_date,
        "instruments": target_instruments,
        "infer_processors": [
            {
                "class": "RobustZScoreNorm",
                "kwargs": {"fields_group": "feature", "clip_outlier": True},
            },
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
        "label": ["Ref($close, -20) / $close - 1"],
    }

    dh = Alpha158(**handler_kwargs)

    # Fetch feature data directly for sklearn/lgbm classifier
    logger.info("Fetching data for inference")
    df_data = dh.fetch(selector=(start_date, end_date), col_set="feature")

    # Predict Probabilities
    logger.info("Generating predictions (Probability)")
    # LGBMClassifier.predict_proba returns [prob_0, prob_1]
    probs = model.predict_proba(df_data.values)[:, 1]

    # Construct Series
    pred_scores = pd.Series(probs, index=df_data.index)

    # 5. Simulation
    # Fetch Prices AND MA60
    logger.info("Fetching Market Data & MA60")
    fields = ["$close", "$open", "$high", "$low", "Mean($close, 60)"]
    names = ["close", "open", "high", "low", "ma60"]

    market_data = D.features(target_instruments, fields, start_time=start_date, end_time=end_date)
    market_data.columns = names

    close_prices = market_data["close"].unstack(level="instrument")
    ma60_data = market_data["ma60"].unstack(level="instrument")
    daily_rets = close_prices.pct_change()

    if benchmark in daily_rets.columns:
        bench_ret = daily_rets[benchmark]
    else:
        bench_ret = pd.Series(0, index=daily_rets.index)

    portfolio_value = initial_cash
    history = []
    trading_days = sorted(daily_rets.index)
    current_holdings = []

    # Track Stats
    ticker_profits = {t: 0.0 for t in target_instruments}
    trade_logs = {}

    for i, date in enumerate(trading_days):
        trade_logs[date] = list(current_holdings)

        if i == 0:
            continue

        day_pnl = 0
        if current_holdings:
            stock_weight = 1.0 / topk

            for ticker in current_holdings:
                if ticker in daily_rets.columns:
                    ret = daily_rets.loc[date, ticker]
                    if pd.isna(ret):
                        ret = 0
                    day_pnl += ret * stock_weight
                    ticker_profits[ticker] += ret

            portfolio_value = portfolio_value * (1 + day_pnl)

        try:
            today_scores = pred_scores.xs(date, level="datetime")

            # --- DUAL FILTER LOGIC ---
            # 1. Sort by Score
            candidates = today_scores.sort_values(ascending=False).head(topk)

            valid_picks = []
            for ticker, score in candidates.items():
                # Filter 1: Trend Score > 0
                if score <= 0:
                    continue

                # Filter 2: Price > MA60
                if ticker in ma60_data.columns:
                    price = close_prices.loc[date, ticker]
                    ma60 = ma60_data.loc[date, ticker]

                    if pd.notna(price) and pd.notna(ma60) and price > ma60:
                        valid_picks.append(ticker)

            if set(valid_picks) != set(current_holdings):
                portfolio_value = portfolio_value * (1 - 0.0005)

            current_holdings = valid_picks

        except KeyError:
            current_holdings = []

        history.append(
            {
                "date": date,
                "portfolio_value": portfolio_value,
                "benchmark_value": initial_cash
                * (1 + bench_ret.loc[:date].fillna(0).add(1).cumprod().iloc[-1] - 1),
                "holdings": ", ".join(current_holdings),
                "daily_return": day_pnl,
            }
        )

    # 6. Final Results
    hist_df = pd.DataFrame(history).set_index("date")
    total_ret = (hist_df["portfolio_value"].iloc[-1] / initial_cash) - 1
    bench_total_ret = (hist_df["benchmark_value"].iloc[-1] / initial_cash) - 1

    # Model Metadata for Report
    model_info = {
        "algorithm": "Ridge LinearModel",
        "train_period": "2018-01-01 to 2023-12-31",
        "label": "T+20 Forward Return",
    }

    logger.info("Backtest Results")
    logger.info("Final portfolio value", value=f"${hist_df['portfolio_value'].iloc[-1]:,.2f}")
    logger.info("Strategy return", pct=f"{total_ret * 100:.2f}%")
    logger.info("Benchmark return", benchmark=benchmark, pct=f"{bench_total_ret * 100:.2f}%")

    generate_interactive_report(
        hist_df, benchmark, close_prices, ticker_profits, trade_logs, model_info=model_info
    )


if __name__ == "__main__":
    fire.Fire(run_backtest)
