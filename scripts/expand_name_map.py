import io
from pathlib import Path

import pandas as pd
import requests
import yaml


def load_name_map():
    path = Path("configs/name_map.yaml")
    if path.exists():
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}

def save_name_map(data):
    # We want to preserve comments and structure if possible, 
    # but for a bulk update, a clean rewrite is easier.
    # However, to be nice, we'll try to group them.
    
    us_data = {k: v for k, v in data.items() if not k.isdigit() and not k.endswith(".HK") and len(k) < 10}
    cn_data = {k: v for k, v in data.items() if k.isdigit()}
    hk_data = {k: v for k, v in data.items() if k.endswith(".HK")}
    other_data = {k: v for k, v in data.items() if k not in us_data and k not in cn_data and k not in hk_data}
    
    with open("configs/name_map.yaml", 'w', encoding='utf-8') as f:
        f.write("# Mapping of Ticker Symbols to Human-Readable Names\n\n")
        
        f.write("# US Market\n")
        for k in sorted(us_data.keys()):
            f.write(f"{k}: \"{us_data[k]}\"\n")
        f.write("\n")
        
        f.write("# CN Market (A-Shares & Indices)\n")
        for k in sorted(cn_data.keys()):
            f.write(f"\"{k}\": \"{cn_data[k]}\"\n")
        f.write("\n")
        
        f.write("# HK Market\n")
        for k in sorted(hk_data.keys()):
            f.write(f"\"{k}\": \"{hk_data[k]}\"\n")
        f.write("\n")
        
        if other_data:
            f.write("# Other / ETFs\n")
            for k in sorted(other_data.keys()):
                f.write(f"\"{k}\": \"{other_data[k]}\"\n")

def fetch_nasdaq100_names():
    print("Fetching NASDAQ 100 names from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        
        tables = pd.read_html(io.StringIO(r.text))
        for df in tables:
            if 'Ticker' in df.columns and 'Company' in df.columns:
                return dict(zip(df['Ticker'], df['Company']))
            if 'Symbol' in df.columns and 'Company' in df.columns:
                return dict(zip(df['Symbol'], df['Company']))
        return {}
    except Exception as e:
        print(f"Error fetching NASDAQ 100: {e}")
        return {}

def fetch_csi300_names():
    print("Fetching CSI 300 names...")
    # Using the discovered URL
    url = "https://yfiua.github.io/index-constituents/constituents-csi300.csv"
    try:
        r = requests.get(url)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # Expected columns: code, name (or similar)
        # Let's check columns
        cols = df.columns.tolist()
        print(f"CSI 300 CSV Columns: {cols}")
        
        # Mapping based on common names
        code_col = next((c for c in cols if 'code' in c.lower() or 'symbol' in c.lower()), None)
        name_col = next((c for c in cols if 'name' in c.lower()), None)
        
        if code_col and name_col:
            print(f"Using columns: code={code_col}, name={name_col}")
            # Clean code (remove .SH, .SZ if present)
            df[code_col] = df[code_col].astype(str).str.extract('(\d{6})')
            res = dict(zip(df[code_col], df[name_col]))
            # Remove NaN keys
            res = {k: v for k, v in res.items() if isinstance(k, str) and len(k) == 6}
            return res
    except Exception as e:
        print(f"Error fetching CSI 300: {e}")
        return {}

def main():
    name_map = load_name_map()
    
    # 1. Update US (Nasdaq 100)
    us_names = fetch_nasdaq100_names()
    if us_names:
        print(f"Fetched {len(us_names)} US names.")
        for ticker, name in us_names.items():
            if ticker not in name_map:
                name_map[ticker] = name
                
    # 2. Update CN (CSI 300)
    cn_names = fetch_csi300_names()
    if cn_names:
        print(f"Fetched {len(cn_names)} CN names.")
        for code, name in cn_names.items():
            if code not in name_map:
                name_map[code] = name
            else:
                # Update if existing name is much shorter (often happens with initial manual entries)
                if len(name) > len(name_map[code]) + 5:
                    name_map[code] = name
        
    save_name_map(name_map)
    print("Updated configs/name_map.yaml")

if __name__ == "__main__":
    main()
