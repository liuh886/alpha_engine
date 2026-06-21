import pickle
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex


def register():
    mlruns_dir = PROJECT_ROOT / "mlruns"
    model_list_path = PROJECT_ROOT / "models" / "model_list.yaml"
    db_path = resolve_metadata_db_path(PROJECT_ROOT)
    model_index = ModelRegistryIndex(db_path=db_path)

    # Load existing model list
    if model_list_path.exists():
        with open(model_list_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"models": []}
    else:
        data = {"models": []}

    existing_run_ids = {m.get("run_id") for m in data["models"] if m.get("run_id")}

    # Scan all experiment directories
    new_count = 0
    for exp_dir in mlruns_dir.iterdir():
        if not exp_dir.is_dir() or exp_dir.name in ["0", ".trash"]:
            continue

        for run_dir in exp_dir.iterdir():
            if not run_dir.is_dir() or run_dir.name == "artifacts":
                continue

            run_id = run_dir.name
            if run_id in existing_run_ids:
                continue

            # Check for backtest report
            report_path = run_dir / "artifacts" / "portfolio_analysis" / "report_normal_1day.pkl"
            if not report_path.exists():
                # Try higher level
                report_path = run_dir / "artifacts" / "report_normal_1day.pkl"

            if report_path.exists():
                print(f"Registering new run: {run_id}")

                # Guess market
                market = "us"
                meta_path = run_dir / "meta.yaml"
                if meta_path.exists():
                    try:
                        with open(meta_path) as f:
                            meta = yaml.safe_load(f)
                            # Check tags
                            tags = meta.get("tags", {})
                            if "cn" in str(tags).lower():
                                market = "cn"
                    except Exception:
                        pass

                try:
                    with open(report_path, "rb") as f:
                        df = pickle.load(f)
                    last_date = str(df.index[-1].date())
                except Exception:
                    last_date = "unknown"

                entry = {
                    "id": f"auto_{run_id[:8]}",
                    "tag": f"Auto-Registered {run_id[:8]}",
                    "market": market,
                    "run_id": run_id,
                    "created_at": str(datetime.fromtimestamp(report_path.stat().st_mtime).date()),
                    "backtest": {"period": f"until {last_date}", "metrics": {}},
                }

                data["models"].append(entry)
                model_index.upsert_entry(entry)
                existing_run_ids.add(run_id)
                new_count += 1

    if new_count > 0:
        # Sort by created_at DESC
        data["models"].sort(key=lambda x: x.get("created_at", ""), reverse=True)
        with open(model_list_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, sort_keys=False)
        print(f"Successfully registered {new_count} new models.")
    else:
        print("No new models to register.")


if __name__ == "__main__":
    register()
