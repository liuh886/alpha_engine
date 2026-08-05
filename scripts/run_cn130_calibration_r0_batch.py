"""Run R0/R1 score ledgers for the frozen feasible 2022-2023 calibration windows."""
from __future__ import annotations

import argparse
from pathlib import Path

import scripts.run_cn130_ranking_batch as base

CALIBRATION_WINDOWS = {
    "2022H2": ("2022-07-01", "2022-12-31"),
    "2023H1": ("2023-01-01", "2023-06-30"),
    "2023H2": ("2023-07-01", "2023-12-31"),
}


def main() -> None:
    base.WINDOWS.update(CALIBRATION_WINDOWS)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--window", choices=sorted(CALIBRATION_WINDOWS), required=True)
    args = parser.parse_args()
    base.run(
        args.root.resolve(),
        args.provider_dir.resolve(),
        args.output_dir.resolve(),
        args.window,
        "r0r1",
    )


if __name__ == "__main__":
    main()
