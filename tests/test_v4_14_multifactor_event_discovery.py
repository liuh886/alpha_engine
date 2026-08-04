from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_14_multifactor_event_discovery import (
    _benjamini_hochberg,
    _nonoverlap_locations,
    build_multifactor_feature_frame,
    enumerate_rules,
    events_for_rule,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_multifactor_events_v4_14_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _bars(symbol: str, index: pd.DatetimeIndex, scale: float) -> pd.DataFrame:
    trend = np.linspace(100.0 * scale, 170.0 * scale, len(index))
    cycle = 4.0 * scale * np.sin(np.arange(len(index)) / 13.0)
    close = trend + cycle
    open_price = close * (1.0 + 0.001 * np.cos(np.arange(len(index)) / 7.0))
    if symbol in {"^VIX", "^VXN"}:
        base = 20.0 if symbol == "^VIX" else 25.0
        close = base + 4.0 * np.sin(np.arange(len(index)) / 17.0)
        open_price = close * 0.999
    return pd.DataFrame({"date": index, "open": open_price, "close": close})


def _synthetic_inputs() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    index = pd.date_range("2010-01-04", periods=620, freq="B")
    bars = {
        "QQQ": _bars("QQQ", index, 1.0),
        "TQQQ": _bars("TQQQ", index, 1.8),
        "VOO": _bars("VOO", index, 0.9),
        "BIL": _bars("BIL", index, 0.8),
        "^VIX": _bars("^VIX", index, 1.0),
        "^VXN": _bars("^VXN", index, 1.0),
    }
    baseline = pd.DataFrame(index=index)
    baseline["position_state"] = np.where(np.arange(len(index)) % 60 < 20, 2, 1)
    return bars, baseline


def test_rule_catalog_is_bounded_and_interpretable() -> None:
    rules = enumerate_rules(_contract())
    assert len(rules) > 100
    assert len({rule.rule_id for rule in rules}) == len(rules)
    assert all(2 <= rule.condition_count <= 3 for rule in rules)
    for rule in rules:
        families = [condition.family for condition in rule.conditions]
        assert families.count("volatility") == 1
        assert families.count("price") == 1
        assert families.count("cross_index") <= 1


def test_feature_builder_uses_close_time_features_and_next_open_outcomes() -> None:
    bars, baseline = _synthetic_inputs()
    frame = build_multifactor_feature_frame(bars, baseline)
    assert "qqq_rsi20" in frame
    assert "vxn_vix_ratio_z63" in frame
    assert "qqq_voo_rs_distance_ma20" in frame
    assert "target_tech_acceleration" in frame
    first_valid = frame["forward_qqq_5d"].first_valid_index()
    assert first_valid is not None
    location = frame.index.get_loc(first_valid)
    expected = float(
        np.prod(
            1.0
            + frame["qqq_next_open_return"].iloc[
                location + 1 : location + 6
            ].to_numpy()
        )
        - 1.0
    )
    assert np.isclose(frame.loc[first_valid, "forward_qqq_5d"], expected)
    assert frame.loc[first_valid, "v4_2_execution_state"] == baseline[
        "position_state"
    ].shift(-1).loc[first_valid]


def test_nonoverlap_builder_respects_holding_and_cooldown() -> None:
    mask = pd.Series(
        [False, True, True, True, False, True, True, True, True, True, True, True]
    )
    locations = _nonoverlap_locations(
        mask, holding_sessions=3, cooldown_sessions=2
    )
    assert locations == [1, 7]


def test_events_execute_at_next_open_and_end_after_frozen_horizon() -> None:
    bars, baseline = _synthetic_inputs()
    frame = build_multifactor_feature_frame(bars, baseline)
    contract = _contract()
    rule = next(
        rule
        for rule in enumerate_rules(contract)
        if rule.event_family == "tech_acceleration"
        and rule.condition_count == 2
    )
    events = events_for_rule(
        frame,
        rule,
        contract,
        fold="unit",
        sample="outer",
    )
    if not events.empty:
        for row in events.itertuples(index=False):
            signal_location = frame.index.get_loc(row.signal_close_date)
            assert row.execution_date == frame.index[signal_location + 1]
            assert row.event_end_date == frame.index[
                signal_location + contract["rule_grammar"]["holding_sessions"]
            ]


def test_benjamini_hochberg_is_monotone_in_sorted_order() -> None:
    pvalues = pd.Series([0.04, 0.001, 0.02, 0.50])
    qvalues = _benjamini_hochberg(pvalues)
    ordered = pd.DataFrame({"p": pvalues, "q": qvalues}).sort_values("p")
    assert ordered["q"].is_monotonic_increasing
    assert (qvalues >= pvalues).all()
    assert qvalues.between(0.0, 1.0).all()
