from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.run_us_x1_2_current_target import resolve_formal_bundle
from src.research.us_x1_2_current_target import (
    MODEL_ID,
    _calibration,
    _factor_columns,
)

ROOT = Path(__file__).resolve().parents[1]


def test_formal_us_x1_2_bundle_resolves_without_legacy_alias() -> None:
    manifest_path, portfolio_path = resolve_formal_bundle(
        ROOT / "data/research/formal_model_runs"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_version_id"] == MODEL_ID
    assert manifest["publication_channel"] == "formal"
    assert manifest["publication_status"] == "accepted_formal_baseline"
    assert portfolio_path.name == "portfolio.json"
    assert portfolio_path.is_file()


def test_current_target_uses_exact_formal_x1_2_model_contract() -> None:
    config = yaml.safe_load((ROOT / "configs/models/us_x1_2.yaml").read_text(encoding="utf-8"))
    calibration = _calibration(config)
    assert config["lineage"]["selected_candidate"] == "r11_sampled"
    assert calibration.num_boost_round == 200
    assert calibration.learning_rate == 0.05
    assert calibration.subsample == 0.8
    assert calibration.colsample_bytree == 0.8
    assert config["strategy"]["top_n"] == 15
    assert config["strategy"]["maximum_names_per_sector"] == 4
    assert config["strategy"]["cost_bps"] == 20

    expressions = list(config["features"]["expressions"])
    columns = [f"feature_{index}" for index in range(len(expressions))]
    factor_columns = _factor_columns(ROOT, expressions=expressions, columns=columns)
    assert len(factor_columns) == 7
    assert set(factor_columns.values()) == set(columns)


def test_production_ranker_workflow_no_longer_targets_us_x1_1() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/run_us_x1_2_current_target.py due" in workflow
    assert "scripts/run_us_x1_2_current_target.py build" in workflow
    assert "strategy_signal_ledgers/us_x1_2" in workflow
    assert "strategy_signal_ledgers/us_x1_1" not in workflow
