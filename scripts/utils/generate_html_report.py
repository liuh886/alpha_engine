import pickle
from pathlib import Path

import pandas as pd


def generate_html(market):
    print(f"Generating HTML report for {market.upper()}...")
    
    # 1. Load latest model
    models_dir = Path("models")
    model_files = sorted(list(models_dir.glob(f"{market}_model_*.pkl")))
    if not model_files:
        print(f"No models found for {market}")
        return
    latest_model_path = model_files[-1]
    with open(latest_model_path, "rb") as f:
        model = pickle.load(f)
    
    # 2. Get Data (2025 Test Set)
    csv_dir = Path("data/csv_clean")
    universe_file = Path(f"data/watchlist/instruments/{market}.txt")
    with open(universe_file) as f:
        tickers = [line.split("\t")[0] for line in f]
    
    all_res = []
    for t in tickers:
        p = csv_dir / f"{t}.csv"
        if not p.exists(): continue
        df = pd.read_csv(p)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        
        # 2025 Range (plus context)
        df = df[df.index >= "2024-11-01"].copy()
        if len(df) < 60: continue
        
        # Features (Match training: 13 features)
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
        
        X = pd.concat([f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13], axis=1).dropna()
        X.columns = [f"f{i}" for i in range(1, 14)]
        
        # Predict
        scores = model.model.predict(X)
        X["score"] = scores
        X["label"] = df["close"].shift(-5) / df["close"].shift(-1) - 1
        X["instrument"] = t
        all_res.append(X[X.index >= "2025-01-01"])
        
    full_df = pd.concat(all_res).dropna()
    
    # 3. Strategy Simulation (Top 10 daily)
    daily_stats = []
    dates = sorted(full_df.index.unique())
    cum_ret = 1.0
    bench_cum = 1.0
    
    for d in dates:
        day_df = full_df.loc[d]
        if isinstance(day_df, pd.Series): continue
        
        top10 = day_df.nlargest(10, "score")
        ret = top10["label"].mean() / 5.0
        mkt_ret = day_df["label"].mean() / 5.0
        
        cum_ret *= (1 + ret)
        bench_cum *= (1 + mkt_ret)
        
        daily_stats.append({
            "date": d.strftime("%Y-%m-%d"),
            "strategy": cum_ret,
            "benchmark": bench_cum
        })
        
    stats_df = pd.DataFrame(daily_stats)
    latest_date = full_df.index.max()
    
    # 4. Generate HTML
    html_content = f"""<html>
<head>
    <title>Trading Report: {market.upper()}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f4f4f9; }}
        .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .metric-card {{ display: inline-block; background: #eee; padding: 15px; margin-right: 10px; border-radius: 5px; min-width: 150px; }}
        .metric-val {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
        th {{ background: #f8f9fa; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>AI Backtest Report: {market.upper()} (2025)</h1>
        <p><b>Model:</b> {latest_model_path.name}</p>
        <p><b>Target:</b> 5-Day Forward Return (Ranker Mode)</p>
        <div class="metrics">
            <div class="metric-card">
                <div>Strategy Total Return</div>
                <div class="metric-val">{(cum_ret-1)*100:.2f}%</div>
            </div>
            <div class="metric-card">
                <div>Benchmark Total Return</div>
                <div class="metric-val">{(bench_cum-1)*100:.2f}%</div>
            </div>
            <div class="metric-card">
                <div>Excess Return</div>
                <div class="metric-val">{(cum_ret - bench_cum)*100:+.2f}%</div>
            </div>
        </div>
        <h2>Top 10 Picks for Latest Date ({latest_date.date()})</h2>
        <table>
            <tr><th>Rank</th><th>Ticker</th><th>Alpha Score</th></tr>"""
    
    # Get latest picks
    top_picks = full_df.loc[latest_date].nlargest(10, "score")
    for i, (inst, row) in enumerate(top_picks.iterrows()):
        html_content += f"\n            <tr><td>{i+1}</td><td>{row['instrument']}</td><td>{row['score']:.4f}</td></tr>"
        
    html_content += """
        </table>
    </div>
</body>
</html>"""
    
    output_path = Path(f"reports/{market}_report.html")
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html_content)
    print(f"HTML Report saved to {output_path}")

if __name__ == "__main__":
    generate_html("us")
    generate_html("cn")
