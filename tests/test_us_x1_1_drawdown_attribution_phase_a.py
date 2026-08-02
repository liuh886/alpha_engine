from __future__ import annotations

import pandas as pd

from scripts.run_us_x1_1_drawdown_attribution_phase_a import (
    StrategySpec,
    _cap_weights,
    _decision,
    _drawdown_path,
    _evaluate,
    _effective_return_weights,
)


def _scores() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=11)
    rows = []
    for index, date in enumerate(dates):
        if index < 10:
            values = {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0}
        else:
            values = {"BBB": 3.0, "CCC": 2.0, "AAA": 1.0}
        for instrument, score in values.items():
            rows.append(
                {"datetime": date, "instrument": instrument, "score": score}
            )
    return pd.DataFrame(rows)


def _closes() -> pd.DataFrame:
    dates = pd.bdate_range("2024-09-02", "2025-02-28")
    index = pd.Series(range(len(dates)), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "AAA": 100.0 + index * 0.2,
            "BBB": 90.0 + index * 0.1,
            "CCC": 80.0 + index * 0.3,
            "QQQ": 200.0 + index * 0.15,
        },
        index=dates,
    )


def test_cap_weights_preserves_sum_and_cap() -> None:
    weights = pd.Series({"AAA": 0.8, "BBB": 0.1, "CCC": 0.1})
    result = _cap_weights(weights, 0.5)
    assert abs(float(result.sum()) - 1.0) < 1e-12
    assert float(result.max()) <= 0.5 + 1e-12


def test_missing_returns_are_renormalized_to_target_gross() -> None:
    target = {"AAA": 0.5, "BBB": 0.5}
    effective = _effective_return_weights(target, {"AAA": 0.10})
    assert effective == {"AAA": 1.0}

    half_gross = {"AAA": 0.25, "BBB": 0.25}
    effective_half = _effective_return_weights(half_gross, {"AAA": 0.10})
    assert effective_half == {"AAA": 0.5}


def test_evaluate_reconciles_exit_and_missing_return_costs() -> None:
    scores = _scores()
    dates = sorted(scores["datetime"].unique())[::10]
    returns = {
        pd.Timestamp(dates[0]): {"AAA": 0.10},
        pd.Timestamp(dates[1]): {"BBB": 0.02, "CCC": 0.04},
    }
    benchmark = {pd.Timestamp(date): 0.01 for date in dates}
    result, periods, contributions = _evaluate(
        scores,
        returns,
        benchmark,
        _closes(),
        StrategySpec("test", 2, "equal"),
        20,
    )
    reconciled = contributions.groupby("period_index")["net_contribution"].sum()
    expected = periods.set_index("period_index")["net_return"]
    pd.testing.assert_series_equal(reconciled, expected, check_names=False)

    first_aaa = contributions.loc[
        (contributions["period_index"] == 0)
        & (contributions["instrument"] == "AAA")
    ].iloc[0]
    first_bbb = contributions.loc[
        (contributions["period_index"] == 0)
        & (contributions["instrument"] == "BBB")
    ].iloc[0]
    assert float(first_aaa["effective_return_weight"]) == 1.0
    assert first_bbb["position_role"] == "held_missing_return"
    assert float(first_bbb["effective_return_weight"]) == 0.0

    exit_rows = contributions.loc[
        (contributions["period_index"] == 1)
        & (contributions["instrument"] == "AAA")
    ]
    assert len(exit_rows) == 1
    assert exit_rows.iloc[0]["position_role"] == "exit_cost_only"
    assert float(exit_rows.iloc[0]["allocated_cost"]) > 0
    assert result["n_periods"] == 2


def test_drawdown_path_finds_peak_trough_and_recovery() -> None:
    periods = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(
                ["2025-01-02", "2025-01-16", "2025-01-30", "2025-02-13"]
            ),
            "nav": [1.1, 0.88, 0.77, 1.12],
        }
    )
    result = _drawdown_path(periods)
    assert result["peak_date"] == "2025-01-02"
    assert result["trough_date"] == "2025-01-30"
    assert result["recovery_date"] == "2025-02-13"
    assert result["drawdown_period_indices"] == [1, 2]


def test_decision_identifies_mixed_name_and_regime() -> None:
    baseline = {"excess_return": 0.10, "max_drawdown": -0.30}
    variants = [
        {
            "strategy_id": "top20_equal_weight",
            "excess_return": 0.09,
            "max_drawdown": -0.28,
        },
        {
            "strategy_id": "top15_inverse_vol20_capped",
            "excess_return": 0.09,
            "max_drawdown": -0.27,
        },
        {
            "strategy_id": "top15_equal_weight_name_cap",
            "excess_return": 0.10,
            "max_drawdown": -0.30,
        },
        {
            "strategy_id": "top15_qqq_trend_overlay",
            "excess_return": 0.09,
            "max_drawdown": -0.24,
        },
    ]
    attribution = {
        "top3_negative_name_loss_share": 0.60,
        "negative_trend_loss_share": 0.70,
    }
    leave_one_out = [{"drawdown_improvement": 0.05}]
    result = _decision(baseline, variants, attribution, leave_one_out)
    assert result["decision"] == "mixed_name_and_regime_drawdown"
    assert result["name_concentration_gate"] is True
    assert result["regime_exposure_gate"] is True
