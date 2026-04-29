from pathlib import Path

import pandas as pd
from tqdm import tqdm


def calculate_ma_deviation(series, window=20):
    ma = series.rolling(window=window).mean()
    # Deviation: (Price - MA) / MA
    return (series - ma) / ma


def add_global_features():
    csv_dir = Path("data/csv_source")
    if not csv_dir.exists():
        print("Error: data/csv_source not found.")
        return

    # 1. Identify Market Benchmarks
    # US: SPY
    # CN: 000300 (CSI 300) -> 000300.csv

    benchmarks = {"us": "SPY", "cn": "000300"}

    global_data = {}

    print("Loading Benchmark Data...")
    for market, ticker in benchmarks.items():
        path = csv_dir / f"{ticker}.csv"
        if not path.exists():
            print(f"Warning: Benchmark {ticker} for {market} not found in {csv_dir}")
            continue

        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)

        # Calculate Features
        # 1. MA20 Deviation (Short Term Trend)
        # 2. MA60 Deviation (Medium Term Trend)
        # 3. Volatility (20 day)

        close = df["close"]
        feat = pd.DataFrame(index=df.index)

        feat[f"mkt_{market}_ma20_dev"] = calculate_ma_deviation(close, 20)
        feat[f"mkt_{market}_ma60_dev"] = calculate_ma_deviation(close, 60)

        # Fill NaN (early days) with 0
        feat.fillna(0, inplace=True)

        global_data[market] = feat
        print(f"Loaded {market.upper()} benchmark features from {ticker}")

    if not global_data:
        print("No benchmarks found. Aborting feature injection.")
        return

    # 2. Inject into all CSVs
    print("Injecting Global Features...")
    files = list(csv_dir.glob("*.csv"))

    # We need to know which market a stock belongs to.
    # Simple heuristic:
    # CN: Starts with digit (0, 1, 3, 5, 6)
    # US: Starts with letter
    # HK: Ends with .hk (but filename might be stripped? collect_data saved as symbol.csv)
    # Check collect_data: "00700.HK.csv"

    for f in tqdm(files):
        symbol = f.stem

        # Determine Market
        market = None
        if symbol[0].isdigit():
            # A-share or HK?
            if "HK" in symbol.upper():
                market = "hk"  # We don't have HK benchmark yet, maybe use CN?
                # For now skip HK or use CN
                market = "cn"
            else:
                market = "cn"
        else:
            market = "us"

        if market not in global_data:
            continue

        # Load Stock Data
        try:
            df = pd.read_csv(f)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df.sort_index(inplace=True)

            # Merge Global Features
            mkt_feat = global_data[market]

            # Join on index (Date)
            # Use left join to keep stock dates
            merged = df.join(mkt_feat, how="left")

            # Forward fill global features (if stock trading but market closed? rare)
            # Fill NaNs (if market data missing) with 0
            cols_to_fill = [c for c in mkt_feat.columns]
            merged[cols_to_fill] = merged[cols_to_fill].fillna(0)

            # Save back
            merged.reset_index(inplace=True)
            merged.to_csv(f, index=False)

        except Exception as e:
            print(f"Error processing {f}: {e}")

    print("Global features injected successfully.")


if __name__ == "__main__":
    add_global_features()
