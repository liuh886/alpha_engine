import pickle
import sys
from pathlib import Path

import yaml

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex


def patch_metrics():
    mlruns_dir = project_root / "mlruns"
    model_list_path = project_root / "models" / "model_list.yaml"
    db_path = resolve_metadata_db_path(project_root)
    ModelRegistryIndex(db_path=db_path)

    if not model_list_path.exists():
        return

    with open(model_list_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {"models": []}

    patched_count = 0
    for m in data.get("models", []):
        run_id = m.get("run_id")
        if not run_id:
            continue

        # Find run dir
        run_dir = None
        for exp_dir in mlruns_dir.iterdir():
            if not exp_dir.is_dir() or exp_dir.name in ["0", ".trash"]:
                continue
            cand = exp_dir / run_id
            if cand.exists():
                run_dir = cand
                break

        if not run_dir:
            continue

        port_analysis_path = run_dir / "artifacts" / "portfolio_analysis" / "port_analysis_1day.pkl"
        if not port_analysis_path.exists():
            port_analysis_path = run_dir / "artifacts" / "port_analysis_1day.pkl"

        metrics = {}
        if port_analysis_path.exists():
            try:
                with open(port_analysis_path, "rb") as f:
                    df = pickle.load(f)
                # DataFrame with multi-index e.g. ("excess_return_with_cost", "annualized_return")
                # Let's extract them
                for idx, row in df.iterrows():
                    # idx is a tuple like ('excess_return_with_cost', 'annualized_return')
                    if len(idx) == 2 and idx[0] == "excess_return_with_cost":
                        metrics[idx[1]] = float(row["risk"])
            except Exception as e:
                print(f"Failed to extract metrics for {run_id}: {e}")

        if metrics:
            if "backtest" not in m:
                m["backtest"] = {}
            m["backtest"]["metrics"] = metrics

            # Also update metadata.db
            import json
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE model_versions SET metrics_json = ? WHERE run_id = ?",
                (json.dumps(metrics), run_id),
            )
            conn.commit()
            conn.close()
            patched_count += 1
            print(f"Patched {run_id} with metrics: {metrics}")

    if patched_count > 0:
        with open(model_list_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False)
        print(f"Successfully patched {patched_count} models.")


if __name__ == "__main__":
    patch_metrics()
