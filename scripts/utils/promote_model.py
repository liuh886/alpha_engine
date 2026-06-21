import sqlite3
from pathlib import Path

# Correct path for scripts/utils/promote_model.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
db_path = PROJECT_ROOT / "artifacts" / "metadata" / "metadata.db"


def promote(run_id):
    if not db_path.exists():
        print(f"DB not found at {db_path}")
        return
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE model_versions SET description = 'RECOMMENDED' WHERE run_id = ?", (run_id,)
    )
    conn.commit()
    conn.close()
    print(f"Model {run_id} promoted to RECOMMENDED.")


promote("77ae12e0dec1470a90a2e3e97203261c")
