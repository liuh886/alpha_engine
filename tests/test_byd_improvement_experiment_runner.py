"""Regression test for the historical cross-architecture BYD master runner."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

import numpy as np
import pandas as pd


def _bounded_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index = pd.bdate_range("2019-11-26", "2026-08-03")
    step = np.arange(len(index), dtype=float)

    common = pd.DataFrame(
        {
            "byd_open_return": 0.0004 + 0.006 * np.sin(step / 17.0),
            "etf_open_return": 0.0002 + 0.003 * np.cos(step / 23.0),
            "common_open_eligible": True,
            "market_state": np.where((step.astype(int) // 180) % 3 == 2, "bear", "bull"),
            "drawdown_252": -0.06 + 0.03 * np.sin(step / 71.0),
            "mom_20": 0.04 + 0.06 * np.sin(step / 29.0),
            "mom_60": 0.03 + 0.04 * np.cos(step / 47.0),
            "vol_state": np.where((step.astype(int) // 90) % 2 == 0, "normal", "high"),
        },
        index=index,
    )
    signals = pd.DataFrame(
        {
            "base_byd_weight": np.where(
                (step.astype(int) // 45) % 4 == 3,
                0.75,
                1.0,
            )
        },
        index=index,
    )
    return common, signals, pd.DataFrame(index=index)


def test_master_runner_executes_all_surviving_architectures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runner = importlib.import_module("scripts.run_byd_improvement_experiments")
    common, signals, ledger = _bounded_fixture()
    output = tmp_path / "output"

    monkeypatch.setattr(
        runner,
        "parse_args",
        lambda: argparse.Namespace(
            byd_dir=tmp_path / "byd",
            etf_dir=tmp_path / "etf",
            output_dir=output,
        ),
    )
    monkeypatch.setattr(
        runner,
        "prepare_common_dataset",
        lambda _byd, _etf: (common, signals, ledger),
    )

    assert runner.main() == 0
    assert (output / "master_comparison.csv").is_file()
    for experiment in (
        "adaptive_expansion",
        "vol_target",
        "multi_signal_blend",
        "trend_fix",
    ):
        assert (output / experiment / "summary.json").is_file()
        assert (output / experiment / "evaluation.csv").is_file()
