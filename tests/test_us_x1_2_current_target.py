from __future__ import annotations

from pathlib import Path

import yaml

from src.research.us_x1_2_current_target import (
    _calibration,
    _factor_columns,
    _factor_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_us_x1_2_historical_model_identity_is_preserved() -> None:
    config = yaml.safe_load((ROOT / "configs/models/us_x1_2.yaml").read_text(encoding="utf-8"))
    assert config["model_id"] == "us_x1_2"
    assert config["display_name"] == "US x1.2"
    assert config["lineage"]["selected_candidate"] == "r11_sampled"
    assert config["research_only"] is True
    assert config["trade_ready"] is False


def test_historical_x1_2_current_target_contract_remains_reproducible() -> None:
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

    assert "expressions" not in config["features"]
    factor_ids, expressions = _factor_contract(ROOT, config)
    columns = [f"feature_{index}" for index in range(len(expressions))]
    factor_columns = _factor_columns(factor_ids=factor_ids, columns=columns)
    assert factor_ids == [
        "ohlcv.momentum.ret_10d",
        "ohlcv.momentum.ret_20d",
        "ohlcv.momentum.ret_5d",
        "ohlcv.volatility.std_ret_10d",
        "ohlcv.volatility.std_ret_20d",
        "ohlcv.volume.momentum_10d",
        "ohlcv.liquidity.volume_vs_ma_20d",
    ]
    assert expressions == [
        "$close/Ref($close,10)-1",
        "$close/Ref($close,20)-1",
        "$close/Ref($close,5)-1",
        "Std($close/Ref($close,1)-1,10)",
        "Std($close/Ref($close,1)-1,20)",
        "$volume/Ref($volume,10)-1",
        "$volume/Mean($volume,20)-1",
    ]
    assert list(factor_columns) == factor_ids
    assert set(factor_columns.values()) == set(columns)


def test_production_ranker_workflow_routes_only_to_active_us_x1_3() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/run_us_x1_3_current_target.py due" in workflow
    assert "scripts/run_us_x1_3_current_target.py build" in workflow
    assert "strategy_signal_ledgers/us_x1_3" in workflow
    assert "scripts/run_us_x1_2_current_target.py" not in workflow
    assert "strategy_signal_ledgers/us_x1_2" not in workflow
    assert "strategy_signal_ledgers/us_x1_1" not in workflow
