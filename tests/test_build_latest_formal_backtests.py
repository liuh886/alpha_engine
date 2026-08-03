from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_latest_formal_backtests import (
    LatestFormalBacktestError,
    verify_duplicate_extensions,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(root: Path, *, changed_return: bool = False, counts: bool = False) -> Path:
    experiment_id = "fixture"
    _write(
        root / "walk_forward_windows.json",
        {
            "experiment_id": experiment_id,
            "windows": [
                {
                    "label": "2026H2",
                    "status": "included",
                    "complete": False,
                    "counts_toward_min_windows": counts,
                    "effective_test_end": "2026-07-31",
                }
            ],
        },
    )
    period_return = 0.02 if changed_return else 0.01
    gross_return = period_return + 0.001
    trace = {
        "candidate_name": "xgb:daily_ranker:frozen",
        "orientation": "original",
        "forward_horizon_sessions": 10,
        "top_n": 2,
        "rebalance_days": 10,
        "cost_bps": 20.0,
        "points": [
            {
                "signal_date": "2026-07-01",
                "net_period_return": period_return,
                "nav_after_forward_horizon": 1.0 + period_return,
                "benchmark_nav_after_forward_horizon": 1.005,
                "drawdown": 0.0,
            }
        ],
        "holdings": [
            {
                "signal_date": "2026-07-01",
                "action": "rebalance",
                "weights": {"AAA": 0.5, "BBB": 0.5},
            }
        ],
        "name_contributions": [
            {
                "signal_date": "2026-07-01",
                "forward_horizon_sessions": 10,
                "gross_portfolio_return": gross_return,
                "name_contributions": {
                    "AAA": gross_return / 2.0,
                    "BBB": gross_return / 2.0,
                },
            }
        ],
        "metrics": {
            "n_periods": 1,
            "period_returns": [period_return],
            "benchmark_period_returns": [0.005],
            "total_return": period_return,
            "benchmark_return": 0.005,
            "excess_return": period_return - 0.005,
            "turnover": 0.5,
            "costs": 0.001,
            "max_drawdown": 0.0,
            "test_start": "2026-07-01",
            "test_end": "2026-07-01",
        },
        "research_only": True,
        "trade_ready": False,
    }
    _write(
        root / "windows" / f"{experiment_id}_2026H2.json",
        {"backtest_traces": [trace]},
    )
    return root


def test_independent_extensions_must_match(tmp_path: Path) -> None:
    run_a = _run(tmp_path / "a")
    run_b = _run(tmp_path / "b")
    hashes = verify_duplicate_extensions(run_a, run_b, ("2026H2",))
    assert len(hashes["2026H2"]) == 64


def test_independent_extension_difference_fails(tmp_path: Path) -> None:
    run_a = _run(tmp_path / "a")
    run_b = _run(tmp_path / "b", changed_return=True)
    with pytest.raises(LatestFormalBacktestError, match="independent executions differ"):
        verify_duplicate_extensions(run_a, run_b, ("2026H2",))


def test_partial_window_cannot_affect_selection(tmp_path: Path) -> None:
    run_a = _run(tmp_path / "a", counts=True)
    run_b = _run(tmp_path / "b", counts=True)
    with pytest.raises(LatestFormalBacktestError, match="partial window affects selection"):
        verify_duplicate_extensions(run_a, run_b, ("2026H2",))
