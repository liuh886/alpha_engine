import time
from pathlib import Path


def clean_old_files(directory: str | Path, days: int = 30):
    """
    Cleans up temporary and intermediate CSV/Parquet files older than `days`.
    This helps prevent the system from consuming unbounded disk space.
    """
    now = time.time()
    cutoff = now - (days * 86400)

    dir_path = Path(directory)
    if not dir_path.exists():
        return

    deleted_count = 0
    for p in dir_path.rglob("*.*"):
        if p.suffix in [".csv", ".parquet", ".tmp"]:
            if p.stat().st_mtime < cutoff:
                print(f"[DiskManager] Removing old cache file: {p.name}")
                p.unlink()
                deleted_count += 1

    return deleted_count


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    csv_source = PROJECT_ROOT / "data" / "csv_source"
    print(f"=== Running Disk Quota Manager on {csv_source} ===")

    count = clean_old_files(csv_source, 30)
    print(f"Disk cleanup complete. Recovered space from {count} files.")
