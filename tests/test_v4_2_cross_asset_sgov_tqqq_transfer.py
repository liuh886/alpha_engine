from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_2_cross_asset_sgov_tqqq_transfer import (
    _target_weight_schedules,
    assign_macro_clusters,
    build_nonoverlapping_events,
    fit_cluster_transfer_model,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_qqq_tqqq_cross_asset_sgov_tqqq_transfer_v4_12_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_contract_excludes_target_symbols_from_donor_pairs() -> None:
    contract = _contract()
    excluded = set(contract["boundaries"]["target_symbols_excluded_from_training"])
    donors = set(contract["data"]["donor_pairs"])
    leveraged = set(contract["data"]["donor_pairs"].values())
    assert not donors.intersection(excluded)
    assert not leveraged.intersection(excluded)
    assert contract["data"]["target_pair"] == {
        "underlying": "QQQ",
        "leveraged": "TQQQ",
    }


def test_macro_clusters_use_complete_date_windows() -> None:
    events = pd.DataFrame(
        {
            "signal_close_date": pd.to_datetime(
                ["2020-03-10", "2020-03-25", "2020-04-15", "2020-08-01"]
            ),
            "underlying": ["SPY", "IWM", "XLK", "DIA"],
            "asset_event_id": ["SPY_001", "IWM_001", "XLK_001", "DIA_001"],
        }
    )
    clustered = assign_macro_clusters(events, 30)
    assert clustered["macro_cluster_id"].tolist() == [
        "macro_001",
        "macro_001",
        "macro_002",
        "macro_003",
    ]


def _synthetic_donor_events() -> pd.DataFrame:
    contract = _contract()
    assets = list(contract["data"]["donor_pairs"])
    rows: list[dict] = []
    rng = np.random.default_rng(12)
    for cluster in range(10):
        cluster_sign = 1.0 if cluster % 2 == 0 else -1.0
        for asset_number, asset in enumerate(assets):
            latent = cluster_sign + 0.15 * asset_number + rng.normal(scale=0.05)
            row = {
                "asset_event_id": f"{asset}_{cluster:03d}",
                "underlying": asset,
                "leveraged": contract["data"]["donor_pairs"][asset],
                "macro_cluster_id": f"macro_{cluster:03d}",
                "signal_close_date": pd.Timestamp("2011-01-03")
                + pd.Timedelta(days=cluster * 300 + asset_number),
                "positive_event_excess": int(latent > 0.0),
                "event_excess_log_return": 0.04 * latent,
            }
            for number, feature in enumerate(contract["features"], start=1):
                row[feature] = latent * (1.0 + 0.02 * number) + rng.normal(
                    scale=0.03
                )
            rows.append(row)
    return pd.DataFrame(rows)


def test_cluster_oof_never_trains_on_validation_cluster() -> None:
    events = _synthetic_donor_events()
    model = fit_cluster_transfer_model(events, _contract())
    assert len(model.oof_predictions) == len(events)
    assert set(model.aggregate_metrics["training_assets"]) == set(
        _contract()["data"]["donor_pairs"]
    )
    assert "QQQ" not in model.aggregate_metrics["training_assets"]
    assert model.oof_predictions["training_cluster_count"].eq(9).all()
    assert model.aggregate_metrics["roc_auc"] > 0.90
    assert model.aggregate_metrics["spearman_ic"] > 0.80


def test_nonoverlapping_builder_admits_one_event_per_cycle() -> None:
    contract = _contract()
    index = pd.date_range("2020-01-02", periods=140, freq="B")
    frame = pd.DataFrame(index=index)
    for feature in contract["features"]:
        frame[feature] = 0.1
    frame["underlying_drawdown_63d"] = -0.02
    frame["shock"] = False
    frame["entry_ready"] = False
    frame["below_ma20_exit"] = False
    frame["vix_stress"] = False
    frame["leveraged_next_open_return"] = 0.003
    frame["cash_next_open_return"] = 0.0001

    frame.iloc[10:16, frame.columns.get_loc("underlying_drawdown_63d")] = -0.12
    frame.iloc[10, frame.columns.get_loc("shock")] = True
    frame.iloc[15, frame.columns.get_loc("entry_ready")] = True
    frame.iloc[20, frame.columns.get_loc("below_ma20_exit")] = True
    frame.iloc[30, frame.columns.get_loc("underlying_drawdown_63d")] = -0.01

    frame.iloc[45:51, frame.columns.get_loc("underlying_drawdown_63d")] = -0.13
    frame.iloc[45, frame.columns.get_loc("shock")] = True
    frame.iloc[50, frame.columns.get_loc("entry_ready")] = True
    frame.iloc[55, frame.columns.get_loc("vix_stress")] = True

    events = build_nonoverlapping_events(
        frame,
        underlying="SPY",
        leveraged="UPRO",
        cash="BIL",
        contract=contract,
    )
    assert len(events) == 2
    assert events["asset_event_id"].tolist() == ["SPY_001", "SPY_002"]
    assert events.iloc[0]["event_end_date"] < events.iloc[1]["execution_date"]
    assert events["exit_reason"].tolist() == [
        "two_closes_below_ma20",
        "vix_stress",
    ]


def test_event_override_is_frozen_on_execution_dates() -> None:
    contract = _contract()
    index = pd.date_range("2024-01-02", periods=8, freq="B")
    frame = pd.DataFrame(index=index)
    frame["structural_bull"] = [True, True, False, False, True, True, True, False]
    events = pd.DataFrame(
        {
            "execution_date": [index[3]],
            "event_end_date": [index[5]],
            "probability_bucket": ["medium"],
        }
    )
    schedules = _target_weight_schedules(frame, events, contract)
    structural = schedules["structural_only"]
    joint = schedules["joint_structural_event"]
    assert structural.iloc[0] == 0.0
    assert structural.iloc[1] == 0.75
    assert np.allclose(joint.loc[index[3] : index[5]], 0.5)
    assert joint.iloc[6] == structural.iloc[6]
