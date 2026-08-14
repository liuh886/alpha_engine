"""Focused tests for the Issue #954 CN x1.2 breadth-scaled development runner."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

import scripts.run_cn_ranker_exact_portfolio_replay as replay_script
import src.research.cn_x1_2_breadth_scaled_development as scaled_development
from src.research.cn_x1_1_regime_gated import (
    EXPOSURE_POLICIES,
    SUPPORTED_REGIME_RULES,
    RegimeGateSpec,
    clamped_active_share,
    regime_signal,
    run_regime_portfolio,
)
from src.research.cn_x1_2_breadth_scaled_development import (
    AUTHORITY_ISSUE,
    BASELINE_EXPOSURE_POLICY,
    BASELINE_RULE,
    CHALLENGER_EXPOSURE_POLICY,
    CHALLENGER_RULE,
    DEVELOPMENT_HARD_STOP,
    DEVELOPMENT_RUNNER_ID,
    DEVELOPMENT_WINDOWS,
    RESERVED_HOLDOUT_START,
    SIGNAL_RUNNER_ID,
    _assert_no_2026h2,
    _candidate_exposure_map,
    _candidate_rule_map,
    _evaluate_development_gates,
    _score_artifact_contract,
    _scaled_diagnostics,
    _validate_candidate_separation,
)
from src.research.cn_ranker_exact_portfolio_replay import _candidate_factor_contracts
from src.research.cross_sectional_experiment_runner import (
    load_cross_sectional_experiment_spec,
)
from src.research.resumable_score_artifacts import canonical_sha256

SPEC = Path("configs/research_experiments/cn_x1_2_alpha158_breadth_scaled_v1.yaml")


def _state_row(
    long_trend: bool,
    momentum: bool,
    breadth: bool,
    breadth_value: float,
) -> pd.DataFrame:
    date = pd.Timestamp("2024-01-02")
    return pd.DataFrame(
        {
            "long_trend": [long_trend],
            "medium_momentum": [momentum],
            "cross_sectional_breadth": [breadth],
            "breadth_value": [breadth_value],
            "votes": [int(long_trend) + int(momentum) + int(breadth)],
        },
        index=[date],
    )


# ---------------------------------------------------------------------------
# Active-share formula (Issue #954)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("breadth_value", "expected"),
    [
        (0.50, 1.0),
        (0.25, 0.5),
        (0.00, 0.0),
        (0.75, 1.0),
        (1.00, 1.0),
        (-0.50, 0.0),
        (0.40, 0.8),
        (0.05, 0.1),
    ],
)
def test_clamped_active_share_truth_table(breadth_value, expected) -> None:
    assert clamped_active_share(breadth_value) == pytest.approx(expected)


def test_clamped_active_share_always_within_unit_bounds() -> None:
    for value in (-10.0, -1.0, -0.01, 0.0, 0.1, 0.5, 1.0, 5.0, 100.0):
        assert 0.0 <= clamped_active_share(value) <= 1.0


def test_clamped_active_share_rejects_nonpositive_threshold() -> None:
    with pytest.raises(ValueError, match="positive"):
        clamped_active_share(0.5, breadth_threshold=0.0)


def test_breadth_scaled_eligibility_is_two_of_three() -> None:
    date = pd.Timestamp("2024-01-02")
    # Breadth fails but both trends pass: two_of_three votes=2 -> eligible.
    state = _state_row(True, True, False, 0.25)
    assert regime_signal(state, date, BASELINE_RULE)
    assert CHALLENGER_RULE == BASELINE_RULE
    # Only one trend plus breadth: votes=2 -> still eligible (two_of_three).
    state2 = _state_row(True, False, True, 0.75)
    assert regime_signal(state2, date, CHALLENGER_RULE)
    # One trend only: votes=1 -> ineligible.
    state3 = _state_row(True, False, False, 0.25)
    assert not regime_signal(state3, date, CHALLENGER_RULE)


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------


def _name_row(
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


def _four_name_ledger(
    dates,
    *,
    window: str = "2026H1",
    exec_return: float = 0.02,
    extra: list[dict] | None = None,
) -> pd.DataFrame:
    """A CN ledger with exactly one finite high-score name per sector A-D per date."""

    rows: list[dict] = []
    counter = 1
    for date in dates:
        for sector, top_score in (("A", 100.0), ("B", 99.0), ("C", 98.0), ("D", 97.0)):
            rows.append(
                _name_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=top_score,
                    exec_return=exec_return,
                )
            )
            counter += 1
            rows.append(
                _name_row(
                    window=window,
                    date=date,
                    instrument=f"{counter:06d}",
                    sector=sector,
                    score=20.0,
                    exec_return=np.nan,
                )
            )
            counter += 1
    if extra:
        rows.extend(extra)
    return pd.DataFrame(rows)


def _regime_state(dates, *, breadth_value: float = 0.25) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "long_trend": [True] * len(dates),
            "medium_momentum": [True] * len(dates),
            "cross_sectional_breadth": [False] * len(dates),
            "breadth_value": [breadth_value] * len(dates),
            "votes": [2] * len(dates),
        },
        index=dates,
    )


def _benchmark_series(dates, value: float = 0.01) -> pd.Series:
    return pd.Series([value] * len(dates), index=dates)


def _run_scaled(ledger, dates, *, breadth_value=0.25, rebalance=1, cost_bps=20):
    return run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        _regime_state(dates, breadth_value=breadth_value),
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rule=CHALLENGER_RULE,
        exposure_policy=CHALLENGER_EXPOSURE_POLICY,
        breadth_threshold=0.50,
        rebalance_sessions=rebalance,
        cost_bps=cost_bps,
        validate_holdings=True,
    )


# ---------------------------------------------------------------------------
# Breadth-scaled portfolio behavior
# ---------------------------------------------------------------------------


def test_scaled_mixed_weights_are_exact_4_names_plus_csi300_sleeve() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates)
    summary, periods, holdings, _ = _run_scaled(
        ledger,
        dates,
        breadth_value=0.25,  # active_share = 0.5
    )

    assert periods.iloc[0]["risk_on"]
    assert periods.iloc[0]["risk_on_eligible"]
    assert periods.iloc[0]["active_share"] == pytest.approx(0.5)
    assert periods.iloc[0]["benchmark_sleeve"] == pytest.approx(0.5)

    active = holdings.loc[holdings["instrument"] != "000300"]
    assert len(active) == 4
    assert active["instrument"].is_unique
    assert set(active["sector"]) == {"A", "B", "C", "D"}
    assert active["weight"].to_numpy() == pytest.approx(np.full(4, 0.125))

    sleeve = holdings.loc[holdings["entity"] == "CSI300 sleeve"]
    assert len(sleeve) == 1
    assert sleeve.iloc[0]["instrument"] == "000300"
    assert sleeve.iloc[0]["weight"] == pytest.approx(0.5)

    # Weights across names + benchmark sleeve sum to exactly 1.
    assert active["weight"].sum() + sleeve["weight"].sum() == pytest.approx(1.0)


def test_scaled_mixed_weights_sum_to_exactly_one_every_period() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-07", "2026-05-08"]))
    ledger = _four_name_ledger(dates)
    _, periods, _, _ = _run_scaled(ledger, dates, breadth_value=0.25)

    combined = periods["active_share"].to_numpy() + periods["benchmark_sleeve"].to_numpy()
    assert np.allclose(combined, 1.0)


def test_scaled_turnover_includes_benchmark_sleeve_transition() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-07"]))
    ledger = _four_name_ledger(dates)
    # date0 is risk-off (votes=1) -> previous holds {000300: 1.0}; date1 is
    # eligible with weak breadth (votes=2, active_share=0.5) -> mixed weights
    # {4 names 0.125 each, 000300 0.5}. The sleeve term |0.5 - 1.0| = 0.5 must
    # be traded; without it turnover would be only 0.25.
    state = pd.DataFrame(
        {
            "long_trend": [True, True],
            "medium_momentum": [False, True],
            "cross_sectional_breadth": [False, False],
            "breadth_value": [0.25, 0.25],
            "votes": [1, 2],
        },
        index=dates,
    )
    summary, periods, holdings, _ = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        state,
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rule=CHALLENGER_RULE,
        exposure_policy=CHALLENGER_EXPOSURE_POLICY,
        rebalance_sessions=1,
        cost_bps=20,
        validate_holdings=True,
    )

    assert not periods.iloc[0]["risk_on"]
    assert periods.iloc[1]["risk_on"]
    assert periods.iloc[1]["turnover"] == pytest.approx(0.5)


def test_scaled_full_exposure_date_still_has_weights_sum_to_one() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates)
    summary, periods, holdings, _ = _run_scaled(ledger, dates, breadth_value=0.75)

    assert periods.iloc[0]["risk_on"]
    assert periods.iloc[0]["active_share"] == pytest.approx(1.0)
    assert periods.iloc[0]["benchmark_sleeve"] == pytest.approx(0.0)
    assert periods.iloc[0]["active_share"] + periods.iloc[0]["benchmark_sleeve"] == 1.0
    # No positive-weight sleeve row at full exposure.
    assert "CSI300 sleeve" not in set(holdings["entity"])
    active = holdings.loc[holdings["instrument"] != "000300"]
    assert active["weight"].sum() == pytest.approx(1.0)


def test_scaled_risk_off_holds_100pct_benchmark() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates)
    # Ineligible: votes=1 (one trend, no breadth).
    state = pd.DataFrame(
        {
            "long_trend": [True],
            "medium_momentum": [False],
            "cross_sectional_breadth": [False],
            "breadth_value": [0.25],
            "votes": [1],
        },
        index=dates,
    )
    summary, periods, holdings, _ = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        state,
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rule=CHALLENGER_RULE,
        exposure_policy=CHALLENGER_EXPOSURE_POLICY,
        rebalance_sessions=1,
        cost_bps=20,
        validate_holdings=True,
    )

    assert not periods.iloc[0]["risk_on"]
    assert not periods.iloc[0]["risk_on_eligible"]
    assert periods.iloc[0]["active_share"] == pytest.approx(0.0)
    assert periods.iloc[0]["benchmark_sleeve"] == pytest.approx(1.0)
    assert periods.iloc[0]["gross_return"] == pytest.approx(0.01)
    fallback = holdings.loc[holdings["entity"] == "CSI300 fallback"]
    assert len(fallback) == 1
    assert fallback.iloc[0]["weight"] == pytest.approx(1.0)
    assert len(holdings.loc[holdings["instrument"] != "000300"]) == 0


def test_scaled_eligible_zero_share_is_risk_off_but_records_eligibility() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates)
    summary, periods, holdings, _ = _run_scaled(ledger, dates, breadth_value=0.0)

    assert periods.iloc[0]["risk_on_eligible"]
    assert not periods.iloc[0]["risk_on"]
    assert periods.iloc[0]["active_share"] == pytest.approx(0.0)
    assert periods.iloc[0]["benchmark_sleeve"] == pytest.approx(1.0)
    assert periods.iloc[0]["gross_return"] == pytest.approx(0.01)


def test_scaled_gross_return_blends_active_and_benchmark_sleeve() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates, exec_return=0.04)
    summary, periods, _, _ = _run_scaled(ledger, dates, breadth_value=0.25)

    # active_share=0.5 * mean(exec)=0.04 + 0.5 * benchmark=0.01 = 0.025.
    assert periods.iloc[0]["gross_return"] == pytest.approx(0.5 * 0.04 + 0.5 * 0.01)


def test_scaled_validate_holdings_enforces_exact_four_finite_unique() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))

    # Short selection (only 3 sectors represented).
    short = pd.DataFrame(
        [
            _name_row(
                window="2026H1",
                date=dates[0],
                instrument="000001",
                sector="A",
                score=100.0,
                exec_return=0.02,
            ),
            _name_row(
                window="2026H1",
                date=dates[0],
                instrument="000002",
                sector="B",
                score=99.0,
                exec_return=0.02,
            ),
            _name_row(
                window="2026H1",
                date=dates[0],
                instrument="000003",
                sector="C",
                score=98.0,
                exec_return=0.02,
            ),
            _name_row(
                window="2026H1",
                date=dates[0],
                instrument="000004",
                sector="D",
                score=97.0,
                exec_return=np.nan,
            ),
        ]
    )
    with pytest.raises(ValueError, match="exactly 4 names"):
        _run_scaled(short, dates, breadth_value=0.25)

    # Non-finite selected holding.
    nonfinite = _four_name_ledger(dates, exec_return=0.02)
    nonfinite.loc[nonfinite["score"] == 100.0, "execution_forward_return"] = np.inf
    with pytest.raises(ValueError, match="non-finite execution return"):
        _run_scaled(nonfinite, dates, breadth_value=0.25)

    # Duplicate instrument across sectors.
    duplicate = _four_name_ledger(dates)
    dup = duplicate.copy()
    dup.loc[dup["score"] == 99.0, "instrument"] = "000001"
    dup.loc[dup["score"] == 99.0, "sector"] = "B"
    with pytest.raises(ValueError, match="duplicate holdings"):
        _run_scaled(dup, dates, breadth_value=0.25)


# ---------------------------------------------------------------------------
# Baseline / legacy unchanged
# ---------------------------------------------------------------------------


def test_baseline_full_exposure_is_legacy_unscaled() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-07"]))
    ledger = _four_name_ledger(dates)
    state = _regime_state(dates, breadth_value=0.75)

    explicit = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        state,
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rule=BASELINE_RULE,
        exposure_policy=BASELINE_EXPOSURE_POLICY,
        rebalance_sessions=1,
        cost_bps=20,
        validate_holdings=True,
    )
    legacy = run_regime_portfolio(
        ledger,
        _benchmark_series(dates),
        state,
        windows=("2026H1",),
        variant=RegimeGateSpec().variant(),
        rule=BASELINE_RULE,
        rebalance_sessions=1,
        cost_bps=20,
    )

    assert explicit[0] == legacy[0]
    pd.testing.assert_frame_equal(explicit[1], legacy[1])
    pd.testing.assert_frame_equal(explicit[2], legacy[2])
    # Legacy frames must not gain the Issue #954 diagnostic columns.
    assert "active_share" not in legacy[1].columns
    assert "benchmark_sleeve" not in legacy[1].columns


def test_breadth_veto_unchanged_under_supported_rules() -> None:
    assert "breadth_veto" in SUPPORTED_REGIME_RULES
    assert "two_of_three" in SUPPORTED_REGIME_RULES
    assert BASELINE_EXPOSURE_POLICY == "full_exposure"
    assert CHALLENGER_EXPOSURE_POLICY in EXPOSURE_POLICIES
    date = pd.Timestamp("2024-01-02")
    state = _state_row(True, True, False, 0.4)
    # breadth_veto vetoes two passing trend votes; baseline two_of_three stays on.
    assert regime_signal(state, date, "two_of_three")
    assert not regime_signal(state, date, "breadth_veto")


def test_unsupported_exposure_policy_fails_closed() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06"]))
    ledger = _four_name_ledger(dates)
    with pytest.raises(ValueError, match="unsupported exposure policy"):
        run_regime_portfolio(
            ledger,
            _benchmark_series(dates),
            _regime_state(dates),
            windows=("2026H1",),
            variant=RegimeGateSpec().variant(),
            rule=BASELINE_RULE,
            exposure_policy="mystery_policy",
            rebalance_sessions=1,
            cost_bps=20,
        )


def test_scaled_portfolio_is_deterministic() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-05-06", "2026-05-07"]))
    ledger = _four_name_ledger(dates)

    first = _run_scaled(ledger, dates, breadth_value=0.25)
    second = _run_scaled(ledger, dates, breadth_value=0.25)

    assert first[0] == second[0]
    pd.testing.assert_frame_equal(first[1], second[1])
    pd.testing.assert_frame_equal(first[2], second[2])
    pd.testing.assert_frame_equal(first[3], second[3])


# ---------------------------------------------------------------------------
# Scaled diagnostics
# ---------------------------------------------------------------------------


def test_scaled_diagnostics_reports_active_share_and_sleeve() -> None:
    dates = pd.to_datetime(["2026-05-06", "2026-05-07"])
    periods = pd.DataFrame(
        {
            "window": ["2026H1"] * 3,
            "datetime": [dates[0], dates[1], dates[1]],
            "risk_on": [True, True, False],
            "risk_on_eligible": [True, True, True],
            "active_share": [0.5, 0.8, 0.0],
            "benchmark_sleeve": [0.5, 0.2, 1.0],
        }
    )
    name_rows = [
        _name_row(
            window="2026H1",
            date=dates[0],
            instrument="000001",
            sector="A",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[0],
            instrument="000002",
            sector="B",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[0],
            instrument="000003",
            sector="C",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[0],
            instrument="000004",
            sector="D",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[1],
            instrument="000005",
            sector="A",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[1],
            instrument="000006",
            sector="B",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[1],
            instrument="000007",
            sector="C",
            score=1.0,
            exec_return=0.02,
        ),
        _name_row(
            window="2026H1",
            date=dates[1],
            instrument="000008",
            sector="D",
            score=1.0,
            exec_return=0.02,
        ),
    ]
    sleeve = [
        {
            "window": "2026H1",
            "datetime": dates[0],
            "instrument": "000300",
            "entity": "CSI300 sleeve",
            "sector": "CSI300",
            "score": np.nan,
            "weight": 0.5,
            "raw_return": 0.01,
            "benchmark_return": 0.01,
            "net_contribution": 0.005,
            "precision_hit": False,
        },
        {
            "window": "2026H1",
            "datetime": dates[1],
            "instrument": "000300",
            "entity": "CSI300 fallback",
            "sector": "CSI300",
            "score": np.nan,
            "weight": 1.0,
            "raw_return": 0.01,
            "benchmark_return": 0.01,
            "net_contribution": 0.01,
            "precision_hit": False,
        },
    ]
    # _scaled_diagnostics validates raw_return finiteness per exact-4 group; the
    # hand-built name rows must carry the same field the real holdings schema does.
    for row in name_rows:
        row["raw_return"] = 0.02

    diag = _scaled_diagnostics(periods, pd.DataFrame(name_rows + sleeve))

    assert diag["risk_on_active_share_mean"] == pytest.approx(0.65)
    assert diag["risk_on_active_share_max"] == pytest.approx(0.8)
    assert diag["risk_on_eligible_share"] == pytest.approx(1.0)
    assert diag["benchmark_sleeve_periods"] == 1
    assert diag["benchmark_sleeve_weight_sum"] == pytest.approx(0.5)
    assert diag["mixed_weights_sum_to_one"] is True
    assert diag["exact_four_finite_unique_selections"] is True


# ---------------------------------------------------------------------------
# Development contract: five windows, hard stop, no 2026H2, authority 954
# ---------------------------------------------------------------------------


def test_spec_declares_five_development_windows_and_954_authority() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    assert spec.market == "cn"
    assert spec.contract.selection_windows == DEVELOPMENT_WINDOWS
    assert spec.raw["authority_issue"] == AUTHORITY_ISSUE == 954
    assert spec.raw["development_runner"] == DEVELOPMENT_RUNNER_ID
    assert spec.raw["research_only"] is True
    assert spec.raw["trade_ready"] is False
    assert spec.raw["automatic_promotion"] is False
    assert spec.raw["rejected_parent_candidate"] == "cn_x1_2_alpha158_three_mechanism"
    assert spec.parent.walk_forward["test_end"] == "2026-06-30"
    assert spec.parent.walk_forward["partial_window_policy"] == "complete_windows_only"
    assert spec.contract.provider_identity_sha256 == (
        "6f17a9eba541159a4cb472721b32758f6bac4892d1a917730fa1b62e9d455980"
    )
    assert spec.contract.cutoff == "2026-06-30"


def test_no_2026h2_fails_closed_on_reserved_holdout() -> None:
    _assert_no_2026h2([], label="empty")
    _assert_no_2026h2(["2024-01-02", "2026-06-30"], label="boundary")
    assert DEVELOPMENT_HARD_STOP == pd.Timestamp("2026-06-30")
    assert RESERVED_HOLDOUT_START == pd.Timestamp("2026-07-01")
    with pytest.raises(ValueError, match="reserved 2026H2 holdout"):
        _assert_no_2026h2(["2026-07-01"], label="holdout start")
    with pytest.raises(ValueError, match="reserved 2026H2 holdout"):
        _assert_no_2026h2(["2026-08-11"], label="provider cutoff")


def test_candidates_carry_frozen_signal_and_expected_policies() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    rules = _candidate_rule_map(spec)
    exposures = _candidate_exposure_map(spec)
    contracts = _candidate_factor_contracts(spec)

    assert rules["baseline_cn_x1_1"] == BASELINE_RULE
    assert rules["cn_x1_2_alpha158_breadth_scaled"] == CHALLENGER_RULE
    assert exposures["baseline_cn_x1_1"] == BASELINE_EXPOSURE_POLICY
    assert exposures["cn_x1_2_alpha158_breadth_scaled"] == CHALLENGER_EXPOSURE_POLICY
    assert len(contracts["baseline_cn_x1_1"]["factor_ids"]) == 14
    assert len(contracts["cn_x1_2_alpha158_breadth_scaled"]["factor_ids"]) == 17
    assert contracts["cn_x1_2_alpha158_breadth_scaled"]["factor_ids"][-3:] == (
        "qlib_alpha158.cntd30",
        "qlib_alpha158.cord5",
        "qlib_alpha158.imin30",
    )


def test_score_artifact_identity_is_independent_of_portfolio_policy() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    contracts = _candidate_factor_contracts(spec)
    candidate = spec.candidates[1]
    factor_contract = contracts[candidate.candidate_id]
    expressions = list(factor_contract["expressions"])
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(expressions)
    }
    window = SimpleNamespace(
        label="2026H1",
        train_start="2021-01-01",
        train_end="2025-12-31",
        test_start="2026-01-01",
        test_end="2026-06-30",
    )
    arguments = {
        "spec": spec,
        "observed_provider": spec.contract.provider_identity_sha256,
        "symbols": [f"{value:06d}" for value in range(1, 131)],
        "benchmark_symbol": "000300",
        "factor_contract": factor_contract,
        "expression_columns": expression_columns,
        "calibration_identity": candidate.calibration.identity_manifest(),
        "window": window,
        "evaluation_dates": pd.date_range("2026-01-05", periods=3, freq="10D"),
    }
    before = _score_artifact_contract(**arguments)
    spec.raw["candidates"][1]["exposure_policy"] = "full_exposure"
    spec.raw["candidates"][1]["regime_rule"] = "breadth_required_one_trend"
    after = _score_artifact_contract(**arguments)

    assert before == after
    assert before["runner"] == SIGNAL_RUNNER_ID
    assert canonical_sha256(before) == canonical_sha256(after)


def test_public_runner_persists_terminal_state_without_training(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_impl(*args, tracker, **kwargs):
        tracker.set_phase("controlled_smoke")
        return {"status": "completed", "decision": "smoke_completed"}

    monkeypatch.setattr(
        scaled_development,
        "_run_breadth_scaled_development_impl",
        fake_impl,
    )
    receipt = scaled_development.run_breadth_scaled_development(
        SPEC,
        output_dir=tmp_path,
    )
    state = yaml.safe_load((tmp_path / "run_state.json").read_text(encoding="utf-8"))

    assert receipt["decision"] == "smoke_completed"
    assert state["status"] == "completed"
    assert state["decision"] == "smoke_completed"
    assert state["total_fit_units"] == 15
    assert state["completed_fit_units"] == 0


def test_candidate_separation_enforced() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    rules = {
        "baseline_cn_x1_1": BASELINE_RULE,
        "cn_x1_2_alpha158_breadth_scaled": CHALLENGER_RULE,
    }
    exposures = {
        "baseline_cn_x1_1": BASELINE_EXPOSURE_POLICY,
        "cn_x1_2_alpha158_breadth_scaled": CHALLENGER_EXPOSURE_POLICY,
    }
    assert (
        _validate_candidate_separation(spec, rules, exposures) == "cn_x1_2_alpha158_breadth_scaled"
    )

    scaled_baseline = {
        "baseline_cn_x1_1": CHALLENGER_EXPOSURE_POLICY,
        "cn_x1_2_alpha158_breadth_scaled": CHALLENGER_EXPOSURE_POLICY,
    }
    with pytest.raises(ValueError, match="baseline.*full_exposure"):
        _validate_candidate_separation(spec, rules, scaled_baseline)

    unscaled_challenger = {
        "baseline_cn_x1_1": BASELINE_EXPOSURE_POLICY,
        "cn_x1_2_alpha158_breadth_scaled": BASELINE_EXPOSURE_POLICY,
    }
    with pytest.raises(ValueError, match="breadth_scaled"):
        _validate_candidate_separation(spec, rules, unscaled_challenger)


def test_exposure_map_rejects_unsupported_policies() -> None:
    spec = load_cross_sectional_experiment_spec(SPEC)
    mutated = spec.raw
    mutated["candidates"][1]["exposure_policy"] = "mystery_policy"
    with pytest.raises(ValueError, match="unsupported exposure policies"):
        _candidate_exposure_map(spec)


# ---------------------------------------------------------------------------
# Issue #954 gates
# ---------------------------------------------------------------------------


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
        "risk_on_active_share_mean": 0.60,
        "risk_on_active_share_max": 0.80,
        "benchmark_sleeve_periods": 3,
        "benchmark_sleeve_weight_sum": 0.9,
        "mixed_weights_sum_to_one": True,
        "exact_four_finite_unique_selections": True,
    }


def test_development_gates_pass_when_all_issue954_conditions_hold() -> None:
    result = _evaluate_development_gates(**_passing_gate_inputs())
    assert result["supported"] is True
    assert all(result["checks"].values())
    assert result["checks"]["active_share_scaling_engaged"] is True
    assert result["checks"]["benchmark_sleeve_present"] is True
    assert result["checks"]["mixed_weights_sum_to_one"] is True
    assert result["checks"]["exact_four_finite_unique_selections"] is True


def test_scaling_engaged_gate_fails_when_no_partial_exposure() -> None:
    inputs = _passing_gate_inputs()
    inputs["risk_on_active_share_mean"] = 1.0  # always full exposure
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["active_share_scaling_engaged"] is False
    assert result["checks"]["active_share_within_unit_bounds"] is True


def test_active_share_unit_bounds_gate_fails_when_exposure_exceeds_full() -> None:
    inputs = _passing_gate_inputs()
    inputs["risk_on_active_share_max"] = 1.5  # impossible under the clamp
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["active_share_within_unit_bounds"] is False


def test_benchmark_sleeve_gate_fails_when_missing() -> None:
    inputs = _passing_gate_inputs()
    inputs["benchmark_sleeve_periods"] = 0
    inputs["benchmark_sleeve_weight_sum"] = 0.0
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["benchmark_sleeve_present"] is False


def test_mixed_weights_sum_gate_fails_when_not_summing_to_one() -> None:
    inputs = _passing_gate_inputs()
    inputs["mixed_weights_sum_to_one"] = False
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["mixed_weights_sum_to_one"] is False


def test_exact_selection_gate_fails_on_short_or_non_finite_selection() -> None:
    inputs = _passing_gate_inputs()
    inputs["exact_four_finite_unique_selections"] = False
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["exact_four_finite_unique_selections"] is False


def test_2026h1_drawdown_worsening_gate_is_enforced() -> None:
    inputs = _passing_gate_inputs()
    inputs["challenger_windows_20"] = _window_frame(
        {"2024H1": 0.02, "2024H2": 0.03, "2025H1": 0.02, "2025H2": 0.03, "2026H1": 0.02},
        drawdown=-0.16,
    )
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["2026h1_drawdown_worsening_within_3pp"] is False


def test_determinism_contract_reaches_the_support_decision() -> None:
    inputs = _passing_gate_inputs()
    inputs["deterministic_portfolio"] = False
    result = _evaluate_development_gates(**inputs)
    assert result["supported"] is False
    assert result["checks"]["exact_portfolio_reproduction"] is False
    assert result["checks"]["exact_score_reproduction"] is True


# ---------------------------------------------------------------------------
# CLI dispatch for the Issue #954 route
# ---------------------------------------------------------------------------


def _write_spec(tmp_path: Path, payload: dict) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return spec


def _runner_stub(key: str, calls: dict):
    def run(spec_path, output_dir, **kwargs):
        calls[key] = (spec_path, output_dir, kwargs)
        return {"status": "completed"}

    return run


def test_954_route_dispatches_breadth_scaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict = {}
    monkeypatch.setattr(
        replay_script,
        "run_breadth_scaled_development",
        _runner_stub("scaled", calls),
    )
    monkeypatch.setattr(
        replay_script,
        "run_exact_cn_ranker_portfolio_replay",
        _runner_stub("exact", calls),
    )
    monkeypatch.setattr(
        replay_script,
        "run_breadth_veto_development",
        _runner_stub("veto", calls),
    )
    spec = _write_spec(tmp_path, {"development_runner": DEVELOPMENT_RUNNER_ID})
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cn_ranker_exact_portfolio_replay", "--spec", str(spec), "--output-dir", str(out)],
    )

    assert replay_script.main() == 0
    assert set(calls) == {"scaled"}
    assert calls["scaled"][2] == {"checkpoint_dir": None, "resume": False}


def test_954_route_forwards_explicit_resume_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}
    monkeypatch.setattr(
        replay_script,
        "run_breadth_scaled_development",
        _runner_stub("scaled", calls),
    )
    spec = _write_spec(tmp_path, {"development_runner": DEVELOPMENT_RUNNER_ID})
    out = tmp_path / "out"
    checkpoints = tmp_path / "shared-scores"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cn_ranker_exact_portfolio_replay",
            "--spec",
            str(spec),
            "--output-dir",
            str(out),
            "--checkpoint-dir",
            str(checkpoints),
            "--resume",
        ],
    )

    assert replay_script.main() == 0
    assert calls["scaled"][2] == {"checkpoint_dir": checkpoints, "resume": True}


def test_954_script_import_keeps_legacy_modules_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    legacy = (
        "src.research.cn_rank_blend_portfolio_replay",
        "src.research.cn_cal_deeper_portfolio_mapping_replay",
    )
    for name in legacy:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.delitem(sys.modules, replay_script.__name__, raising=False)
    reloaded = importlib.import_module(replay_script.__name__)
    for name in legacy:
        assert name not in sys.modules
    assert reloaded is not None
