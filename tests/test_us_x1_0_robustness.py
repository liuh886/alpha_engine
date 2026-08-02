from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analyze_us_x1_0_robustness.py"
CONTRACT = ROOT / "configs/research_experiments/us_x1_0_robustness_v1.yaml"
MODEL = ROOT / "configs/models/us_x1_0.yaml"
CANDIDATE = (
    "xgb:daily_ranker:risk_controlled_momentum:"
    "gain7_round200_leaves31_leaf20_lr0.03"
)


def _load_module() -> ModuleType:
    name = "analyze_us_x1_0_robustness"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _candidate(
    total_return: float,
    benchmark_return: float,
    costs: float,
    drawdown: float,
    names: list[str],
) -> dict[str, object]:
    return {
        "candidate_name": CANDIDATE,
        "orientation": "original",
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "excess_return": total_return - benchmark_return,
        "costs": costs,
        "max_drawdown": drawdown,
        "icir": 0.2,
        "rank_ic": 0.04,
        "turnover": 6.0,
        "top_selected_stocks": names,
    }


def _write_window(
    run_dir: Path,
    label: str,
    candidate: dict[str, object],
) -> None:
    path = run_dir / "windows" / f"fixture_{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"comparison_report": {"candidates": [candidate]}}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_contract_locks_parent_effective_runtime_and_holdout() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert contract["parent_model_id"] == "us_x1_0"
    assert contract["candidate"]["effective_runtime"]["learning_rate"] == 0.05
    assert contract["windows"]["development"] == [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]
    assert contract["windows"]["reporting_only_consumed_holdout"] == ["2026H1"]
    assert contract["windows"]["consumed_holdout_may_enter_decision"] is False
    assert contract["next_version_policy"]["automatic_model_update"] is False


def test_full_backtest_stress_identifies_tail_and_recurrence_block(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "run"
    provider = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["provider"][
        "required_identity_sha256"
    ]
    (run_dir / "run_status.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_status.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "runtime_metadata": {"provider_identity_sha256": provider},
            }
        ),
        encoding="utf-8",
    )

    recurring = ["A", "B", "C", "D", "E"]
    unique = [f"N{i}" for i in range(40)]
    rows = [
        ("2024H1", 0.325426, 0.194209, 0.01446667, -0.029417),
        ("2024H2", 0.435849, 0.068419, 0.01486667, -0.117242),
        ("2025H1", 0.096846, 0.077012, 0.0126, -0.28361),
        ("2025H2", 0.59568, 0.129391, 0.0114, -0.100614),
        ("2026H1", 1.036889, 0.155057, 0.01153333, -0.06799),
    ]
    for index, (label, total, benchmark, costs, drawdown) in enumerate(rows):
        names = recurring + unique[index * 10 : index * 10 + 10]
        _write_window(
            run_dir,
            label,
            _candidate(total, benchmark, costs, drawdown, names),
        )

    report = module.build_report(run_dir, CONTRACT, MODEL)
    assert report["decision"] == "tail_risk_or_concentration_blocks_x1_1"
    assert report["all_window_recurring_names"] == recurring
    assert report["all_window_recurring_name_count"] == 5
    assert report["worst_development_drawdown"] == -0.28361
    assert all(
        value > 0
        for value in report["leave_one_window_out_relative_excess"].values()
    )
    sixty_bps = next(
        row for row in report["cost_stress"] if row["cost_bps"] == 60
    )
    assert sixty_bps["compounded_relative_excess"] > 0
    assert report["reporting_only_consumed_holdout"]["2026H1"][
        "total_return"
    ] == 1.036889
