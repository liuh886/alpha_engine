import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from src.common.paths import ARTIFACTS_DIR


def archive_sqlite_table(table_name, output_dir):
    db_path = ARTIFACTS_DIR / "metadata" / "metadata.db"
    if not db_path.exists():
        return

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        conn.close()

        if not df.empty:
            df.to_parquet(output_dir / f"{table_name}_archive.parquet", index=False)
            print(f"Archived {table_name} to {output_dir}")
    except Exception as e:
        print(f"Failed to archive {table_name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Archive Heavy Metadata to Parquet")
    parser.add_argument("--table", type=str, default="all", help="Table to archive")
    parser.add_argument("--out", type=str, default="artifacts/archives/parquet", help="Output path")

    args = parser.parse_args()
    out_path = PROJECT_ROOT / args.out

    tables = ["backtest_runs", "model_versions", "data_snapshots"]
    if args.table != "all":
        tables = [args.table]

    for t in tables:
        archive_sqlite_table(t, out_path)


if __name__ == "__main__":
    main()
