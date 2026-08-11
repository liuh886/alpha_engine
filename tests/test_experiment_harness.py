from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.research.experiment_harness import evaluate_experiment, load_experiment_contract


SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")


def _write_spec(tmp_path: Path, *, reporting: list[str] | None = None) -> Path:
    payload = {
        "experiment_id": "us_x1_2_harness_integrity_v1",
        "snapshot": {
            "provider_identity_sha256": "a" * 64,
            "cutoff": "2026-07-31",
        },
        "windows": {
            "candidate_selection": list(SELECTION_WINDOWS),
            "consumed_reporting_only": reporting or ["2026H1"],
            "consumed_reporting_may_enter_selection": False,
        },
        "execution": {
            "base_cost_bps": 20,
            "cost_stress_bps": [20, 40, 60],
        },
        "evaluation": {
            "baseline_candidate_id": "baseline_7factor",
            "stress_cost_bps": 60,
            "decision": "risk_controlled_momentum_candidate_supported",
            "ranking": [
                "gate_pass_count",
                "worst_drawdown",
                "lower_concentration",
                "compounded_relative_excess",
            ],
            "thresholds": {
                "min_window_relative_excess": 0.0,
                "min_worst_drawdown": -0.30,
                "min_stress_compounded_relative_excess": 0.0,
                "max_strongest_positive_window_share": 0.50,
                "min_mean_rank_ic_improvement": 0.005,
                "require_factor_baseline_dominance": True,
            },
        },
    }
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _rows(
    *,
    baseline_rank_ic: float = 0.030,
    challenger_rank_ic: float = 0.040,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate_id, excess, drawdown, rank_ic in (
        ("baseline_7factor", 0.04, -0.27, baseline_rank_ic),
        ("risk_controlled_9factor", 0.10, -0.20, challenger_rank_ic),
    ):
        for window in SELECTION_WINDOWS:
            for cost_bps, multiplier in ((20, 1.0), (60, 0.5)):
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "window": window,
                        "cost_bps": cost_bps,
                        "relative_excess": excess * multiplier,
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


def test_reporting_only_window_cannot_change_winner_or_gates(tmp_path: Path) -> None:
    contract = load_experiment_contract(_write_spec(tmp_path))
    base_receipt = evaluate_experiment(contract, _rows(), candidate_metadata=_metadata())

    poisoned_rows = deepcopy(_rows())
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

    assert base_receipt["leader"] == "risk_controlled_9factor"
    assert base_receipt["winner"] == "risk_controlled_9factor"
    assert base_receipt["supported"] is True
    assert poisoned_receipt["leader"] == base_receipt["leader"]
    assert poisoned_receipt["winner"] == base_receipt["winner"]
    assert poisoned_receipt["decision"] == base_receipt["decision"]
    assert poisoned_receipt["candidates"] == base_receipt["candidates"]
    assert poisoned_receipt["reporting_windows_seen_but_not_used"] == ["2026H1"]


def test_unsupported_challenger_is_leader_but_not_winner(tmp_path: Path) -> None:
    contract = load_experiment_contract(_write_spec(tmp_path))
    receipt = evaluate_experiment(
        contract,
        _rows(baseline_rank_ic=0.030, challenger_rank_ic=0.031),
        candidate_metadata=_metadata(),
    )

    assert receipt["leader"] == "risk_controlled_9factor"
    assert receipt["winner"] is None
    assert receipt["decision"] == "not_supported"
    assert receipt["supported"] is False


def test_missing_selection_window_fails_closed(tmp_path: Path) -> None:
    contract = load_experiment_contract(_write_spec(tmp_path))
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
    with pytest.raises(ValueError, match="selection/reporting windows overlap"):
        load_experiment_contract(_write_spec(tmp_path, reporting=["2025H2"]))


class TestProviderIdentityValidation:
    """Non-empty, 64-char hex SHA256 + valid ISO date required."""

    VALID_SHA256 = "a" * 64

    def _write(self, tmp_path: Path, provider_id: str = VALID_SHA256, cutoff: str = "2026-06-24") -> Path:
        spec = deepcopy({
            "experiment_id": "test",
            "runner": "cross_sectional_xgb_ranker_v1",
            "research_only": True,
            "trade_ready": False,
            "windows": {"candidate_selection": ["2024H1"], "consumed_reporting_only": [],
                         "consumed_reporting_may_enter_selection": False},
            "evaluation": {"baseline_candidate_id": "bl", "stress_cost_bps": 60,
                           "decision": "test", "ranking": ["compounded_relative_excess"],
                           "thresholds": {"min_window_relative_excess": 0.0, "min_worst_drawdown": -0.30,
                                          "min_stress_compounded_relative_excess": 0.0,
                                          "max_strongest_positive_window_share": 0.55,
                                          "min_mean_rank_ic_improvement": 0.0,
                                          "require_factor_baseline_dominance": False}},
            "execution": {"base_cost_bps": 20, "cost_stress_bps": [20, 60]},
            "snapshot": {"provider_identity_sha256": provider_id, "cutoff": cutoff},
        })
        p = tmp_path / "spec.yaml"
        p.write_text(yaml.dump(spec))
        return p

    def test_valid_sha256_loads(self, tmp_path):
        c = load_experiment_contract(self._write(tmp_path))
        assert len(c.provider_identity_sha256) == 64

    def test_missing_identity_raises(self, tmp_path):
        p = self._write(tmp_path, provider_id="")
        with pytest.raises(ValueError, match="provider_identity_sha256 is required"):
            load_experiment_contract(p)

    def test_wrong_length_raises(self, tmp_path):
        p = self._write(tmp_path, provider_id="abc123")
        with pytest.raises(ValueError, match="64-character hex"):
            load_experiment_contract(p)

    def test_non_hex_raises(self, tmp_path):
        p = self._write(tmp_path, provider_id="g" * 64)
        with pytest.raises(ValueError, match="64-character hex"):
            load_experiment_contract(p)

    def test_invalid_date_raises(self, tmp_path):
        p = self._write(tmp_path, cutoff="not-a-date")
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            load_experiment_contract(p)

    def test_missing_cutoff_raises(self, tmp_path):
        p = self._write(tmp_path, cutoff="")
        with pytest.raises(ValueError, match="cutoff is required"):
            load_experiment_contract(p)
