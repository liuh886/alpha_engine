import os
import pickle
from pathlib import Path


def inspect_latest_artifact():
    mlruns_dir = Path("mlruns")
    latest_time = 0
    latest_report = None
    latest_run_dir = None

    for root, dirs, files in os.walk(mlruns_dir):
        if "report_normal_1day.pkl" in files:
            file_path = Path(root) / "report_normal_1day.pkl"
            mtime = file_path.stat().st_mtime
            if mtime > latest_time:
                latest_time = mtime
                latest_report = file_path
                latest_run_dir = Path(root).parent  # artifacts parent

    if not latest_report:
        print("No report found.")
        return

    print(f"Inspecting: {latest_report}")
    with open(latest_report, "rb") as f:
        df = pickle.load(f)
        print("Columns:", df.columns.tolist())
        print("First 2 rows:")
        print(df.head(2))

    # Check params
    print(f"\nChecking Params in {latest_run_dir}")
    params_dir = latest_run_dir / "params"
    if params_dir.exists():
        print("Params found:")
        for p in params_dir.glob("*"):
            print(f"  {p.name}")
    else:
        print("No params directory found in run dir. Checking parent...")
        # MLflow structure: exp/run/params
        # Current path might be exp/run/artifacts/portfolio_analysis/..
        # Let's climb up
        run_root = latest_run_dir
        while "params" not in [d.name for d in run_root.iterdir()] and run_root.parent != run_root:
            run_root = run_root.parent

        params_dir = run_root / "params"
        if params_dir.exists():
            print(f"Params found in {params_dir}:")
            for p in params_dir.glob("*"):
                print(f"  {p.name}")
        else:
            print("Params NOT found.")


if __name__ == "__main__":
    inspect_latest_artifact()
