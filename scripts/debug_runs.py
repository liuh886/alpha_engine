import pickle
from datetime import datetime
from pathlib import Path

mlruns_dir = Path("mlruns")
runs = list(mlruns_dir.rglob("report_normal_1day.pkl"))

print(f"Found {len(runs)} backtest reports.\n")
for p in sorted(runs, key=lambda x: x.stat().st_mtime, reverse=True):
    try:
        with open(p, "rb") as f:
            df = pickle.load(f)
        last_date = df.index[-1]
        print(f"File: {p}")
        print(f"  Modified: {datetime.fromtimestamp(p.stat().st_mtime)}")
        print(f"  Last Date in Index: {last_date}")
        print(f"  Run ID: {p.parent.parent.name}")
        print("-" * 20)
    except Exception as e:
        print(f"Error loading {p}: {e}")
