from pathlib import Path

import yaml


def create_universes():
    with open("configs/watchlist.yaml") as f:
        watchlist = yaml.safe_load(f)
    
    inst_dir = Path("data/watchlist/instruments")
    inst_dir.mkdir(exist_ok=True)
    
    # Read all.txt to get the start/end dates
    all_data = {}
    with open(inst_dir / "all.txt") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) == 3:
                all_data[parts[0]] = (parts[1], parts[2])

    for market in ['cn', 'us']:
        tickers = watchlist.get(market, [])
        with open(inst_dir / f"{market}.txt", "w") as f_out:
            for t in tickers:
                if t in all_data:
                    start, end = all_data[t]
                    f_out.write(f"{t}\t{start}\t{end}\n")
        print(f"Created universe for {market}: {len(tickers)} tickers")

if __name__ == "__main__":
    create_universes()
