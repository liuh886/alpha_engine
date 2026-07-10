"""Tests for the fixed-10D contract-only research paradigm."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from src.research.paradigm import (
    ARTIFACT_PROFILE,
    GATE_PROFILE,
    REQUIRED_METRICS,
    ResearchParadigmSpec,
    build_factor_baselines_from_spec,
    build_ranker_candidates_from_spec,
    dry_run_paradigm,
    load_research_paradigm_spec,
    run_research_paradigm,
    validate_research_paradigm_spec,
)

MINIMAL_YAML = """\
# Canonical CN fixed-10D research preparation contract.
schema_version: "1.0"
experiment_id: "test_contract"
market: "cn"
benchmark: "000300"

universe:
  source: "configs/watchlist.yaml"
  market_key: "cn"
  min_symbols: 50
  alignment_mode: "auto"

factor_library:
  source: "configs/factor_libraries/cn_ohlcv.yaml"
  groups:
    - "cn_balanced_ohlcv"

candidate_grid:
  ranker:
    calibrations:
      - n_gain_bins: 3
        num_boost_round: 100
        num_leaves: 15
        min_data_in_leaf: 10
        learning_rate: 0.05
  factor_baselines:
    - "factor:cn_momentum_10d"

strategy:
  horizon_days: 10
  holding_days: 10
  rebalance_days: 10
  top_n: 15
  bottom_n: 15
  return_expression: "Ref($close, -10) / $close - 1"
  return_provenance: "raw_forward_return"
  research_only: true

walk_forward:
  requested_train_start: "2021-01-01"
  test_end: "2026-06-18"
  first_test_year: 2024
  last_test_year: 2026
  min_windows: 3
  train_embargo_sessions: 10

evaluation:
  benchmark_mode: "reference_only"
  metrics:
    - "mean_icir"
    - "mean_rank_ic"
    - "mean_spread"
    - "worst_drawdown"
    - "ready_ratio"
    - "positive_icir_ratio"
    - "positive_spread_ratio"
  gate_profile: "ten_day_model_gates_v1"

outputs:
  artifact_profile: "research_run_v1"
"""


def _write_spec(tmp_path: Path, data: dict | None = None) -> Path:
    payload = data if data is not None else yaml.safe_load(MINIMAL_YAML)
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _spec_dict() -> dict:
    return yaml.safe_load(MINIMAL_YAML)


def test_valid_spec_loads_and_builds_declared_candidates(tmp_path: Path) -> None:
    spec = load_research_paradigm_spec(_write_spec(tmp_path))
    assert spec.experiment_id == "test_contract"
    assert len(build_ranker_candidates_from_spec(spec)) == 1
    assert set(build_factor_baselines_from_spec(spec)) == {
        "factor:cn_momentum_10d"
    }


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.update(experiment_id="../escape"), "safe slug"),
        (
            lambda data: data["universe"].update(market_key="us"),
            "market_key must match",
        ),
        (
            lambda data: data["strategy"].update(top_n=0),
            "top_n must be positive",
        ),
        (
            lambda data: data["walk_forward"].update(
                requested_train_start="2027-01-01"
            ),
            "must be before test_end",
        ),
        (
            lambda data: data["evaluation"].update(benchmark_mode="active"),
            "benchmark_mode",
        ),
        (
            lambda data: data["evaluation"].update(metrics=["mean_icir"]),
            "canonical ordered metric set",
        ),
        (
            lambda data: data["evaluation"].update(gate_profile="custom"),
            "gate_profile",
        ),
        (
            lambda data: data["evaluation"].update(gates={"mean_icir": 0.1}),
            "must not duplicate thresholds",
        ),
        (
            lambda data: data["outputs"].update(write_frontend_payload=True),
            "may only contain artifact_profile",
        ),
    ],
)
def test_invalid_contracts_fail_closed(
    tmp_path: Path, mutator, message: str
) -> None:
    data = _spec_dict()
    mutator(data)
    spec = ResearchParadigmSpec.from_dict(
        data, spec_path=str(tmp_path / "spec.yaml")
    )
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        validate_research_paradigm_spec(spec)


def test_contract_uses_profiles_not_duplicate_thresholds() -> None:
    data = _spec_dict()
    assert data["evaluation"]["gate_profile"] == GATE_PROFILE
    assert "gates" not in data["evaluation"]
    assert tuple(data["evaluation"]["metrics"]) == REQUIRED_METRICS
    assert data["outputs"] == {"artifact_profile": ARTIFACT_PROFILE}


def test_dry_run_writes_only_preparation_artifacts(tmp_path: Path) -> None:
    spec = load_research_paradigm_spec(_write_spec(tmp_path))
    qlib_before = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    result = dry_run_paradigm(spec, output_dir=tmp_path / "out")
    qlib_after = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    assert qlib_after == qlib_before
    assert result["status"] == "prepared"
    assert result["contract_only"] is True

    run_dir = Path(result["run_dir"])
    expected = {
        "experiment_spec.json",
        "run_status.json",
        "factor_manifest.json",
        "candidate_manifest.json",
        "signals_latest.json",
        "top_bottom_signals.csv",
        "frontend_payload.json",
    }
    assert {path.name for path in run_dir.iterdir()} == expected
    assert not (run_dir / "data_readiness.json").exists()
    assert not (run_dir / "walk_forward_stability.json").exists()
    assert not (run_dir / "model_decision_pack.json").exists()

    frontend = json.loads((run_dir / "frontend_payload.json").read_text())
    assert frontend["trade_ready"] is False
    assert frontend["research_only"] is True
    assert frontend["metadata"]["contract_only"] is True
    assert set(frontend["artifact_paths"]) == {
        "experiment_spec",
        "run_status",
        "factor_manifest",
        "candidate_manifest",
        "signals_latest",
        "top_bottom_signals_csv",
        "frontend_payload",
    }


def test_run_api_rejects_real_execution(tmp_path: Path) -> None:
    spec = load_research_paradigm_spec(_write_spec(tmp_path))
    with pytest.raises(ValueError, match="Only dry_run=True"):
        run_research_paradigm(spec, dry_run=False)


@pytest.mark.parametrize(
    "path",
    [
        "configs/research_paradigms/cn_10d_csi300_baseline.yaml",
        "configs/research_paradigms/us_10d_qqq_baseline.yaml",
    ],
)
def test_real_specs_validate_and_prepare(path: str, tmp_path: Path) -> None:
    spec = load_research_paradigm_spec(path)
    result = run_research_paradigm(
        spec, dry_run=True, output_dir=tmp_path
    )
    assert result["status"] == "prepared"
    assert result["n_candidates"] > 0
    assert result["contract_only"] is True
