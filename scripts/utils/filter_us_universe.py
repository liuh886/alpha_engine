from pathlib import Path

import pandas as pd


def filter_us():
    inst_file = Path("data/watchlist/instruments/us.txt")
    if not inst_file.exists():
        print("us.txt not found")
        return
        
    filtered = []
    # Training range starts at 2021-01-01
    required_start = pd.Timestamp("2021-01-01")
    
    with open(inst_file) as f:
        for line in f:
            symbol, start, end = line.strip().split("\t")
            start_ts = pd.Timestamp(start)
            # If stock started after our training start, it's problematic for some Qlib ops
            if start_ts <= required_start:
                filtered.append(line.strip())
            else:
                print(f"Filtering out {symbol} (Started {start})")
                
    with open(inst_file, "w") as f:
        for line in filtered:
            f.write(line + "\n")
            
    print(f"Updated us.txt: {len(filtered)} tickers remaining.")

if __name__ == "__main__":
    filter_us()
