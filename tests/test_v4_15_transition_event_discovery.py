from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_15_transition_event_discovery import (
    TransitionRule,
    build_transition_flags,
    enumerate_transition_rules,
    events_for_transition_rule,
    transition_rule_mask,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_transition_events_v4_15_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _features(periods: int = 80) -> pd.DataFrame:
    index = pd.date_range("2020-01-02", periods=periods, freq="B")
    frame = pd.DataFrame(index=index)
    frame["vol_max_percentile_252"] = 0.50
    frame["vol_max_return_5d"] = 0.00
    frame["vol_min_retreat_20d"] = 0.05
    frame["vxn_vix_ratio_z63"] = 0.00
    frame["qqq_rsi20"] = 40.0
    frame["qqq_bollinger_pct_b_20_2"] = 0.40
    frame["qqq_bollinger_bandwidth_z63"] = -0.20
    frame["qqq_distance_ma20"] = -0.01
    frame["qqq_voo_rs_distance_ma20"] = -0.01
    frame["qqq_voo_bollinger_gap"] = -0.10
    frame["qqq_minus_voo_return_20d"] = -0.01
    frame["voo_distance_ma200"] = 0.10
    for horizon in (5, 10, 20):
        frame[f"forward_qqq_{horizon}d"] = 0.02
        frame[f"forward_tqqq_{horizon}d"] = 0.04
        frame[f"forward_voo_{horizon}d"] = 0.015
        frame[f"forward_bil_{horizon}d"] = 0.001
    return frame


def test_crossing_impulse_fires_once_not_as_persistent_state() -> None:
    features = _features()
    features.loc[features.index[10:20], "qqq_rsi20"] = 60.0
    flags = build_transition_flags(features, _contract())
    active = flags.index[flags["rsi20_cross_up_55"]]
    assert active.tolist() == [features.index[10]]


def test_retreat_confirmation_requires_prior_stress_and_fires_once() -> None:
    features = _features()
    features.loc[features.index[5:8], "vol_max_percentile_252"] = 0.90
    features.loc[features.index[9:15], "vol_min_retreat_20d"] = 0.20
    features.loc[features.index[9:15], "vol_max_return_5d"] = -0.05
    flags = build_transition_flags(features, _contract())
    active = flags.index[flags["dual_vol_retreat_confirmed"]]
    assert active.tolist() == [features.index[9]]


def test_three_session_confirmation_uses_latest_impulse_only() -> None:
    features = _features()
    flags = pd.DataFrame(False, index=features.index, columns=[])
    flags["dual_vol_retreat_confirmed"] = False
    flags["rsi20_cross_up_55"] = False
    flags["qqq_voo_rs_cross_up"] = False
    flags.loc[features.index[10], "dual_vol_retreat_confirmed"] = True
    flags.loc[features.index[11], "rsi20_cross_up_55"] = True
    flags.loc[features.index[12], "qqq_voo_rs_cross_up"] = True
    rule = TransitionRule(
        "tech_acceleration",
        "dual_vol_retreat_confirmed",
        "rsi20_cross_up_55",
        "qqq_voo_rs_cross_up",
    )
    mask = transition_rule_mask(features, flags, rule, _contract())
    assert mask.index[mask].tolist() == [features.index[12]]


def test_extension_cap_rejects_late_acceleration() -> None:
    features = _features()
    features.loc[features.index[12], "qqq_distance_ma20"] = 0.06
    flags = pd.DataFrame(False, index=features.index, columns=[])
    flags["dual_vol_retreat_confirmed"] = False
    flags["rsi20_cross_up_55"] = False
    flags.loc[features.index[11], "dual_vol_retreat_confirmed"] = True
    flags.loc[features.index[12], "rsi20_cross_up_55"] = True
    rule = TransitionRule(
        "tech_acceleration",
        "dual_vol_retreat_confirmed",
        "rsi20_cross_up_55",
        None,
    )
    mask = transition_rule_mask(features, flags, rule, _contract())
    assert not bool(mask.any())


def test_family_horizons_execute_next_open() -> None:
    features = _features()
    flags = pd.DataFrame(False, index=features.index, columns=[])
    for column in ("dual_vol_retreat_confirmed", "rsi20_cross_up_55"):
        flags[column] = False
    flags.loc[features.index[20], "dual_vol_retreat_confirmed"] = True
    flags.loc[features.index[21], "rsi20_cross_up_55"] = True
    rule = TransitionRule(
        "tech_acceleration",
        "dual_vol_retreat_confirmed",
        "rsi20_cross_up_55",
        None,
    )
    events = events_for_transition_rule(
        features,
        flags,
        rule,
        _contract(),
        fold="unit",
        sample="outer",
    )
    assert len(events) == 1
    event = events.iloc[0]
    assert event["execution_date"] == features.index[22]
    assert event["event_end_date"] == features.index[26]
    assert event["holding_sessions"] == 5


def test_transition_rule_catalog_remains_bounded() -> None:
    rules = enumerate_transition_rules(_contract())
    assert len(rules) == 126
    assert len({rule.rule_id for rule in rules}) == len(rules)
    assert all(2 <= rule.condition_count <= 3 for rule in rules)
    rotation = [rule for rule in rules if rule.event_family == "broad_rotation"]
    assert all(rule.cross_transition is not None for rule in rotation)
