"""Focused tests for the Issue #947 CN x1.2 breadth-veto development runner."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.cn_ranker_exact_portfolio_replay import (
    _candidate_factor_contracts,
    _load_benchmark_returns,
    economic_rebalance_dates,
    validate_benchmark_execution_economic_rebalance_dates,
    validate_execution_economic_rebalance_dates,
)
from src.research.cn_x1_1_regime_gated import (
    SUPPORTED_REGIME_RULES,
    RegimeGateSpec,
    regime_signal,
    run_regime_portfolio,
)
from src.research.cn_x1_2_breadth_veto_development import (
    BASELINE_RULE,
    CHALLENGER_RULE,
    DEVELOPMENT_RUNNER_ID,
    DEVELOPMENT_WINDOWS,
    _assert_no_2026h2,
    _candidate_rule_map,
    _evaluate_development_gates,
    _validate_rule_separation,
)
from src.research.cross_sectional_experiment_runner import (
    load_cross_sectional_experiment_spec,
)

SPEC = Path("configs/research_experiments/cn_x1_2_alpha158_breadth_veto_v1.yaml")


def _state_row(long_trend: bool, momentum: bool, breadth: bool) -> pd.DataFrame:
    date = pd.Timestamp("2024-01-02")
    return pd.DataFrame(
        {
            "long_trend": [long_trend],
            "medium_momentum": [momentum],
            "cross_sectional_breadth": [breadth],
            "breadth_value": [0.6 if breadth else 0.4],
            "votes": [int(long_trend) + int(momentum) + int(breadth)],
        },
        index=[date],
    )


@pytest.mark.parametrize(
    ("long_trend", "momentum", "breadth", "expected"),
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, True),
        (True, False, False, False),
        (False, True, True, True),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, False),
    ],
)
def test_breadth_veto_truth_table(long_trend, momentum, breadth, expected) -> None:
    state = _state_row(long_trend, momentum, breadth)
    assert regime_signal(state, state.index[0], CHALLENGER_RULE) is expected


def test_breadth_veto_is_breadth_plus_one_trend_vote() -> None:
    date = pd.Timestamp("2024-01-02")
    state = pd.DataFrame(
        {
            "long_trend": [True],
            "medium_momentum": [False],
            "cross_sectional_breadth": [False],
            "breadth_value": [0.4],
            "votes": [1],
        },
        index=[date],
    )
    # votes=1 (trend only) is risk-off under the veto even though two_of_three
    # with the same two votes... two_of_three requires >=2, so also risk-off.
    assert not regime_signal(state, date, CHALLENGER_RULE)
    assert not regime_signal(state, date, BASELINE_RULE)


def test_breadth_veto_differs_from_two_of_three_when_breadth_vetoes() -> None:
    date = pd.Timestamp("2024-01-02")
    state = pd.DataFrame(
        {
            # Both trends pass, breadth fails: two_of_three is risk-on,
            # breadth_veto is risk-off (the veto overrides two votes).
            "long_trend": [True],
            "medium_momentum": [True],
            "cross_sectional_breadth": [False],
            "breadth_value": [0.4],
            "votes": [2],
        },
        index=[date],
    )
    assert regime_signal(state, date, BASELINE_RULE)
    assert not regime_signal(state, date, CHALLENGER_RULE)


def test_legacy_rules_and_default_are_unchanged() -> None:
    date = pd.Timestamp("2024-01-02")
    state = pd.DataFrame(
        {
            "long_trend": [True, True],
            "medium_momentum": [False, True],
            "cross_sectional_breadth": [True, False],
            "breadth_value": [0.6, 0.4],
            "votes": [2, 2],
        },
        index=[date, pd.Timestamp("2024-01-03")],
    )
    assert regime_signal(state, date, "two_of_three")
    assert regime_signal(state, date, "trend_only")
    assert not regime_signal(state, date, "momentum_and_breadth")
    assert not regime_signal(state, date, "three_of_three")
    assert CHALLENGER_RULE in SUPPORTED_REGIME_RULES
    assert BASELINE_RULE in SUPPORTED_REGIME_RULES
    with pytest.raises(ValueError, match="unsupported regime rule"):
        regime_signal(state, date, "not_a_rule")


def test_spec_declares_five_development_windows_and_947_authority() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    assert spec.market == "cn"
    assert spec.contract.selection_windows == DEVELOPMENT_WINDOWS
    assert spec.raw["authority_issue"] == 947
    assert spec.raw["development_runner"] == DEVELOPMENT_RUNNER_ID
    assert spec.raw["research_only"] is True
    assert spec.raw["trade_ready"] is False
    assert spec.raw["automatic_promotion"] is False
    assert spec.raw["rejected_parent_candidate"] == "cn_x1_2_alpha158_three_mechanism"
    assert spec.parent.walk_forward["test_end"] == "2026-06-30"
    assert spec.parent.walk_forward["partial_window_policy"] == "complete_windows_only"


def test_candidates_carry_frozen_signal_and_expected_rules() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    rules = _candidate_rule_map(spec)
    contracts = _candidate_factor_contracts(spec)

    assert rules["baseline_cn_x1_1"] == BASELINE_RULE
    assert rules["cn_x1_2_alpha158_breadth_veto"] == CHALLENGER_RULE
    assert len(contracts["baseline_cn_x1_1"]["factor_ids"]) == 14
    assert len(contracts["cn_x1_2_alpha158_breadth_veto"]["factor_ids"]) == 17
    assert contracts["cn_x1_2_alpha158_breadth_veto"]["factor_ids"][-3:] == (
        "qlib_alpha158.cntd30",
        "qlib_alpha158.cord5",
        "qlib_alpha158.imin30",
    )


def test_rule_separation_enforced_for_baseline_and_challenger() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    rules = {"baseline_cn_x1_1": BASELINE_RULE, "cn_x1_2_alpha158_breadth_veto": CHALLENGER_RULE}
    assert _validate_rule_separation(spec, rules) == "cn_x1_2_alpha158_breadth_veto"

    swapped = {
        "baseline_cn_x1_1": CHALLENGER_RULE,
        "cn_x1_2_alpha158_breadth_veto": BASELINE_RULE,
    }
    with pytest.raises(ValueError, match="baseline.*two_of_three"):
        _validate_rule_separation(spec, swapped)

    no_veto = {
        "baseline_cn_x1_1": BASELINE_RULE,
        "cn_x1_2_alpha158_breadth_veto": BASELINE_RULE,
    }
    with pytest.raises(ValueError, match="must use breadth_veto"):
        _validate_rule_separation(spec, no_veto)


def test_rule_map_rejects_unsupported_rules() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    mutated = spec.raw
    mutated["candidates"][1]["regime_rule"] = "mystery_rule"
    with pytest.raises(ValueError, match="unsupported regime rules"):
        _candidate_rule_map(spec)


def test_no_2026h2_fails_closed_on_reserved_holdout() -> None:
    _assert_no_2026h2([], label="empty")
    _assert_no_2026h2(["2024-01-02", "2026-06-30"], label="boundary")
    with pytest.raises(ValueError, match="reserved 2026H2 holdout"):
        _assert_no_2026h2(["2026-07-01"], label="holdout start")
    with pytest.raises(ValueError, match="reserved 2026H2 holdout"):
        _assert_no_2026h2(["2026-08-11"], label="provider cutoff")


def _summary(
    *,
    relative_excess: float,
    max_drawdown: float,
    positive_windows: int,
    risk_on_excess: float,
    risk_off_excess: float,
    risk_off_cost: float,
    risk_on_share: float,
    hit_rate: float,
) -> dict[str, float | int]:
    return {
        "relative_excess": relative_excess,
        "max_drawdown": max_drawdown,
        "positive_excess_windows": positive_windows,
        "risk_on_relative_excess": risk_on_excess,
        "risk_off_relative_excess": risk_off_excess,
        "risk_off_total_cost": risk_off_cost,
        "risk_on_share": risk_on_share,
        "risk_on_active_hit_rate": hit_rate,
    }


def _window_frame(excess: dict[str, float], drawdown: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "window": list(excess),
            "relative_excess": [excess[label] for label in DEVELOPMENT_WINDOWS],
            "max_drawdown": [drawdown] * len(DEVELOPMENT_WINDOWS),
        }
    )


def _passing_gate_inputs():
    baseline = _summary(
        relative_excess=0.05,
        max_drawdown=-0.08,
        positive_windows=3,
        risk_on_excess=0.06,
        risk_off_excess=-0.01,
        risk_off_cost=0.01,
        risk_on_share=0.60,
        hit_rate=0.55,
    )
    baseline_stress = _summary(
        relative_excess=0.01,
        max_drawdown=-0.09,
        positive_windows=3,
        risk_on_excess=0.02,
        risk_off_excess=-0.01,
        risk_off_cost=0.01,
        risk_on_share=0.60,
        hit_rate=0.55,
    )
    challenger = _summary(
        relative_excess=0.09,
        max_drawdown=-0.10,
        positive_windows=4,
        risk_on_excess=0.10,
        risk_off_excess=-0.005,
        risk_off_cost=0.01,
        risk_on_share=0.55,
        hit_rate=0.60,
    )
    challenger_stress = _summary(
        relative_excess=0.03,
        max_drawdown=-0.11,
        positive_windows=4,
        risk_on_excess=0.04,
        risk_off_excess=-0.005,
        risk_off_cost=0.01,
        risk_on_share=0.55,
        hit_rate=0.60,
    )
    base_20 = _window_frame(
        {"2024H1": 0.01, "2024H2": 0.02, "2025H1": 0.01, "2025H2": 0.02, "2026H1": 0.01},
        drawdown=-0.08,
    )
    base_60 = _window_frame(
        {"2024H1": 0.00, "2024H2": 0.01, "2025H1": 0.00, "2025H2": 0.01, "2026H1": 0.00},
        drawdown=-0.09,
    )
    chal_20 = _window_frame(
        {"2024H1": 0.02, "2024H2": 0.03, "2025H1": 0.02, "2025H2": 0.03, "2026H1": 0.02},
        drawdown=-0.10,
    )
    chal_60 = _window_frame(
        {"2024H1": 0.01, "2024H2": 0.02, "2025H1": 0.01, "2025H2": 0.02, "2026H1": 0.01},
        drawdown=-0.11,
    )
    return {
        "baseline": baseline,
        "baseline_stress": baseline_stress,
        "challenger": challenger,
        "challenger_stress": challenger_stress,
        "baseline_windows_20": base_20,
        "baseline_windows_60": base_60,
        "challenger_windows_20": chal_20,
        "challenger_windows_60": chal_60,
        "challenger_mean_rank_ic": 0.01,
        "deterministic_scores": True,
        "deterministic_portfolio": True,
    }


def test_development_gates_pass_when_all_issue947_conditions_hold() -> None:
    result = _evaluate_development_gates(**_passing_gate_inputs())
    assert result["supported"] is True
    assert all(result["checks"].values())


def test_2026h1_drawdown_worsening_gate_is_enforced() -> None:
    inputs = _passing_gate_inputs()
    # 2026H1 challenger drawdown worsens by 8pp vs incumbent (> 3pp boundary).
    inputs["challenger_windows_20"] = _window_frame(
        {"2024H1": 0.02, "2024H2": 0.03, "2025H1": 0.02, "2025H2": 0.03, "2026H1": 0.02},
        drawdown=-0.16,
    )
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["2026h1_drawdown_worsening_within_3pp"] is False


def test_2026h1_beat_incumbent_checks_are_enforced_at_both_costs() -> None:
    inputs = _passing_gate_inputs()
    inputs["challenger_windows_20"] = _window_frame(
        {"2024H1": 0.02, "2024H2": 0.03, "2025H1": 0.02, "2025H2": 0.03, "2026H1": 0.00},
        drawdown=-0.10,
    )
    inputs["challenger_windows_60"] = _window_frame(
        {"2024H1": 0.01, "2024H2": 0.02, "2025H1": 0.01, "2025H2": 0.02, "2026H1": 0.00},
        drawdown=-0.11,
    )
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["2026h1_beats_incumbent_20bps"] is False
    assert result["checks"]["2026h1_beats_incumbent_60bps"] is False
    assert result["checks"]["at_least_four_of_five_positive_windows"] is True


def test_positive_window_share_and_risk_on_gates_are_enforced() -> None:
    inputs = _passing_gate_inputs()
    inputs["challenger"] = _summary(
        relative_excess=0.09,
        max_drawdown=-0.10,
        positive_windows=3,
        risk_on_excess=0.10,
        risk_off_excess=-0.005,
        risk_off_cost=0.01,
        risk_on_share=0.90,
        hit_rate=0.60,
    )
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["at_least_four_of_five_positive_windows"] is False
    assert result["checks"]["risk_on_share_within_bounds"] is False


def test_determinism_contract_reaches_the_support_decision() -> None:
    inputs = _passing_gate_inputs()
    inputs["deterministic_portfolio"] = False
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["exact_portfolio_reproduction"] is False
    assert result["checks"]["exact_score_reproduction"] is True


# ---------------------------------------------------------------------------
# Outcome-independent execution validation (Issue #947)
# ---------------------------------------------------------------------------


class _FakeRuntime:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def features(self, instruments, expressions, start, end):
        return self._frame


def _execution_frame(dates, values) -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [np.repeat(["000001"], len(dates)), pd.DatetimeIndex(dates)],
        names=["instrument", "datetime"],
    )
    return pd.DataFrame({"execution_forward_return": values}, index=index)


def _portfolio_row(
    *,
    window: str,
    date: pd.Timestamp,
    instrument: str,
    sector: str,
    score: float,
    exec_return: float,
) -> dict:
    return {
        "window": window,
        "datetime": date,
        "instrument": instrument,
        "entity": instrument,
        "sector": sector,
        "score": score,
        "execution_forward_return": exec_return,
    }


def _risk_on_ledger(dates, *, window: str = "2026H1") -> pd.DataFrame:
    """Build a CN sector ledger where exactly the fixed 4x1 selection is finite.

    Sectors A-D carry one finite high-score name each (the governed selection);
    every other name is non-finite (dropped by ``choose_holdings``) so the
    universe is never required to be fully finite before selection.
    """

    rows: list[dict] = []
    counter = 1
    for date in dates:
        for sector, top_score in (
            ("A", 100.0),
            ("B", 99.0),
            ("C", 98.0),
            ("D", 97.0),
        ):
            rows.append(
                _portfolio_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=top_score,
                    exec_return=0.02,
                )
            )
            counter += 1
            rows.append(
                _portfolio_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=20.0,
                    exec_return=np.nan,
                )
            )
            counter += 1
        for sector, top_score in (("E", 50.0), ("F", 40.0)):
            rows.append(
                _portfolio_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=top_score,
                    exec_return=np.nan,
                )
            )
            counter += 1
            rows.append(
                _portfolio_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=10.0,
                    exec_return=np.nan,
                )
            )
            counter += 1
    return pd.DataFrame(rows)


def _regime_state(dates) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "long_trend": [True] * len(dates),
            "medium_momentum": [True] * len(dates),
            "cross_sectional_breadth": [True] * len(dates),
            "breadth_value": [0.8] * len(dates),
            "votes": [3] * len(dates),
        },
        index=dates,
    )


def _benchmark_series(dates, value: float = 0.01) -> pd.Series:
    return pd.Series([value] * len(dates), index=dates)


def _load_benchmark(runtime, *, required_dates, require_finite: bool = True):
    return _load_benchmark_returns(
        runtime,
        benchmark_instrument="000300",
        return_expression="expr",
        evaluation_dates=pd.DatetimeIndex(
            pd.to_datetime(["2026-05-06", "2026-05-07", "2026-05-08"])
        ),
        start="2026-05-01",
        end="2026-05-31",
        provenance="raw_forward_return",
        horizon=10,
        required_dates=required_dates,
        require_finite=require_finite,
    )


def test_economic_rebalance_dates_samples_cadence() -> None:
    dates = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-09",
                "2026-01-12",
                "2026-01-13",
            ]
        )
    )

    sampled = economic_rebalance_dates(dates, 3)

    assert list(sampled) == [dates[0], dates[3], dates[6]]


def test_economic_rebalance_dates_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        economic_rebalance_dates(pd.DatetimeIndex([]), 10)
    with pytest.raises(ValueError, match="positive"):
        economic_rebalance_dates(pd.DatetimeIndex(pd.to_datetime(["2026-01-02", "2026-01-05"])), 0)
    with pytest.raises(ValueError, match="unique"):
        economic_rebalance_dates(pd.DatetimeIndex(pd.to_datetime(["2026-01-02", "2026-01-02"])), 2)


def test_benchmark_missing_required_rebalance_date_fails_closed() -> None:
    frame = pd.DataFrame(
        {"return": [0.01, 0.02]},
        index=pd.to_datetime(["2026-05-06", "2026-05-07"]),
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-08"]))

    with pytest.raises(ValueError, match="missing"):
        _load_benchmark(_FakeRuntime(frame), required_dates=required)


def test_benchmark_non_finite_required_date_fails() -> None:
    frame = pd.DataFrame(
        {"return": [np.nan]},
        index=pd.to_datetime(["2026-05-06"]),
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))

    with pytest.raises(ValueError, match="non-finite"):
        _load_benchmark(_FakeRuntime(frame), required_dates=required)


def test_benchmark_ignores_unsampled_tail_dates() -> None:
    frame = pd.DataFrame(
        {"return": [0.01, np.nan]},
        index=pd.to_datetime(["2026-05-06", "2026-05-07"]),
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))

    result = _load_benchmark(_FakeRuntime(frame), required_dates=required)

    assert list(result.index) == [pd.Timestamp("2026-05-06")]


def test_benchmark_default_policy_requires_all_evaluation_dates() -> None:
    frame = pd.DataFrame(
        {"return": [0.01]},
        index=pd.to_datetime(["2026-05-06"]),
    )

    with pytest.raises(ValueError, match="missing"):
        _load_benchmark(_FakeRuntime(frame), required_dates=None)


def test_benchmark_default_policy_accepts_complete_series() -> None:
    frame = pd.DataFrame(
        {"return": [0.01, 0.02, 0.03]},
        index=pd.to_datetime(["2026-05-06", "2026-05-07", "2026-05-08"]),
    )

    result = _load_benchmark(_FakeRuntime(frame), required_dates=None)

    assert len(result) == 3


def test_execution_missing_rebalance_date_fails_closed() -> None:
    frame = _execution_frame(
        pd.to_datetime(["2026-05-06", "2026-05-07"]),
        [0.01, 0.02],
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-08"]))

    with pytest.raises(ValueError, match="missing"):
        validate_execution_economic_rebalance_dates(frame, required, "2026H1")


def test_execution_non_finite_rebalance_date_presence_only() -> None:
    frame = _execution_frame(pd.to_datetime(["2026-05-06"]), [np.nan])
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))

    validate_execution_economic_rebalance_dates(frame, required, "2026H1")


def test_execution_ignores_unsampled_tail_dates() -> None:
    frame = _execution_frame(
        pd.to_datetime(["2026-05-06", "2026-05-07"]),
        [0.01, np.nan],
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))

    validate_execution_economic_rebalance_dates(frame, required, "2026H1")


def test_risk_on_partial_universe_non_finite_allowed_when_four_selected_valid() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _risk_on_ledger(dates)

    summary, periods, holdings, _ = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        _regime_state(dates),
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rebalance_sessions=1,
        cost_bps=20,
        validate_holdings=True,
    )

    assert periods.iloc[0]["risk_on"]
    assert len(periods) == 1
    assert len(holdings.loc[holdings["instrument"] != "000300"]) == 4
    assert summary["rebalance_count"] == 1


def test_risk_on_short_selection_fails_closed() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    rows = [
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="A",
            score=100.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000002",
            sector="B",
            score=99.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000003",
            sector="C",
            score=98.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000004",
            sector="D",
            score=97.0,
            exec_return=np.nan,
        ),
    ]
    ledger = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="exactly 4 names"):
        run_regime_portfolio(
            ledger,
            _benchmark_series(dates),
            _regime_state(dates),
            windows=("2026H1",),
            variant=RegimeGateSpec().variant(),
            rebalance_sessions=1,
            cost_bps=20,
            validate_holdings=True,
        )

    # Legacy path (no guard) still accepts the short selection unchanged.
    summary, _, _, _ = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        _regime_state(dates),
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rebalance_sessions=1,
        cost_bps=20,
    )
    assert summary["rebalance_count"] == 1


def test_risk_on_non_finite_selected_holding_fails_closed() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    rows = [
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="A",
            score=100.0,
            exec_return=np.inf,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000002",
            sector="B",
            score=99.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000003",
            sector="C",
            score=98.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000004",
            sector="D",
            score=97.0,
            exec_return=0.02,
        ),
    ]
    ledger = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="non-finite execution return"):
        run_regime_portfolio(
            ledger,
            _benchmark_series(dates),
            _regime_state(dates),
            windows=("2026H1",),
            variant=RegimeGateSpec().variant(),
            rebalance_sessions=1,
            cost_bps=20,
            validate_holdings=True,
        )


def test_risk_on_duplicate_selected_holdings_fails_closed() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    rows = [
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="A",
            score=100.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="B",
            score=99.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000002",
            sector="C",
            score=98.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000003",
            sector="D",
            score=97.0,
            exec_return=0.02,
        ),
    ]
    ledger = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="duplicate holdings"):
        run_regime_portfolio(
            ledger,
            _benchmark_series(dates),
            _regime_state(dates),
            windows=("2026H1",),
            variant=RegimeGateSpec().variant(),
            rebalance_sessions=1,
            cost_bps=20,
            validate_holdings=True,
        )


def test_holdings_validation_identical_for_baseline_and_challenger_rules() -> None:
    """Issue #947: execution validation must apply to both regime rules, not just the incumbent.

    The baseline (``two_of_three``) and challenger (``breadth_veto``) share one
    runtime; the only allowed delta is the risk-on rule. A full 4x1 selection
    passes under both, and a short selection is rejected identically under both.
    """

    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    state = _regime_state(dates)  # all votes pass -> both rules are risk-on
    full = pd.DataFrame(
        [
            _portfolio_row(
                window="2026H1",
                date=dates[0],
                instrument="000001",
                sector="A",
                score=100.0,
                exec_return=0.02,
            ),
            _portfolio_row(
                window="2026H1",
                date=dates[0],
                instrument="000002",
                sector="B",
                score=99.0,
                exec_return=0.02,
            ),
            _portfolio_row(
                window="2026H1",
                date=dates[0],
                instrument="000003",
                sector="C",
                score=98.0,
                exec_return=0.02,
            ),
            _portfolio_row(
                window="2026H1",
                date=dates[0],
                instrument="000004",
                sector="D",
                score=97.0,
                exec_return=0.02,
            ),
        ]
    )
    for rule in (BASELINE_RULE, CHALLENGER_RULE):
        summary, periods, holdings, _ = run_regime_portfolio(
            full,
            _benchmark_series(dates),
            state,
            windows=("2026H1",),
            variant=RegimeGateSpec().variant(),
            rebalance_sessions=1,
            cost_bps=20,
            rule=rule,
            validate_holdings=True,
        )
        assert periods.iloc[0]["risk_on"]
        assert summary["rebalance_count"] == 1
        assert len(holdings.loc[holdings["instrument"] != "000300"]) == 4

    short = full.iloc[:-1]
    for rule in (BASELINE_RULE, CHALLENGER_RULE):
        with pytest.raises(ValueError, match="exactly 4 names"):
            run_regime_portfolio(
                short,
                _benchmark_series(dates),
                state,
                windows=("2026H1",),
                variant=RegimeGateSpec().variant(),
                rebalance_sessions=1,
                cost_bps=20,
                rule=rule,
                validate_holdings=True,
            )


def test_benchmark_delay_zero_diagnostic_retains_non_finite_when_gate_deferred() -> None:
    frame = pd.DataFrame(
        {"return": [0.01, np.nan]},
        index=pd.to_datetime(["2026-05-06", "2026-05-07"]),
    )
    required = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-07"]))

    result = _load_benchmark(
        _FakeRuntime(frame),
        required_dates=required,
        require_finite=False,
    )

    assert list(result.index) == [
        pd.Timestamp("2026-05-06"),
        pd.Timestamp("2026-05-07"),
    ]
    assert np.isnan(result.iloc[1, 0])


def test_benchmark_delay_one_execution_gate_accepts_finite_rebalance_dates() -> None:
    rebalance = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-08"]))
    execution = pd.Series([0.01, 0.02], index=rebalance)

    validate_benchmark_execution_economic_rebalance_dates(execution, rebalance, "2026H1")


def test_benchmark_delay_one_execution_gate_fails_non_finite() -> None:
    rebalance = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    execution = pd.Series([np.nan], index=rebalance)

    with pytest.raises(ValueError, match="non-finite"):
        validate_benchmark_execution_economic_rebalance_dates(execution, rebalance, "2026H1")


def test_benchmark_delay_one_execution_gate_fails_missing_date() -> None:
    rebalance = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    execution = pd.Series([0.01], index=pd.DatetimeIndex(pd.to_datetime(["2026-05-05"])))

    with pytest.raises(ValueError, match="missing"):
        validate_benchmark_execution_economic_rebalance_dates(execution, rebalance, "2026H1")


def test_validate_holdings_default_keeps_legacy_behavior() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    rows = [
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="A",
            score=100.0,
            exec_return=0.02,
        ),
        _portfolio_row(
            window="2026H1",
            date=dates[0],
            instrument="000002",
            sector="B",
            score=99.0,
            exec_return=0.02,
        ),
    ]
    ledger = pd.DataFrame(rows)

    summary, _, _, _ = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        _regime_state(dates),
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rebalance_sessions=1,
        cost_bps=20,
    )

    assert summary["rebalance_count"] == 1
