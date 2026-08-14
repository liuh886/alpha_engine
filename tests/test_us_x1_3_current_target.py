from __future__ import annotations

from pathlib import Path

import yaml

from src.research.us_x1_3_current_target import (
    _calibration,
    _factor_columns,
    _factor_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_target_uses_exact_formal_x1_3_stage_b_contract() -> None:
    config = yaml.safe_load((ROOT / "configs/models/us_x1_3.yaml").read_text(encoding="utf-8"))
    calibration = _calibration(config)
    assert config["model_id"] == "us_x1_3"
    assert config["research_only"] is True
    assert config["trade_ready"] is False
    assert config["lineage"]["supersedes"] == "us_x1_2"
    assert config["lineage"]["selected_candidate"] == "mvv_plus_pressure"
    assert config["features"]["source_factor_groups"] == [
        "momentum_volatility_volume",
        "us_price_volume_pressure",
    ]
    assert config["features"]["factor_order_semantics"] == "ordered_group_union_first_occurrence_wins"
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
        "ohlcv.momentum.ret_5d",
        "ohlcv.momentum.ret_10d",
        "ohlcv.momentum.ret_20d",
        "ohlcv.volatility.std_ret_10d",
        "ohlcv.volatility.std_ret_20d",
        "ohlcv.volume.momentum_10d",
        "ohlcv.liquidity.volume_vs_ma_20d",
        "ohlcv.momentum.ret_3d",
        "ohlcv.liquidity.volume_vs_ma_5d",
        "ohlcv.liquidity.volume_vs_ma_10d",
        "ohlcv.pressure.ret1_x_volume_shock_5d",
        "ohlcv.pressure.ret5_x_volume_shock_10d",
        "ohlcv.pressure.high_low_ratio",
    ]
    assert len(expressions) == 13
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
    assert not (ROOT / "scripts/run_us_x1_2_current_target.py").exists()
    assert not (ROOT / "src/research/us_x1_2_current_target.py").exists()


def test_production_us_ranker_reuses_governed_history_and_refreshes_only_incrementally() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(
        encoding="utf-8"
    )
    us_step = workflow.split("- name: Build due US x1.3 provider and current target", 1)[1].split(
        "- name: Build due CN provider and current target", 1
    )[0]
    cn_step = workflow.split("- name: Build due CN provider and current target", 1)[1].split(
        "- name: Seal due canonical decisions", 1
    )[0]

    assert "--source-csv-dir data/csv_clean" in us_step
    assert "--full-refresh" not in us_step
    assert "--full-refresh" in cn_step
    assert "--market cn" not in cn_step
