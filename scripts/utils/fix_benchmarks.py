from pathlib import Path

import pandas as pd
import yfinance as yf


def fix_benchmarks():
    csv_dir = Path("data/csv_source")

    # 1. Fetch 000300.SS
    print("Fetching 000300 (CSI 300)...")
    df = yf.download("000300.SS", period="5y", auto_adjust=True)
    if not df.empty:
        # Standardize
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df["money"] = df["close"] * df["volume"]
        df["factor"] = 1.0
        df["vwap"] = df["close"]
        df.to_csv(csv_dir / "000300.csv", index=False)
        print("000300.csv updated.")

    # 2. Fetch SPY
    print("Fetching SPY...")
    df = yf.download("SPY", period="5y", auto_adjust=True)
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df["money"] = df["close"] * df["volume"]
        df["factor"] = 1.0
        df["vwap"] = df["close"]
        df.to_csv(csv_dir / "SPY.csv", index=False)
        print("SPY.csv updated.")


if __name__ == "__main__":
    fix_benchmarks()
