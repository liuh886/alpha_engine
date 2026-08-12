from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.run_us_x1_3_current_target import resolve_formal_bundle
from src.research.us_x1_3_current_target import (
    MODEL_ID,
    _calibration,
    _factor_columns,
    _factor_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_formal_us_x1_3_bundle_resolves_without_legacy_alias() -> None:
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
    config = yaml.safe_load((ROOT / "configs/models/us_x1_3.yaml").read_text(encoding="utf-8"))
    calibration = _calibration(config)
    assert config["lineage"]["selected_candidate"] == "mvv_plus_pressure"
    assert calibration.num_boost_round == 200
    assert calibration.learning_rate == 0.05
    assert calibration.subsample == 0.8
    assert calibration.colsample_bytree == 0.8
    assert config["strategy"]["top_n"] == 15
    assert config["strategy"]["maximum_names_per_sector"] == 4
    assert config["strategy"]["cost_bps"] == 20

    assert "expressions" not in config["features"]
    factor_ids, expressions = _factor_contract(ROOT, config)
    columns = [f"feature_{index}" for index in range(len(expressions))]
    factor_columns = _factor_columns(factor_ids=factor_ids, columns=columns)
    assert factor_ids == [
        "ohlcv.momentum.ret_3d",
        "ohlcv.momentum.ret_5d",
        "ohlcv.momentum.ret_10d",
        "ohlcv.momentum.ret_20d",
        "ohlcv.volatility.std_ret_10d",
        "ohlcv.volatility.std_ret_20d",
        "ohlcv.volume.momentum_10d",
        "ohlcv.liquidity.volume_vs_ma_5d",
        "ohlcv.liquidity.volume_vs_ma_10d",
        "ohlcv.liquidity.volume_vs_ma_20d",
        "ohlcv.pressure.ret1_x_volume_shock_5d",
        "ohlcv.pressure.ret5_x_volume_shock_10d",
        "ohlcv.pressure.high_low_ratio",
    ]
    assert len(expressions) == 13
    assert list(factor_columns) == factor_ids
    assert set(factor_columns.values()) == set(columns)


def test_production_ranker_workflow_no_longer_targets_us_x1_1() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/run_us_x1_3_current_target.py due" in workflow
    assert "scripts/run_us_x1_3_current_target.py build" in workflow
    assert "strategy_signal_ledgers/us_x1_3" in workflow
    assert "strategy_signal_ledgers/us_x1_2" not in workflow
