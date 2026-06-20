import datetime
import json
import pickle
from pathlib import Path

import pandas as pd


# --- Python Backtest Engine ---
def run_simulation(market, model, top_k=10, initial_capital=100000000):
    print(f"Running simulation for {market.upper()}...")

    csv_dir = Path("data/csv_clean")
    universe_file = Path(f"data/watchlist/instruments/{market}.txt")
    if not universe_file.exists():
        return None

    with open(universe_file) as f:
        tickers = [line.split("\t")[0] for line in f]

    all_data = []
    features_cols = [f"f{i}" for i in range(1, 14)]

    for t in tickers:
        p = csv_dir / f"{t}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[df.index >= "2024-11-01"].copy()
        if len(df) < 60:
            continue

        try:
            f1 = df["close"].pct_change(1)
            f2 = df["close"].pct_change(5)
            f3 = df["close"].pct_change(10)
            f4 = df["close"].pct_change(20)
            f5 = df["close"] / df["close"].rolling(5).mean() - 1
            f6 = df["close"] / df["close"].rolling(20).mean() - 1
            f7 = df["close"] / df["close"].rolling(60).mean() - 1
            f8 = df["close"].rolling(20).std() / df["close"].rolling(20).mean()
            f9 = (df["high"] - df["low"]) / df["close"]
            f10 = df["volume"] / df["volume"].rolling(5).mean()
            f11 = df["volume"] / df["volume"].rolling(20).mean()
            mkt_col20 = f"mkt_{market}_ma20_dev"
            mkt_col60 = f"mkt_{market}_ma60_dev"
            f12 = df[mkt_col20] if mkt_col20 in df.columns else pd.Series(0, index=df.index)
            f13 = df[mkt_col60] if mkt_col60 in df.columns else pd.Series(0, index=df.index)

            X = pd.concat([f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13], axis=1)
            X.columns = features_cols
            X = X.dropna()

            scores = model.model.predict(X)
            res = pd.DataFrame(index=X.index)
            res["score"] = scores
            res["close"] = df.loc[X.index, "close"]
            res["instrument"] = t
            all_data.append(res)
        except Exception:
            continue

    if not all_data:
        return None
    full_df = pd.concat(all_data).sort_index()
    full_df = full_df[full_df.index >= "2025-01-01"]

    dates = sorted(full_df.index.unique())
    cash = initial_capital
    positions = {}
    equity_curve = []
    finished_trades = []
    fee_rate = 0.001 if market == "cn" else 0.0005

    daily_univ_ret = (
        full_df.groupby(level=0).apply(lambda x: x["close"].mean()).pct_change().fillna(0)
    )
    bench_equity = 1.0

    for d in dates:
        day_data = full_df.loc[d]
        if isinstance(day_data, pd.Series):
            day_data = day_data.to_frame().T

        current_port_val = cash
        for t, pos in positions.items():
            price = (
                day_data[day_data["instrument"] == t]["close"].values[0]
                if t in day_data["instrument"].values
                else pos["entry_price"]
            )
            current_port_val += pos["shares"] * price

        target_tickers = day_data.nlargest(top_k, "score")["instrument"].tolist()

        to_sell = [t for t in positions if t not in target_tickers]
        for t in to_sell:
            row = day_data[day_data["instrument"] == t]
            if row.empty:
                continue
            price = float(row["close"].values[0])
            pos = positions.pop(t)
            proceeds = pos["shares"] * price
            fee = proceeds * fee_rate
            cash += proceeds - fee

            finished_trades.append(
                {
                    "symbol": t,
                    "entry_date": pos["entry_date"],
                    "exit_date": d.strftime("%Y-%m-%d"),
                    "entry_price": pos["entry_price"],
                    "exit_price": price,
                    "shares": pos["shares"],
                    "netPnl": float(proceeds - fee - (pos["shares"] * pos["entry_price"])),
                    "fee": float(fee + (pos["shares"] * pos["entry_price"] * fee_rate)),
                    "return": float(price / pos["entry_price"] - 1),
                    "reason": "Top-Rank Exit",
                }
            )

        target_val = current_port_val * 0.95 / top_k
        for t in target_tickers:
            if t not in positions:
                row = day_data[day_data["instrument"] == t]
                if row.empty:
                    continue
                price = float(row["close"].values[0])
                shares = int(target_val / price)
                if shares <= 0:
                    continue
                cost = shares * price
                fee = cost * fee_rate
                if cash >= (cost + fee):
                    cash -= cost + fee
                    positions[t] = {
                        "shares": shares,
                        "entry_price": price,
                        "entry_date": d.strftime("%Y-%m-%d"),
                    }

        bench_equity *= 1 + daily_univ_ret.loc[d]
        equity_curve.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "strategy": float(current_port_val / initial_capital),
                "benchmark": float(bench_equity),
            }
        )

    return {
        "meta": {
            "market": market.upper(),
            "generated_at": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        },
        "equityCurve": equity_curve,
        "trades": finished_trades,
    }


def generate_reports():
    models_dir = Path("models")
    template_path = Path("src/reporting/template.html")
    if not template_path.exists():
        print("Template missing!")
        return

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    for market in ["us", "cn"]:
        model_files = sorted(list(models_dir.glob(f"{market}_model_*.pkl")))
        if not model_files:
            continue

        with open(model_files[-1], "rb") as f:
            model = pickle.load(f)

        data = run_simulation(market, model)
        if not data:
            continue

        final_html = template.replace("{{DATA_JSON}}", json.dumps(data))

        out_path = Path(f"reports/{market}_interactive_backtest.html")
        out_path.parent.mkdir(exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(final_html)
        print(f"Successfully generated: {out_path}")


if __name__ == "__main__":
    generate_reports()
