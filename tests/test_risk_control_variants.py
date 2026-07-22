from __future__ import annotations

import pandas as pd

from src.research.risk_control_variants import (
    VARIANT_TOP3_BENCHMARK_TREND,
    VARIANT_TOP3_INVERSE_VOL20,
    VARIANT_TOP5_EQUAL,
    RiskVariantSpec,
    aggregate_variant_reports,
    build_variant_target_weights,
    evaluate_risk_control_variant,
)


def _scores() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    instruments = ["A", "B", "C", "D", "E", "F"]
    rows = []
    values = []
    for date in dates:
        for rank, instrument in enumerate(instruments):
            rows.append((date, instrument))
            values.append(float(10 - rank))
    index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
    return pd.DataFrame({"score": values}, index=index)


def _returns() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    instruments = ["A", "B", "C", "D", "E", "F"]
    values_by_instrument = {
        "A": 0.08,
        "B": 0.05,
        "C": 0.03,
        "D": 0.01,
        "E": -0.01,
        "F": -0.03,
    }
    rows = []
    values = []
    for date in dates:
        for instrument in instruments:
            rows.append((date, instrument))
            values.append(values_by_instrument[instrument])
    index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
    frame = pd.DataFrame({"return": values}, index=index)
    frame.attrs["provenance"] = "raw_forward_return"
    frame.attrs["horizon"] = 10
    return frame


def _benchmark() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    frame = pd.DataFrame({"return": [0.02, -0.01, 0.015]}, index=dates)
    frame.attrs["provenance"] = "raw_forward_return"
    frame.attrs["horizon"] = 10
    return frame


def _vol20() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    instruments = ["A", "B", "C", "D", "E", "F"]
    # A is high-vol, C is low-vol. Inverse-vol should weight C more than A.
    vol_by_instrument = {
        "A": 0.40,
        "B": 0.20,
        "C": 0.10,
        "D": 0.30,
        "E": 0.25,
        "F": 0.35,
    }
    rows = []
    values = []
    for date in dates:
        for instrument in instruments:
            rows.append((date, instrument))
            values.append(vol_by_instrument[instrument])
    index = pd.MultiIndex.from_tuples(rows, names=["datetime", "instrument"])
    return pd.DataFrame({"vol20": values}, index=index)


def _benchmark_trend() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"])
    return pd.DataFrame({"trend_return_20d": [0.05, -0.03, 0.02]}, index=dates)


def test_top5_equal_weight_builds_five_holdings_per_rebalance_date():
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP5_EQUAL,
        top_n=5,
        construction="equal_weight",
    )
    dates = tuple(pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"]))
    weights = build_variant_target_weights(
        _scores(),
        spec=spec,
        evaluation_dates=dates,
        rebalance_days=1,
    )

    counts = weights.groupby(level="datetime").size()
    totals = weights["target_weight"].groupby(level="datetime").sum()

    assert counts.tolist() == [5, 5, 5]
    assert totals.round(10).tolist() == [1.0, 1.0, 1.0]


def test_inverse_vol20_weights_lower_volatility_name_more_heavily():
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_INVERSE_VOL20,
        top_n=3,
        construction="inverse_vol20_weight",
    )
    dates = tuple(pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"]))
    weights = build_variant_target_weights(
        _scores(),
        spec=spec,
        evaluation_dates=dates,
        rebalance_days=1,
        vol20=_vol20(),
    )
    first_day = weights.xs(pd.Timestamp("2025-01-02"), level="datetime")

    assert first_day.loc["C", "target_weight"] > first_day.loc["B", "target_weight"]
    assert first_day.loc["B", "target_weight"] > first_day.loc["A", "target_weight"]
    assert abs(first_day["target_weight"].sum() - 1.0) < 1e-12


def test_benchmark_trend_filter_cuts_gross_exposure_on_negative_trend():
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=3,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=0.5,
    )
    dates = tuple(pd.to_datetime(["2025-01-02", "2025-01-13", "2025-01-24"]))
    weights = build_variant_target_weights(
        _scores(),
        spec=spec,
        evaluation_dates=dates,
        rebalance_days=1,
        benchmark_trend=_benchmark_trend(),
    )
    gross = weights["target_weight"].groupby(level="datetime").sum()

    assert gross.loc[pd.Timestamp("2025-01-02")] == 1.0
    assert gross.loc[pd.Timestamp("2025-01-13")] == 0.5
    assert gross.loc[pd.Timestamp("2025-01-24")] == 1.0


def test_evaluate_variant_reports_research_only_metrics():
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=3,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=0.5,
    )
    report = evaluate_risk_control_variant(
        _scores(),
        _returns(),
        _benchmark(),
        spec=spec,
        benchmark_trend=_benchmark_trend(),
        rebalance_days=1,
        cost_bps=20.0,
    )
    payload = report.to_dict()

    assert payload["variant_id"] == VARIANT_TOP3_BENCHMARK_TREND
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["max_gross_exposure"] == 1.0
    assert payload["min_gross_exposure"] == 0.5
    assert report.n_periods == 3


def test_aggregate_variant_reports_selects_only_gate_passing_variant():
    good = evaluate_risk_control_variant(
        _scores(),
        _returns(),
        _benchmark(),
        spec=RiskVariantSpec(
            variant_id=VARIANT_TOP5_EQUAL,
            top_n=5,
            construction="equal_weight",
        ),
        rebalance_days=1,
        cost_bps=0.0,
    )
    bad = evaluate_risk_control_variant(
        _scores(),
        _returns(),
        _benchmark(),
        spec=RiskVariantSpec(
            variant_id=VARIANT_TOP3_BENCHMARK_TREND,
            top_n=3,
            construction="equal_weight_with_benchmark_trend_filter",
            negative_benchmark_trend_exposure=0.5,
        ),
        benchmark_trend=_benchmark_trend(),
        rebalance_days=1,
        cost_bps=0.0,
    )

    summary = aggregate_variant_reports(
        {
            VARIANT_TOP5_EQUAL: [good, good, good, good],
            VARIANT_TOP3_BENCHMARK_TREND: [bad, bad],
        },
        min_positive_excess_windows=3,
        min_relative_excess_return=0.01,
        max_drawdown_gate=-0.50,
    )

    assert summary["research_only"] is True
    assert summary["trade_ready"] is False
    assert summary["candidate_v2_selected"] == VARIANT_TOP5_EQUAL
    assert summary["variants"][VARIANT_TOP5_EQUAL]["passes_candidate_v2_gate"] is True
    assert summary["variants"][VARIANT_TOP3_BENCHMARK_TREND]["passes_candidate_v2_gate"] is False
