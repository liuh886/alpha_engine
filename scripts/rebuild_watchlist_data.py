import shutil
from pathlib import Path

import pandas as pd


def rebuild():
    src_dir = Path("data/csv_source")
    clean_dir = Path("data/csv_clean")
    clean_dir.mkdir(exist_ok=True)

    # 1. Clean CSVs
    print("Cleaning CSVs...")
    valid_count = 0
    for f in src_dir.glob("*.csv"):
        try:
            df = pd.read_csv(f)
            # Must have enough data
            if len(df) < 1000:
                continue

            # Must have no empty critical columns
            if df["close"].isnull().all():
                continue

            # Fill small holes
            df.ffill(inplace=True)
            df.bfill(inplace=True)

            df.to_csv(clean_dir / f.name, index=False)
            valid_count += 1
        except:
            continue

    print(f"Cleaned {valid_count} robust CSVs.")

    # 2. Re-run Dump
    # Use the canonical dump script pointed to csv_clean
    import subprocess
    import sys

    print("Re-running binary dump...")
    # Wipe old
    watchlist_dir = Path("data/watchlist")
    if watchlist_dir.exists():
        shutil.rmtree(watchlist_dir)

    subprocess.run(
        [
            sys.executable,
            "scripts/dump_bin.py",
            "dump_all",
            "--data_path",
            "data/csv_clean",
            "--qlib_dir",
            "data/watchlist",
        ],
        check=True,
    )

    # 3. Update Universes
    subprocess.run([sys.executable, "scripts/create_universes.py"], check=True)
    print("Data rebuild complete.")


if __name__ == "__main__":
    rebuild()
