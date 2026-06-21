import pickle
import sqlite3
from pathlib import Path

# Fix PROJECT_ROOT to correctly point to the project directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]
db_path = PROJECT_ROOT / "artifacts" / "metadata" / "metadata.db"

print(f"Project Root: {PROJECT_ROOT}")
print(f"Database Path: {db_path}")


def get_recommended():
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT run_id, market FROM model_versions WHERE description LIKE '%RECOMMENDED%' LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def get_pred(run_id):
    mlruns_dir = PROJECT_ROOT / "mlruns"
    for exp_dir in mlruns_dir.iterdir():
        if not exp_dir.is_dir():
            continue
        p = exp_dir / run_id / "artifacts" / "pred.pkl"
        if p.exists():
            with open(p, "rb") as f:
                return pickle.load(f)
    return None


row = get_recommended()
if row:
    print(f"Recommended Run ID: {row['run_id']} ({row['market']})")
    pred = get_pred(row["run_id"])
    if pred is not None:
        print("Prediction head:")
        print(pred.head())
    else:
        print("pred.pkl not found.")
else:
    print("No RECOMMENDED model found.")
