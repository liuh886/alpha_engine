from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.research.experiment_harness import (
    evaluate_experiment,
    load_experiment_contract,
)


SPEC_PATH = Path(
    "configs/research_experiments/us_x1_2_risk_controlled_momentum_v1.yaml"
)
SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate_id, excess, drawdown, rank_ic in (
        ("baseline_7factor", 0.04, -0.27, 0.030),
        ("risk_controlled_9factor", 0.10, -0.20, 0.040),
    ):
        for window in SELECTION_WINDOWS:
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "window": window,
                    "cost_bps": 20,
                    "relative_excess": excess,
                    "max_drawdown": drawdown,
                    "rank_ic": rank_ic,
                }
            )
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "window": window,
                    "cost_bps": 60,
                    "relative_excess": excess / 2,
                    "max_drawdown": drawdown,
                    "rank_ic": rank_ic,
                }
            )
    return rows


def _metadata() -> dict[str, dict[str, object]]:
    return {
        "baseline_7factor": {
            "dominates_factor_baselines": False,
            "concentration": 0.42,
        },
        "risk_controlled_9factor": {
            "dominates_factor_baselines": True,
            "concentration": 0.30,
        },
    }


def test_reporting_only_window_cannot_change_winner_or_gates() -> None:
    contract = load_experiment_contract(SPEC_PATH)
    base_rows = _rows()
    base_receipt = evaluate_experiment(
        contract,
        base_rows,
        candidate_metadata=_metadata(),
    )

    poisoned_rows = deepcopy(base_rows)
    poisoned_rows.extend(
        [
            {
                "candidate_id": "baseline_7factor",
                "window": "2026H1",
                "cost_bps": 20,
                "relative_excess": 5.0,
                "max_drawdown": -0.01,
                "rank_ic": 0.90,
            },
            {
                "candidate_id": "risk_controlled_9factor",
                "window": "2026H1",
                "cost_bps": 20,
                "relative_excess": -0.99,
                "max_drawdown": -0.99,
                "rank_ic": -0.90,
            },
        ]
    )
    poisoned_receipt = evaluate_experiment(
        contract,
        poisoned_rows,
        candidate_metadata=_metadata(),
    )

    assert base_receipt["winner"] == "risk_controlled_9factor"
    assert base_receipt["decision"] == "risk_controlled_momentum_candidate_supported"
    assert base_receipt["supported"] is True
    assert poisoned_receipt["winner"] == base_receipt["winner"]
    assert poisoned_receipt["decision"] == base_receipt["decision"]
    assert poisoned_receipt["candidates"] == base_receipt["candidates"]
    assert poisoned_receipt["reporting_windows_seen_but_not_used"] == ["2026H1"]


def test_missing_development_window_fails_closed() -> None:
    contract = load_experiment_contract(SPEC_PATH)
    rows = [
        row
        for row in _rows()
        if not (
            row["candidate_id"] == "risk_controlled_9factor"
            and row["window"] == "2025H2"
            and row["cost_bps"] == 20
        )
    ]

    with pytest.raises(ValueError, match="missing selection windows"):
        evaluate_experiment(contract, rows, candidate_metadata=_metadata())


def test_selection_and_reporting_windows_must_be_disjoint(tmp_path: Path) -> None:
    raw = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    raw["windows"]["consumed_reporting_only"] = ["2025H2"]
    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="selection/reporting windows overlap"):
        load_experiment_contract(bad_spec)
