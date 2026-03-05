import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf


def load_watchlist():
    # Path relative to project root
    with open("configs/watchlist.yaml") as f:
        return yaml.safe_load(f)

def get_yfinance_symbol(ticker, market):
    ticker = str(ticker)
    if market == 'us':
        return ticker
    elif market == 'hk':
        if not ticker.endswith('.HK'):
            return f"{ticker}.HK"
        return ticker
    elif market == 'cn':
        # Simple heuristic for A-share suffixes
        if ticker.startswith('6') or ticker.startswith('5'): # SH
            return f"{ticker}.SS"
        elif ticker.startswith('0') or ticker.startswith('3') or ticker.startswith('1'): # SZ
            return f"{ticker}.SZ"
    return ticker

def dump_to_qlib_csv(df, symbol, output_dir):
    # Standardize columns: date, open, close, high, low, volume, amount(optional), factor(optional)
    if df.empty:
        return False
    
    # Handle yfinance MultiIndex columns (Price, Ticker)
    if isinstance(df.columns, pd.MultiIndex):
        # If columns are like (Open, AAPL), (Close, AAPL)...
        # We drop the second level
        df.columns = df.columns.droplevel(1)
        
    df = df.reset_index()
    
    # Rename columns to lower case
    new_cols = []
    for c in df.columns:
        if isinstance(c, str):
            new_cols.append(c.lower())
        else:
            new_cols.append(str(c).lower())
    df.columns = new_cols
    
    # Ensure date is format YYYY-MM-DD
    # yfinance usually has 'date' or 'Date' as index which becomes column after reset_index
    
    data = pd.DataFrame()
    try:
        data['date'] = df['date']
        data['open'] = df['open']
        data['high'] = df['high']
        data['low'] = df['low']
        data['close'] = df['close']
        data['volume'] = df['volume']
    except KeyError:
        # Sometimes columns might be missing or named differently
        # print(f"Missing column for {symbol}: {e}")
        return False

    # Estimate Amount/Money
    data['amount'] = df['close'] * df['volume'] 
    
    data['factor'] = 1.0
    
    # Save to CSV
    csv_path = output_dir / f"{symbol}.csv"
    data.to_csv(csv_path, index=False)
    return True

def main():
    print("Loading watchlist...")
    try:
        watchlist = load_watchlist()
    except FileNotFoundError:
        print("Error: configs/watchlist.yaml not found. Run from project root.")
        return

    # Temp dir for CSVs
    csv_dir = Path("data/csv_source")
    csv_dir.mkdir(parents=True, exist_ok=True)
    
    # Target Qlib dir
    qlib_dir = Path("data/watchlist")
    qlib_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    fail_count = 0
    
    for market, tickers in watchlist.items():
        if not tickers:
            continue
            
        print(f"\nFetching {market.upper()} data ({len(tickers)} tickers)...")
        
        for t in tickers:
            yf_sym = get_yfinance_symbol(t, market)
            # print(f"  Downloading {t} ({yf_sym})...", end="", flush=True)
            
            try:
                # Download last 5 years
                df = yf.download(yf_sym, period="5y", progress=False, auto_adjust=True)
                
                # Check emptiness
                if len(df) < 10:
                    # print(f" Empty or too short. Skipped.")
                    fail_count += 1
                    continue
                    
                if dump_to_qlib_csv(df, str(t), csv_dir):
                    print(f"  [+] {t}")
                    success_count += 1
                else:
                    print(f"  [-] {t} (Write Failed)")
                    fail_count += 1
            except Exception as e:
                print(f"  [!] {t} Error: {e}")
                fail_count += 1

    print(f"\nDownloaded {success_count} instruments. Failed: {fail_count}")
    
    if success_count > 0:
        print("\nConverting to Qlib Binary Format...")
        
        cmd = [
            sys.executable, "scripts/dump_bin.py", "dump_all",
            "--data_path", str(csv_dir),
            "--qlib_dir", str(qlib_dir),
            "--include_fields", "open,high,low,close,volume,amount,factor",
            "--date_field_name", "date",
            "--symbol_field_name", "symbol"
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print("Data conversion complete.")
        except subprocess.CalledProcessError:
            print("Warning: Data conversion failed (likely module missing). Please run dump_bin manually.")
            print(f"CSVs are saved in {csv_dir}")
        except Exception as e:
            print(f"Warning: Conversion step encountered error: {e}")
            print(f"CSVs are saved in {csv_dir}")

if __name__ == "__main__":
    main()
