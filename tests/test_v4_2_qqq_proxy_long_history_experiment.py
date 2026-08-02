from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_qqq_proxy_long_history_experiment import (
    _long_sample_support_gate,
    alias_qqqi_to_qqq,
    overlap_event_concordance,
)


def test_alias_qqqi_to_qqq_is_exact_and_does_not_mutate_source() -> None:
    index = pd.date_range("2020-05-26", periods=3, freq="B")
    qqq = pd.DataFrame({"open": [1.0, 2.0, 3.0], "close": [1.1, 2.1, 3.1]}, index=index)
    original_qqqi = pd.DataFrame(
        {"open": [10.0, 11.0], "close": [10.5, 11.5]},
        index=index[-2:],
    )
    bars = {"QQQ": qqq, "QQQI": original_qqqi}

    proxied = alias_qqqi_to_qqq(bars)

    assert proxied["QQQI"].equals(qqq)
    assert bars["QQQI"].equals(original_qqqi)
    proxied["QQQI"].iloc[0, 0] = 99.0
    assert bars["QQQ"].iloc[0, 0] == pytest.approx(1.0)


def test_alias_requires_qqq() -> None:
    with pytest.raises(ValueError, match="QQQ bars are required"):
        alias_qqqi_to_qqq({"QQQI": pd.DataFrame()})


def test_overlap_event_concordance_matches_direction() -> None:
    actual = pd.DataFrame(
        {
            "start_date": ["2024-08-16", "2024-11-07"],
            "end_date": ["2024-08-21", "2024-11-07"],
            "sessions": [4, 1],
            "event_relative_return": [0.013, 0.004],
        }
    )
    proxy = pd.DataFrame(
        {
            "start_date": ["2022-03-01", "2024-08-16", "2024-11-07"],
            "end_date": ["2022-03-02", "2024-08-21", "2024-11-07"],
            "sessions": [2, 4, 1],
            "event_relative_return": [-0.010, 0.020, -0.001],
        }
    )

    matched = overlap_event_concordance(actual, proxy)

    assert len(matched) == 2
    assert bool(matched.iloc[0]["direction_match"])
    assert not bool(matched.iloc[1]["direction_match"])


def test_support_gate_requires_event_expansion_and_overlap_consistency() -> None:
    actual_diagnostics = {"common_sample_start": "2024-01-30"}
    proxy_diagnostics = {
        "common_sample_start": "2020-05-27",
        "shadow_gate": {
            "metrics": {
                "full_sample_cagr_delta_vs_25_pp": 1.0,
                "early_segment_cagr_delta_vs_25_pp": 0.5,
                "late_segment_cagr_delta_vs_25_pp": 0.4,
                "marginal_event_positive_rate_vs_25": 0.75,
                "largest_marginal_event_benefit_share": 0.40,
            }
        },
    }
    actual_events = pd.DataFrame({"event_id": ["a", "b", "c"]})
    proxy_events = pd.DataFrame({"event_id": list("abcdefg")})
    concordance = pd.DataFrame(
        {
            "proxy_marginal_return": [0.01, 0.02, 0.03],
            "direction_match": [True, True, True],
        }
    )
    contract = {
        "validation": {
            "minimum_long_sample_precursor_events": 6,
            "minimum_additional_events_vs_actual_qqqi_sample": 3,
            "overlap_event_sign_concordance_min": 0.67,
            "require_all_actual_events_matched_in_overlap": True,
            "require_proxy_sample_start_before_actual_sample_start": True,
            "require_long_sample_50_vs_25_full_cagr_delta_nonnegative": True,
            "require_long_sample_50_vs_25_early_cagr_delta_nonnegative": True,
            "require_long_sample_50_vs_25_late_cagr_delta_nonnegative": True,
            "minimum_long_sample_marginal_event_positive_rate": 0.60,
            "maximum_long_sample_largest_event_share": 0.50,
        }
    }

    gate = _long_sample_support_gate(
        actual_diagnostics,
        proxy_diagnostics,
        actual_events,
        proxy_events,
        concordance,
        contract,
    )

    assert gate["structural_support_for_50_percent_hypothesis"]
    assert not gate["actionable_model_authorized"]
