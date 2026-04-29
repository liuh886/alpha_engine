from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


def load_pkl(path: Path):
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def compare_series(s1: pd.Series, s2: pd.Series, name: str, atol=1e-7):
    # Align by index
    common_idx = s1.index.intersection(s2.index)
    if len(common_idx) == 0:
        return False, f"{name}: No common index found."

    v1 = s1.loc[common_idx]
    v2 = s2.loc[common_idx]

    diff = (v1 - v2).abs()
    max_diff = diff.max()

    if max_diff > atol:
        return False, f"{name}: Max diff {max_diff} exceeds tolerance {atol}."
    return True, f"{name}: Matches (Max diff: {max_diff})"


def main():
    parser = argparse.ArgumentParser(
        description="Verify reproducibility by comparing two backtest prediction artifacts."
    )
    parser.add_argument("run_id_1", type=str, help="First Run ID (Baseline)")
    parser.add_argument("run_id_2", type=str, help="Second Run ID (New)")
    args = parser.parse_args()

    mlruns = PROJECT_ROOT / "mlruns"

    def find_pred(run_id):
        for exp in mlruns.iterdir():
            if not exp.is_dir():
                continue
            p = exp / run_id / "artifacts" / "pred.pkl"
            if p.exists():
                return p
        return None

    p1 = find_pred(args.run_id_1)
    p2 = find_pred(args.run_id_2)

    if not p1 or not p2:
        print(
            f"Error: Could not find pred.pkl for one or both runs ({args.run_id_1}, {args.run_id_2})"
        )
        sys.exit(1)

    print(f"Comparing Baseline: {args.run_id_1} <-> New: {args.run_id_2}")

    d1 = load_pkl(p1)
    d2 = load_pkl(p2)

    # pred.pkl is usually a DataFrame with 'score' column
    s1 = d1["score"] if isinstance(d1, pd.DataFrame) else d1
    s2 = d2["score"] if isinstance(d2, pd.DataFrame) else d2

    ok, msg = compare_series(s1, s2, "Prediction Scores")
    print(f"Result: {'[PASS]' if ok else '[FAIL]'} {msg}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
