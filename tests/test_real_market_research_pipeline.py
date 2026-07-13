from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.research.real_market_research_pipeline import run_real_market_research_pipeline


def _write_spec(tmp_path: Path) -> Path:
    universe = tmp_path / "universe.yaml"
    universe.write_text(
        yaml.safe_dump(
            {
                "metadata": {
                    "universe_id": "test_us_v1",
                    "membership_mode": "static_curated",
                    "membership_as_of": "2026-07-11",
                    "asset_type": "equity",
                    "survivorship_bias": True,
                },
                "us": [f"S{i:02d}" for i in range(20)],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    factors = tmp_path / "factors.yaml"
    factors.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "groups": {
                    "signals": {
                        "description": "test",
                        "factors": [
                            {
                                "id": "test:momentum",
                                "expression": "$close/Ref($close,10)-1",
                                "family": "momentum",
                            }
                        ],
                    },
                    "factor_baselines": {
                        "description": "test",
                        "factors": [
                            {
                                "id": "factor:test_momentum",
                                "expression": "$close/Ref($close,10)-1",
                                "family": "baseline",
                            }
                        ],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.1",
                "experiment_id": "test_real_market_pipeline",
                "market": "us",
                "benchmark": "QQQ",
                "universe": {
                    "source": str(universe),
                    "market_key": "us",
                    "universe_id": "test_us_v1",
                    "membership_mode": "static_curated",
                    "membership_as_of": "2026-07-11",
                    "asset_type": "equity",
                    "survivorship_bias": True,
                    "min_symbols": 10,
                    "alignment_mode": "strict",
                },
                "factor_library": {"source": str(factors), "groups": ["signals"]},
                "candidate_grid": {
                    "ranker": {
                        "calibrations": [
                            {
                                "n_gain_bins": 5,
                                "num_boost_round": 10,
                                "num_leaves": 7,
                                "min_data_in_leaf": 2,
                                "learning_rate": 0.05,
                            }
                        ]
                    },
                    "factor_baselines": ["factor:test_momentum"],
                },
                "strategy": {
                    "horizon_days": 10,
                    "holding_days": 10,
                    "rebalance_days": 10,
                    "top_n": 5,
                    "bottom_n": 5,
                    "return_expression": "Ref($close, -10) / $close - 1",
                    "return_provenance": "raw_forward_return",
                    "research_only": True,
                },
                "walk_forward": {
                    "requested_train_start": "2021-01-01",
                    "test_end": "2026-06-18",
                    "first_test_year": 2024,
                    "last_test_year": 2026,
                    "min_windows": 3,
                    "partial_window_policy": "complete_windows_only",
                    "train_embargo_sessions": 10,
                },
                "evaluation": {
                    "benchmark_mode": "reference_only",
                    "metrics": [
                        "mean_icir",
                        "mean_rank_ic",
                        "mean_spread",
                        "worst_drawdown",
                        "ready_ratio",
                        "positive_icir_ratio",
                        "positive_spread_ratio",
                    ],
                    "gate_profile": "ten_day_model_gates_v1",
                },
                "outputs": {"artifact_profile": "research_run_v1"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return spec


def _acceptance_runner(accepted: bool):
    def run(spec_path: Path, **kwargs: Any) -> dict[str, Any]:
        report = {
            "experiment_id": "test_real_market_pipeline",
            "market": "us",
            "accepted": accepted,
            "summary": {"passed": 5 if accepted else 4, "failed": 0 if accepted else 1},
        }
        Path(kwargs["output_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    return run


def test_pipeline_stops_after_rejected_acceptance(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    diagnostics_called = False

    def diagnostics(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal diagnostics_called
        diagnostics_called = True
        return {}

    manifest = run_real_market_research_pipeline(
        spec,
        repository_root=tmp_path,
        output_dir=tmp_path / "run",
        acceptance_runner=_acceptance_runner(False),
        diagnostics_runner=diagnostics,
    )

    assert manifest["status"] == "blocked"
    assert manifest["stages"]["real_market_acceptance"] == "rejected"
    assert manifest["stages"]["factor_diagnostics"] == "not_run"
    assert diagnostics_called is False
    assert manifest["promotion_evaluated"] is False
    assert manifest["trade_ready"] is False


def test_pipeline_writes_bound_manifest_after_diagnostics(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    output_dir = tmp_path / "run"

    def diagnostics(spec_path: Path, acceptance_path: Path, **kwargs: Any) -> dict[str, Any]:
        assert acceptance_path.is_file()
        report = {
            "diagnostic_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
            "factor_count": 2,
            "factor_id_count": 4,
            "unique_expression_count": 2,
            "sampled_rebalance_dates": 60,
        }
        Path(kwargs["output_path"]).write_text(json.dumps(report), encoding="utf-8")
        return report

    manifest = run_real_market_research_pipeline(
        spec,
        repository_root=tmp_path,
        output_dir=output_dir,
        acceptance_runner=_acceptance_runner(True),
        diagnostics_runner=diagnostics,
    )

    assert manifest["status"] == "completed"
    assert manifest["schema_version"] == "1.1"
    assert manifest["factor_count"] == 2
    assert manifest["factor_id_count"] == 4
    assert manifest["unique_expression_count"] == 2
    assert manifest["sampled_rebalance_dates"] == 60
    assert len(manifest["acceptance_sha256"]) == 64
    assert len(manifest["factor_diagnostics_sha256"]) == 64
    assert manifest["promotion_eligible"] is False
    persisted = json.loads(
        (output_dir / "real_market_research_manifest.json").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "completed"


def test_pipeline_records_diagnostic_failure_before_raising(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    output_dir = tmp_path / "run"

    def diagnostics(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("factor diagnostics failed")

    with pytest.raises(RuntimeError, match="factor diagnostics failed"):
        run_real_market_research_pipeline(
            spec,
            repository_root=tmp_path,
            output_dir=output_dir,
            acceptance_runner=_acceptance_runner(True),
            diagnostics_runner=diagnostics,
        )

    manifest = json.loads(
        (output_dir / "real_market_research_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["failed_stage"] == "factor_diagnostics"
    assert manifest["stages"]["factor_diagnostics"] == "failed"
