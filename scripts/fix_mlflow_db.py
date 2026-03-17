import sqlite3
import os

db_path = '/mnt/GitHub/alpha_engine/artifacts/mlflow.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    # Get current artifact locations
    rows = conn.execute("SELECT experiment_id, artifact_location FROM experiments").fetchall()
    for exp_id, loc in rows:
        if 'C:/' in loc:
            parts = loc.replace('\\', '/').split('2601_Trading/')
            if len(parts) > 1:
                new_loc = 'file:/mnt/GitHub/alpha_engine/' + parts[1]
                conn.execute("UPDATE experiments SET artifact_location = ? WHERE experiment_id = ?", (new_loc, exp_id))
                print(f"Fixed experiment {exp_id}: {loc} -> {new_loc}")
    
    # Also fix run artifacts
    rows = conn.execute("SELECT run_uuid, artifact_uri FROM runs").fetchall()
    for run_id, uri in rows:
        if uri and 'C:/' in uri:
            parts = uri.replace('\\', '/').split('2601_Trading/')
            if len(parts) > 1:
                new_uri = 'file:/mnt/GitHub/alpha_engine/' + parts[1]
                conn.execute("UPDATE runs SET artifact_uri = ? WHERE run_uuid = ?", (new_uri, run_id))
                print(f"Fixed run {run_id}: {uri} -> {new_uri}")
                
    conn.commit()
    conn.close()
    print("mlflow.db updated.")
else:
    print("mlflow.db not found.")
