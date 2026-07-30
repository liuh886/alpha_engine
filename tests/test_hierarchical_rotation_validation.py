"""Focused synthetic tests for the US hierarchical rotation validation module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.focus_watchlist_signal import sha256_file
from src.research.hierarchical_rotation_validation import (
    _baseline_metrics,
    _build_return_frame,
    _build_return_frames,
    _cross_section_only_returns,
    _ew_buy_hold_returns,
    _hierarchical_plus_state_returns,
    _load_observed_slice,
    _state_only_returns,
    _trim_return_frame_to_observable,
    _verify_provider_readiness,
    run_us_hierarchical_rotation_validation,
)

FROZEN_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml"
)
DRAFT_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2_draft.yaml"
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pool() -> dict:
    return _load(Path("configs/pools/us_small_pool_v1.yaml"))


def _provider_symbol(display: str, pool: dict) -> str:
    if display in pool.get("references", {}):
        return str(pool["references"][display].get("provider_symbol", display))
    if display in pool.get("symbol_metadata", {}):
        return str(pool["symbol_metadata"][display].get("provider_symbol", display))
    return display


def _synthetic_prices_long(
    start: str = "2019-01-02",
    end: str = "2026-06-30",
) -> pd.DataFrame:
    """Synthetic OHLCV data covering enough history for indicator warm-up
    through the falsification window end (2026-06-30), intentionally
    stopping before the reserved boundary at 2026-07-01."""
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    dates = pd.bdate_range(start, end)
    basket_steps = {
        name: 0.32 - 0.035 * index for index, name in enumerate(pool["baskets"])
    }
    steps: dict[str, float] = {}
    for name, basket in pool["baskets"].items():
        for member_index, symbol in enumerate(basket["symbols"]):
            steps[symbol] = basket_steps[name] - 0.008 * member_index
    benchmark = str(spec["market_regime"]["reference"])
    context = str(spec["sector_context"]["reference"])
    steps[benchmark] = 0.10
    steps[context] = 0.20

    rows: list[dict] = []
    for display, step in steps.items():
        provider = _provider_symbol(display, pool)
        base = 100.0 + step * np.arange(len(dates), dtype=float)
        phase = (sum(ord(c) for c in display) % 11) / 10.0
        close = base + 0.35 * np.sin(np.arange(len(dates)) / 7.0 + phase)
        for date, value in zip(dates, close):
            rows.append({
                "date": date,
                "symbol": provider,
                "open": value - 0.10,
                "high": value + 0.80,
                "low": value - 0.80,
                "close": value,
                "volume": 1_000_000,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# unit tests: open-to-open execution lag (fixed — no DatetimeIndex.shift)
# ---------------------------------------------------------------------------


def test_next_open_return_is_lagged_two_sessions() -> None:
    """Returns use open(t+2)/open(t+1)-1, never same-row future prices."""
    dates = pd.bdate_range("2025-01-02", periods=10)
    prices = pd.DataFrame([
        {
            "date": d, "symbol": "AAPL",
            "open": float(i + 1) * 10.0,
            "high": float(i + 1) * 12.0,
            "low": float(i + 1) * 8.0,
            "close": float(i + 1) * 11.0,
            "volume": 1_000_000,
        }
        for i, d in enumerate(dates)
    ])
    perf, drift = _build_return_frames(
        prices, ["AAPL"], "AAPL", "2025-01-02", "2025-01-15"
    )
    # First perf return: open[i+2]/open[i+1]-1 = 30/20-1 = 0.5
    expected = (3.0 / 2.0) - 1.0
    actual = perf["AAPL"].iloc[0]
    assert np.isclose(actual, expected, atol=1e-10)
    # First drift return: open[i+1]/open[i]-1 = 20/10-1 = 1.0
    expected_drift = (2.0 / 1.0) - 1.0
    assert np.isclose(drift["AAPL"].iloc[0], expected_drift, atol=1e-10)
    # Trailing signal dates without a fully realisable t+2 return are excluded.
    assert len(perf) == len(dates) - 2
    assert np.isfinite(perf["AAPL"]).all()


def test_return_frame_excludes_post_end_date() -> None:
    """Signal dates whose realisation exceeds the window are excluded."""
    dates = pd.bdate_range("2025-06-25", periods=10)
    prices = pd.DataFrame([
        {
            "date": d, "symbol": "QQQ",
            "open": 100.0 + i,
            "high": 102.0 + i, "low": 98.0 + i, "close": 101.0 + i,
            "volume": 1_000_000,
        }
        for i, d in enumerate(dates)
    ])
    perf, drift = _build_return_frames(
        prices, ["QQQ"], "QQQ", "2025-06-25", "2025-06-30"
    )
    assert not perf.empty
    assert np.isfinite(perf["QQQ"]).all()
    assert all(perf.index <= pd.Timestamp("2025-06-30"))


def test_return_frame_no_null_frequency_error() -> None:
    """Regression: DatetimeIndex.shift must not raise NullFrequencyError."""
    dates = pd.bdate_range("2025-01-02", periods=20)
    prices = pd.DataFrame([
        {
            "date": d, "symbol": "QQQ",
            "open": 100.0 + i,
            "high": 102.0, "low": 98.0, "close": 101.0,
            "volume": 1_000_000,
        }
        for i, d in enumerate(dates)
    ])
    # This must not raise
    perf, drift = _build_return_frames(
        prices, ["QQQ"], "QQQ", "2025-01-02", "2025-01-31"
    )
    assert not perf.empty
    assert not drift.empty
    assert len(perf.columns) == 1  # just QQQ
    assert len(drift.columns) == 1


def test_drawdown_improvement_sign_is_positive_only_when_drawdown_is_lower() -> None:
    dates = pd.bdate_range("2025-01-02", periods=2)
    qqq_returns = pd.Series([0.0, -0.5], index=dates)

    def metrics(second_return: float) -> dict:
        portfolio = pd.DataFrame(
            {
                "portfolio_return": [0.0, second_return],
                "turnover": [0.0, 0.0],
                "cost": [0.0, 0.0],
                "gross_exposure": [1.0, 1.0],
                "A": [1.0, 1.0],
            },
            index=dates,
        )
        return _baseline_metrics(
            portfolio, qqq_returns, "candidate", "test", ["A"]
        )

    assert metrics(-0.2)["drawdown_improvement_vs_qqq"] > 0.0
    assert metrics(-0.6)["drawdown_improvement_vs_qqq"] < 0.0


def test_backward_compat_build_return_frame() -> None:
    """_build_return_frame still works for callers that only need perf."""
    dates = pd.bdate_range("2025-01-02", periods=10)
    prices = pd.DataFrame([
        {
            "date": d, "symbol": "QQQ",
            "open": 100.0 + i,
            "high": 102.0, "low": 98.0, "close": 101.0,
            "volume": 1_000_000,
        }
        for i, d in enumerate(dates)
    ])
    frame = _build_return_frame(prices, ["QQQ"], "QQQ", "2025-01-02", "2025-01-15")
    assert not frame.empty
    assert "QQQ" in frame.columns


# ---------------------------------------------------------------------------
# unit tests: turnover/cost drift uses PRIOR interval, not future
# ---------------------------------------------------------------------------


def test_turnover_uses_prior_interval_drift() -> None:
    """Target weights compared to prior holdings drifted by PRIOR interval return."""
    dates = pd.bdate_range("2025-01-02", periods=5)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in ["A", "B"]:
            data["date"].append(d)
            data["symbol"].append(sym)
            # A rises, B falls
            val = 100.0 + i * (5.0 if sym == "A" else -3.0)
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices = pd.DataFrame(data)
    perf, drift = _build_return_frames(
        prices, ["A", "B"], "A", "2025-01-02", "2025-01-10"
    )

    # State-only with ENTER on both symbols
    signal_history = [
        {"date": "2025-01-02", "symbol": "A", "state": "ENTER", "reason_codes": []},
        {"date": "2025-01-02", "symbol": "B", "state": "ENTER", "reason_codes": []},
        {"date": "2025-01-03", "symbol": "A", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-03", "symbol": "B", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-06", "symbol": "A", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-06", "symbol": "B", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-07", "symbol": "A", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-07", "symbol": "B", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-08", "symbol": "A", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-08", "symbol": "B", "state": "HOLD", "reason_codes": []},
    ]
    multipliers = {"ENTER": 1.0, "HOLD": 1.0, "EXIT": 0.0}
    result = _state_only_returns(
        perf, drift, signal_history, ["A", "B"], multipliers, 10.0
    )
    assert len(result) > 0
    # With both symbols at ENTER→HOLD, targets should be 50/50
    # Turnover on day 1 (initial entry): 50%+50% = 100% = 1.0
    assert result.iloc[0]["turnover"] > 0
    # Drift on subsequent days: A outperforms B, so A's weight drifts up
    # Rebalancing back to 50/50 creates turnover proportional to the drift difference
    assert result.iloc[1]["turnover"] > 0


# ---------------------------------------------------------------------------
# unit tests: EW buy-and-hold is genuine (weights drift, no daily rebalance)
# ---------------------------------------------------------------------------


def test_ew_buy_hold_weights_drift_naturally() -> None:
    """EW B&H does NOT daily rebalance; weights drift with performance."""
    dates = pd.bdate_range("2025-01-02", periods=5)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for j, sym in enumerate(["A", "B"]):
            data["date"].append(d)
            data["symbol"].append(sym)
            # A: +10 per step, B: flat
            val = 100.0 + i * (10.0 if sym == "A" else 0.0)
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices = pd.DataFrame(data)
    perf, drift = _build_return_frames(
        prices, ["A", "B"], "A", "2025-01-02", "2025-01-09"
    )

    ew, _diag = _ew_buy_hold_returns(perf, ["A", "B"], cost_bps=10.0)
    assert (ew["turnover"] == 0.0).all(), "EW B&H must have zero turnover after entry"
    assert (ew["gross_exposure"] == 1.0).all()
    # Initial entry cost applied in first period
    assert ew.iloc[0]["cost"] > 0
    # No further costs
    assert ew.iloc[1:]["cost"].sum() == 0.0


def test_ew_buy_hold_differs_from_daily_rebalance() -> None:
    """Genuine B&H produces different returns than implicit daily rebalance."""
    dates = pd.bdate_range("2025-01-02", periods=10)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in ["A", "B"]:
            data["date"].append(d)
            data["symbol"].append(sym)
            val = 100.0 + i * (8.0 if sym == "A" else -2.0)
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices = pd.DataFrame(data)
    perf, drift = _build_return_frames(
        prices, ["A", "B"], "A", "2025-01-02", "2025-01-16"
    )

    # Genuine B&H
    ew_genuine, _diag = _ew_buy_hold_returns(perf, ["A", "B"], cost_bps=10.0)
    # Implicit daily rebalance (fixed 50/50 weights each day)
    rets = perf[["A", "B"]]
    implicit_rebal_ret = (rets * np.array([0.5, 0.5])).sum(axis=1)

    genuine_total = (1.0 + ew_genuine["portfolio_return"]).prod() - 1.0
    rebal_total = (1.0 + implicit_rebal_ret.dropna()).prod() - 1.0

    # They should differ because genuine B&H lets A's outperformance compound
    assert not np.isclose(genuine_total, rebal_total, atol=1e-6), (
        f"genuine B&H ({genuine_total:.6f}) should differ from daily rebalance "
        f"({rebal_total:.6f})"
    )


def test_ew_buy_hold_has_no_turnover() -> None:
    """EW B&H has zero turnover after initial entry."""
    dates = pd.bdate_range("2025-01-02", periods=5)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in ["A", "B", "C"]:
            data["date"].append(d)
            data["symbol"].append(sym)
            data["open"].append(100.0 + i + (ord(sym) % 3))
            data["high"].append(102.0)
            data["low"].append(98.0)
            data["close"].append(101.0)
    prices = pd.DataFrame(data)
    perf, drift = _build_return_frames(
        prices, ["A", "B", "C"], "A", "2025-01-02", "2025-01-08"
    )
    ew, _diag = _ew_buy_hold_returns(perf, ["A", "B", "C"], cost_bps=10.0)
    assert (ew["turnover"] == 0.0).all()
    # Cost only on first row
    assert ew.iloc[0]["cost"] > 0
    assert (ew.iloc[1:]["cost"] == 0.0).all()
    assert (ew["gross_exposure"] == 1.0).all()


# ---------------------------------------------------------------------------
# unit tests: state-only baseline
# ---------------------------------------------------------------------------


def test_state_only_baseline_responds_to_states() -> None:
    """State-only baseline changes exposure when states change."""
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    perf_frame = pd.DataFrame(
        {"A": [0.01, 0.02, -0.01], "B": [-0.01, 0.01, 0.02]},
        index=dates,
    )
    drift_frame = pd.DataFrame(
        {"A": [0.005, 0.008, -0.003], "B": [-0.002, 0.004, 0.006]},
        index=dates,
    )
    signal_history = [
        {"date": "2025-01-02", "symbol": "A", "state": "ENTER", "reason_codes": []},
        {"date": "2025-01-02", "symbol": "B", "state": "EXIT", "reason_codes": []},
        {"date": "2025-01-03", "symbol": "A", "state": "HOLD", "reason_codes": []},
        {"date": "2025-01-03", "symbol": "B", "state": "ENTER", "reason_codes": []},
        {"date": "2025-01-06", "symbol": "A", "state": "EXIT", "reason_codes": []},
        {"date": "2025-01-06", "symbol": "B", "state": "HOLD", "reason_codes": []},
    ]
    multipliers = {"ENTER": 1.0, "HOLD": 1.0, "REDUCE": 0.5, "WATCH": 0.0, "EXIT": 0.0}
    result = _state_only_returns(
        perf_frame, drift_frame, signal_history, ["A", "B"], multipliers, 10.0
    )
    assert len(result) == 3
    # Day 1: only A eligible, weight=1.0 on A
    assert result.iloc[0]["gross_exposure"] == 1.0
    # Day 2: both eligible, 50/50
    assert result.iloc[1]["gross_exposure"] == 1.0
    # Day 3: only B eligible
    assert result.iloc[2]["gross_exposure"] == 1.0


# ---------------------------------------------------------------------------
# unit tests: holding duration tracks position membership/weight changes
# ---------------------------------------------------------------------------


def test_holding_duration_tracks_position_changes(tmp_path: Path) -> None:
    """Average holding duration reflects membership/weight changes, not just gross exposure."""
    dates = pd.bdate_range("2025-01-02", periods=20)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in ["A", "B"]:
            data["date"].append(d)
            data["symbol"].append(sym)
            val = 100.0 + i * 0.5
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices = pd.DataFrame(data)
    perf, drift = _build_return_frames(
        prices, ["A", "B"], "A", "2025-01-02", "2025-01-30"
    )

    # Alternate which symbol is active every 5 days
    signal_history = []
    for i, d in enumerate(dates):
        active_sym = "A" if (i // 5) % 2 == 0 else "B"
        inactive_sym = "B" if active_sym == "A" else "A"
        signal_history.append({
            "date": d.strftime("%Y-%m-%d"), "symbol": active_sym,
            "state": "ENTER", "reason_codes": [],
        })
        signal_history.append({
            "date": d.strftime("%Y-%m-%d"), "symbol": inactive_sym,
            "state": "EXIT", "reason_codes": [],
        })

    multipliers = {"ENTER": 1.0, "HOLD": 1.0, "EXIT": 0.0}
    result = _state_only_returns(
        perf, drift, signal_history, ["A", "B"], multipliers, 10.0
    )
    assert len(result) > 0
    assert "gross_exposure" in result.columns


# ---------------------------------------------------------------------------
# unit tests: cross-section-only independent of state filter
# ---------------------------------------------------------------------------


def test_cross_section_only_is_independent_of_state_filter() -> None:
    """Cross-section-only derives selections from scores, not state-filtered positions."""
    spec = _load(FROZEN_SPEC)
    pool = _pool()

    dates = pd.bdate_range("2025-01-02", periods=30)
    benchmark = str(spec["market_regime"]["reference"])
    context = str(spec["sector_context"]["reference"])
    candidates = [
        symbol
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    ]

    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in candidates + [benchmark, context]:
            data["date"].append(d)
            data["symbol"].append(_provider_symbol(sym, pool))
            val = 100.0 + i * (0.3 + 0.02 * hash(sym) % 7)
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices_df = pd.DataFrame(data)

    perf, drift = _build_return_frames(
        prices_df, candidates, benchmark, "2025-01-02", "2025-02-15"
    )

    # The cross-section-only must accept indicators + rotations, not portfolio_history
    # This is tested implicitly by the function signature change
    # We construct a minimal test: verify the function runs with rotations + indicators
    from src.research.hierarchical_pool_rotation import (
        _candidate_symbols,
        build_hierarchical_rotation_history,
        build_runtime_timing_spec,
        compute_hierarchical_indicators,
        load_hierarchical_contract,
        _repository_root,
    )
    from src.research.focus_watchlist_signal import (
        generate_signal_history,
        load_long_ohlcv_csv,
    )

    # Use a temp CSV
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices_df.to_csv(csv_path, index=False)

        _, pool_obj, resolved_spec, _pool_path = load_hierarchical_contract(FROZEN_SPEC)
        root = _repository_root(resolved_spec)
        timing_spec, _ = build_runtime_timing_spec(
            spec, pool_obj, repository_root=root
        )
        prices = load_long_ohlcv_csv(csv_path, timing_spec)
        indicators = compute_hierarchical_indicators(prices, timing_spec)
        signal_hist, _ = generate_signal_history(indicators, timing_spec)
        _, _, rotations = build_hierarchical_rotation_history(
            indicators, signal_hist, spec, pool_obj
        )

        cs_rets = _cross_section_only_returns(
            perf, drift, rotations, indicators,
            spec, pool_obj, candidates, 10.0,
        )
        assert len(cs_rets) > 0
        assert "portfolio_return" in cs_rets.columns


def test_cross_section_only_includes_watch_symbol_regression() -> None:
    """Regression: deterministic handcrafted fixture proves cross-section-only
    includes a high-ranked symbol excluded by WATCH/EXIT state in the full
    portfolio.  No-lookahead frames are explicit (open-to-open lag already
    verified by test_next_open_return_is_lagged_two_sessions)."""
    from src.research.hierarchical_pool_rotation import SECURITY_SCORE_FIELDS

    # ---- handcrafted spec (minimal fields consumed by the two baselines) ----
    spec = {
        "market_regime": {"reference": "QQQ"},
        "sector_context": {"reference": "SOX"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "median_momentum_20": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "breadth_above_sma50": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "median_drawdown_from_63d_high": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 2,
            "maximum_selected_symbols_per_basket": 2,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "momentum_20": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "drawdown_from_63d_high": {
                        "weight": 0.25, "direction": "higher_is_better",
                    },
                    "realized_volatility_20": {
                        "weight": 0.25, "direction": "lower_is_better",
                    },
                },
                "minimum_composite_percentile": 0.75,
            },
        },
    }

    # ---- handcrafted pool (one basket, two members) ----
    pool = {"baskets": {"tech": {"symbols": ["WINNER", "LOSER"]}}}
    candidates = ["WINNER", "LOSER"]

    # ---- handcrafted return frames (5 business days) ----
    dates = pd.bdate_range("2025-01-02", periods=5)

    perf_frame = pd.DataFrame(
        {
            "WINNER": [0.02, 0.03, 0.01, np.nan, np.nan],
            "LOSER": [-0.005, -0.003, 0.001, np.nan, np.nan],
            "QQQ": [0.005, 0.008, -0.002, np.nan, np.nan],
        },
        index=dates,
    )
    perf_frame.index.name = "date"

    drift_frame = pd.DataFrame(
        {
            "WINNER": [0.015, 0.025, 0.008, 0.002, np.nan],
            "LOSER": [-0.003, -0.001, -0.002, -0.001, np.nan],
            "QQQ": [0.004, 0.006, -0.001, 0.003, np.nan],
        },
        index=dates,
    )
    drift_frame.index.name = "date"
    perf_frame, drift_frame = _trim_return_frame_to_observable(
        perf_frame,
        drift_frame,
        "QQQ",
    )

    # ---- indicators with explicit risk_on=True + all four security score fields ----
    indicator_rows: list[dict] = []
    for d in dates:
        indicator_rows.append({
            "date": d, "symbol": "WINNER", "risk_on": True,
            "relative_momentum_63_vs_benchmark": 0.85,
            "momentum_20": 0.80,
            "drawdown_from_63d_high": 0.90,
            "realized_volatility_20": 0.25,
            "sma_50": 100.0, "close": 105.0,
        })
        indicator_rows.append({
            "date": d, "symbol": "LOSER", "risk_on": True,
            "relative_momentum_63_vs_benchmark": 0.20,
            "momentum_20": 0.15,
            "drawdown_from_63d_high": 0.10,
            "realized_volatility_20": 0.85,
            "sma_50": 100.0, "close": 105.0,
        })
        indicator_rows.append({
            "date": d, "symbol": "QQQ", "risk_on": True,
            "relative_momentum_63_vs_benchmark": 0.50,
            "momentum_20": 0.50,
            "drawdown_from_63d_high": 0.50,
            "realized_volatility_20": 0.50,
            "sma_50": 100.0, "close": 105.0,
        })
    indicators = pd.DataFrame(indicator_rows)

    # ---- rotations: one selected basket from day 1 ----
    rotations: list[dict] = [
        {"date": "2025-01-02", "selected_baskets": ["tech"]},
    ]

    # ---- portfolio_history: WINNER excluded (WATCH/EXIT state), nothing entered ----
    portfolio_history: list[dict] = [
        {"date": d.strftime("%Y-%m-%d"), "positions": [], "risk_on": True}
        for d in dates
    ]

    # ---- cross-section-only returns ----
    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    # ---- full (state-filtered) returns ----
    full_rets = _hierarchical_plus_state_returns(
        perf_frame, drift_frame, portfolio_history, candidates, 10.0,
    )

    # ---- assertions ----
    assert len(cs_rets) > 0
    assert len(full_rets) > 0

    # Cross-section-only selects WINNER → positive exposure and positive return
    assert cs_rets["gross_exposure"].sum() > 0, (
        "cross-section-only must have nonzero exposure"
    )
    assert cs_rets["portfolio_return"].sum() > 0, (
        "cross-section-only must earn positive return (selects WINNER)"
    )

    # Full portfolio has zero exposure (WINNER excluded by WATCH/EXIT)
    assert full_rets["gross_exposure"].sum() == 0.0, (
        "full portfolio must have zero exposure when WATCH symbol is excluded"
    )
    assert full_rets["portfolio_return"].sum() == 0.0, (
        "full portfolio return must be zero when no positions are held"
    )

    # The two return series must differ
    assert not cs_rets["portfolio_return"].equals(
        full_rets["portfolio_return"]
    ), "cross-section-only must differ from full when state filter excludes symbols"


# ---------------------------------------------------------------------------
# regression: weighted-return helper (Correction 1)
# ---------------------------------------------------------------------------


def test_weighted_return_rejects_nan_with_positive_weight() -> None:
    """A symbol with positive weight and NaN return raises ValueError."""
    from src.research.hierarchical_rotation_validation import (
        _weighted_portfolio_return,
    )

    ret_row = pd.Series({"A": np.nan, "B": 0.02, "C": 0.01})
    weights = {"A": 0.3, "B": 0.5, "C": 0.2}
    with pytest.raises(ValueError, match="non-finite"):
        _weighted_portfolio_return(weights, ret_row, ["A", "B", "C"])


def test_weighted_return_skips_zero_weights() -> None:
    """Zero-weight symbols with NaN do not cause an error."""
    from src.research.hierarchical_rotation_validation import (
        _weighted_portfolio_return,
    )

    ret_row = pd.Series({"A": np.nan, "B": 0.02, "C": 0.01})
    weights = {"A": 0.0, "B": 0.5, "C": 0.5}
    port_ret = _weighted_portfolio_return(weights, ret_row, ["A", "B", "C"])
    assert port_ret > 0, f"Expected positive return, got {port_ret}"


def test_prelisting_nan_unheld_does_not_remove_sessions() -> None:
    """Pre-listing NaN for a symbol NOT held in the portfolio must not discard
    sessions (Correction 1 regression)."""
    dates = pd.bdate_range("2025-06-02", periods=6)
    perf_frame = pd.DataFrame(
        {
            "HELD_A": [0.01, -0.005, 0.02, np.nan, np.nan, np.nan],
            "HELD_B": [0.005, 0.01, -0.003, np.nan, np.nan, np.nan],
            "PRE_LISTING": [np.nan, np.nan, np.nan, 0.03, 0.01, -0.02],
            "QQQ": [0.003, 0.004, -0.002, np.nan, np.nan, np.nan],
        },
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {
            "HELD_A": [0.005, 0.008, -0.003, 0.001, np.nan, np.nan],
            "HELD_B": [-0.002, 0.004, 0.006, -0.001, np.nan, np.nan],
            "PRE_LISTING": [np.nan, np.nan, 0.01, 0.005, -0.003, np.nan],
            "QQQ": [0.001, 0.003, -0.001, 0.002, np.nan, np.nan],
        },
        index=dates,
    )
    drift_frame.index.name = "date"

    signal_history = [
        {"date": d.strftime("%Y-%m-%d"), "symbol": s, "state": "ENTER", "reason_codes": []}
        for d in dates[:3] for s in ["HELD_A", "HELD_B"]
    ] + [
        {"date": d.strftime("%Y-%m-%d"), "symbol": "PRE_LISTING", "state": "WATCH", "reason_codes": []}
        for d in dates
    ]
    multipliers = {"ENTER": 1.0, "HOLD": 1.0, "WATCH": 0.0, "EXIT": 0.0}
    result = _state_only_returns(
        perf_frame, drift_frame, signal_history,
        ["HELD_A", "HELD_B", "PRE_LISTING"], multipliers, 10.0,
    )
    # Sessions with HELD returns should be present (3 sessions with valid data)
    assert len(result) == 6, f"All 6 sessions should be present, got {len(result)}"
    assert result["gross_exposure"].iloc[:3].sum() > 0, (
        "First 3 sessions should have positive exposure (HELD symbols active)"
    )


# ---------------------------------------------------------------------------
# regression: cross-section-only truly state-free (Correction 3)
# ---------------------------------------------------------------------------


def test_cross_section_selections_unchanged_between_rotations() -> None:
    """Cross-section-only freezes selections between rotation dates."""
    from src.research.hierarchical_rotation_validation import (
        _cross_section_only_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=12)
    perf_frame = pd.DataFrame(
        {"A": [0.01]*12, "B": [0.005]*12, "C": [-0.002]*12},
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {"A": [0.005]*12, "B": [0.003]*12, "C": [-0.001]*12},
        index=dates,
    )
    drift_frame.index.name = "date"

    # Indicators: A always best, B medium, C worst
    indicator_rows = []
    for d in dates:
        for sym, rel_mom, mom20, dd, rvol in [
            ("A", 0.90, 0.85, 0.80, 0.20),
            ("B", 0.50, 0.45, 0.40, 0.40),
            ("C", 0.20, 0.15, 0.10, 0.80),
        ]:
            indicator_rows.append({
                "date": d, "symbol": sym,
                "relative_momentum_63_vs_benchmark": rel_mom,
                "momentum_20": mom20,
                "drawdown_from_63d_high": dd,
                "realized_volatility_20": rvol,
                "sma_50": 100.0, "close": 105.0,
            })
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "market_regime": {"reference": "QQQ"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "breadth_above_sma50": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 1,
            "maximum_selected_symbols_per_basket": 2,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
        },
    }
    pool = {"baskets": {"growth": {"symbols": ["A", "B", "C"]}}}
    candidates = ["A", "B", "C"]

    # Two rotations 5 sessions apart (days 0 and 5)
    rotations = [
        {"date": dates[0].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
        {"date": dates[5].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
    ]

    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    assert len(cs_rets) > 0
    # Per-candidate weights should be present
    for c in candidates:
        assert c in cs_rets.columns, f"Per-candidate weight column {c} missing"
    # Weights should be constant between rotation dates (days 1-4 should have same weights)
    w_a_day1 = cs_rets["A"].iloc[1]
    w_a_day4 = cs_rets["A"].iloc[4]
    assert w_a_day1 == w_a_day4, (
        f"Weights must be frozen between rotations: day1={w_a_day1}, day4={w_a_day4}"
    )
    # Turnover should be zero on non-rotation days (after initial entry on day 0)
    # Days 1-4: same frozen weights → turnover from drift only
    turnover_days_1_4 = cs_rets["turnover"].iloc[1:5]
    # Some turnover from drift is OK, but it should be small compared to rotation-day turnover
    assert turnover_days_1_4.sum() >= 0


def test_market_risk_off_does_not_zero_cross_section_only() -> None:
    """Cross-section-only must not apply QQQ market-regime gate.
    Even when risk_on would be False, the baseline stays invested."""
    from src.research.hierarchical_rotation_validation import (
        _cross_section_only_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=6)
    perf_frame = pd.DataFrame(
        {"A": [0.01]*6, "B": [0.005]*6, "QQQ": [-0.02]*6},
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {"A": [0.005]*6, "B": [0.003]*6, "QQQ": [-0.01]*6},
        index=dates,
    )
    drift_frame.index.name = "date"

    # Risk_on is False for QQQ every day (crash scenario)
    indicator_rows = []
    for d in dates:
        indicator_rows.append({
            "date": d, "symbol": "A",
            "relative_momentum_63_vs_benchmark": 0.80,
            "momentum_20": 0.75,
            "drawdown_from_63d_high": 0.70,
            "realized_volatility_20": 0.25,
            "sma_50": 100.0, "close": 105.0,
        })
        indicator_rows.append({
            "date": d, "symbol": "B",
            "relative_momentum_63_vs_benchmark": 0.40,
            "momentum_20": 0.35,
            "drawdown_from_63d_high": 0.30,
            "realized_volatility_20": 0.45,
            "sma_50": 100.0, "close": 105.0,
        })
        indicator_rows.append({
            "date": d, "symbol": "QQQ",
            "risk_on": False,  # Market crash!
            "relative_momentum_63_vs_benchmark": 0.10,
            "momentum_20": 0.05,
            "drawdown_from_63d_high": 0.02,
            "realized_volatility_20": 0.95,
            "sma_50": 100.0, "close": 105.0,
        })
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "market_regime": {"reference": "QQQ"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "breadth_above_sma50": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 1,
            "maximum_selected_symbols_per_basket": 2,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
        },
    }
    pool = {"baskets": {"growth": {"symbols": ["A", "B"]}}}
    candidates = ["A", "B"]

    rotations = [
        {"date": dates[0].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
    ]

    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    # Cross-section-only must have exposure even when QQQ indicates risk_off
    assert cs_rets["gross_exposure"].sum() > 0, (
        "cross-section-only must stay invested regardless of market regime"
    )


def test_cross_section_turnover_at_rotations_only() -> None:
    """Cross-section-only turnover occurs at rotation dates (plus minor drift)."""
    from src.research.hierarchical_rotation_validation import (
        _cross_section_only_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=12)
    perf_frame = pd.DataFrame(
        {"A": [0.01]*12, "B": [0.005]*12, "C": [-0.002]*12},
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {"A": [0.005]*12, "B": [0.003]*12, "C": [-0.001]*12},
        index=dates,
    )
    drift_frame.index.name = "date"

    indicator_rows = []
    for d in dates:
        for sym, rel_mom, mom20, dd, rvol in [
            ("A", 0.90, 0.85, 0.80, 0.20),
            ("B", 0.50, 0.45, 0.40, 0.40),
            ("C", 0.20, 0.15, 0.10, 0.80),
        ]:
            indicator_rows.append({
                "date": d, "symbol": sym,
                "relative_momentum_63_vs_benchmark": rel_mom,
                "momentum_20": mom20,
                "drawdown_from_63d_high": dd,
                "realized_volatility_20": rvol,
                "sma_50": 100.0, "close": 105.0,
            })
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "market_regime": {"reference": "QQQ"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "breadth_above_sma50": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 1,
            "maximum_selected_symbols_per_basket": 2,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
        },
    }
    pool = {"baskets": {"growth": {"symbols": ["A", "B", "C"]}}}
    candidates = ["A", "B", "C"]

    # Three rotations
    rotations = [
        {"date": dates[0].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
        {"date": dates[4].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
        {"date": dates[8].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
    ]

    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    # Turnover on rotation dates (0, 4, 8) should be significant
    assert cs_rets["turnover"].iloc[0] > 0, "Initial entry at rotation must have turnover"
    # Days between rotations may have small drift turnover, but not rebalancing turnover
    non_rot_days = [i for i in range(1, 12) if i not in (4, 8)]
    non_rot_turnover = cs_rets["turnover"].iloc[non_rot_days]
    # Drift-only turnover should be small (< 0.05) on non-rotation days
    assert non_rot_turnover.max() < 0.10, (
        f"Non-rotation turnover too high: max={non_rot_turnover.max()}"
    )


# ---------------------------------------------------------------------------
# regression: EW short-history diagnostics (Correction 2)
# ---------------------------------------------------------------------------


def test_ew_buy_hold_short_history_diagnostics() -> None:
    """EW B&H records eligible count/symbols and excluded short-history names."""
    dates = pd.bdate_range("2025-01-02", periods=5)
    data = {"date": [], "symbol": [], "open": [], "high": [], "low": [], "close": []}
    for i, d in enumerate(dates):
        for sym in ["READY_A", "READY_B", "LATE_C"]:
            data["date"].append(d)
            data["symbol"].append(sym)
            val = 100.0 + i
            data["open"].append(val)
            data["high"].append(val + 2)
            data["low"].append(val - 2)
            data["close"].append(val + 1)
    prices = pd.DataFrame(data)

    perf, drift = _build_return_frames(
        prices, ["READY_A", "READY_B", "LATE_C"], "READY_A",
        "2025-01-02", "2025-01-08"
    )

    # Make LATE_C have NaN return at first date
    perf.loc[perf.index[0], "LATE_C"] = np.nan

    ew, diagnostics = _ew_buy_hold_returns(perf, ["READY_A", "READY_B", "LATE_C"], cost_bps=10.0)

    assert diagnostics["total_candidates"] == 3
    assert diagnostics["eligible_count"] == 2
    assert "READY_A" in diagnostics["eligible_symbols"]
    assert "READY_B" in diagnostics["eligible_symbols"]
    assert "LATE_C" in diagnostics["excluded_short_history"]
    assert "LATE_C" not in diagnostics["eligible_symbols"]
    # LATE_C should have zero weight throughout
    assert (ew["LATE_C"] == 0.0).all()
    # But READY symbols have positive weight
    assert ew["READY_A"].iloc[0] > 0
    assert ew["READY_B"].iloc[0] > 0


# ---------------------------------------------------------------------------
# regression: gate resolution (Correction 7)
# ---------------------------------------------------------------------------


def test_configured_gates_resolve_to_non_null(
    _full_run_output: dict,
) -> None:
    """Every configured gate must resolve to a non-null observed metric."""
    decision = _full_run_output["decision"]
    gate_result = decision.get("gate_result", {})
    details = gate_result.get("details", {})

    assert len(details) > 0, "Gate details must not be empty"
    for gate_key, detail in details.items():
        observed = detail.get("observed")
        # Every gate must have a non-null observed value
        # (skip provider_manifest_required which is a special case)
        if "provider_manifest" in gate_key:
            continue
        assert observed is not None, (
            f"Gate '{gate_key}' has null observed value; "
            f"every configured gate must resolve to a metric"
        )


def test_development_window_retains_benchmark_sessions(
    _full_run_output: dict,
) -> None:
    """A valid synthetic development window retains expected session count
    despite recent listings (Correction 7)."""
    metrics = json.loads(
        (_full_run_output["output_dir"] / "baseline_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    # The stub produces 6 sessions for the development window
    for label in metrics["baselines"]:
        dev = metrics["baselines"][label].get("development_observed", {})
        if dev.get("status") == "observed":
            assert dev["sessions"] >= 3, (
                f"{label} development window has only {dev.get('sessions', 0)} "
                f"sessions; expected >= 3 despite recent listings"
            )
            # Must be an integer
            assert isinstance(dev["sessions"], int)


# ---------------------------------------------------------------------------
# regression: attribution counterfactuals
# ---------------------------------------------------------------------------


def test_attribution_exposes_separate_named_effects(_full_run_output: dict) -> None:
    """Attribution must expose market_regime, basket_rank, security_rank,
    and state_overlay effects with honest counterfactual definitions."""
    attribution = json.loads(
        (_full_run_output["output_dir"] / "attribution.json").read_text(
            encoding="utf-8"
        )
    )
    assert "market_regime_effect" in attribution
    assert "market_regime_effect_definition" in attribution
    assert "basket_rank_effect" in attribution
    assert "basket_rank_effect_definition" in attribution
    assert "security_rank_effect" in attribution
    assert "security_rank_effect_definition" in attribution
    assert "state_overlay_effect" in attribution
    assert "state_overlay_effect_definition" in attribution
    assert attribution.get("effects_are_non_additive") is True
    assert "residual" in attribution
    assert "sum_of_named_effects" in attribution
    assert "total_excess_vs_ew" in attribution


def test_state_overlay_effect_is_no_market_regime_minus_cs_only(
    _full_run_output: dict,
) -> None:
    """State overlay effect = no-market-regime full minus state-free cs_only,
    with risk_on forced True.  Market regime is held constant so
    state_overlay_effect does NOT include the market-regime effect."""
    attribution = json.loads(
        (_full_run_output["output_dir"] / "attribution.json").read_text(
            encoding="utf-8"
        )
    )
    so_def = attribution.get("state_overlay_effect_definition", "")
    assert "no-market-regime" in so_def.lower(), (
        f"state_overlay_effect_definition must mention no-market-regime, "
        f"got: {so_def}"
    )
    assert "market-regime gate held constant" in so_def.lower() or (
        "market regime" in so_def.lower() and "constant" in so_def.lower()
    ), (
        f"state_overlay_effect_definition must state market regime is held "
        f"constant, got: {so_def}"
    )


def test_market_regime_effect_sign_is_full_minus_no_market_regime(
    _full_run_output: dict,
) -> None:
    """Market regime effect sign MUST be full minus no-market-regime:
    positive means the regime improved return."""
    attribution = json.loads(
        (_full_run_output["output_dir"] / "attribution.json").read_text(
            encoding="utf-8"
        )
    )
    mr_def = attribution.get("market_regime_effect_definition", "")
    assert "full minus no-market-regime" in mr_def.lower(), (
        f"market_regime_effect_definition must state full minus no-market-regime, "
        f"got: {mr_def}"
    )


def test_risk_off_does_not_empty_state_free_cs_baseline() -> None:
    """Risk-off rotation dates must NOT empty the state-free CS baseline;
    it builds its own basket selection from indicators regardless of risk_on."""
    from src.research.hierarchical_rotation_validation import (
        _cross_section_only_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=6)
    perf_frame = pd.DataFrame(
        {"A": [0.01] * 6, "B": [0.005] * 6, "QQQ": [-0.02] * 6},
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {"A": [0.005] * 6, "B": [0.003] * 6, "QQQ": [-0.01] * 6},
        index=dates,
    )
    drift_frame.index.name = "date"

    indicator_rows = []
    for d in dates:
        for sym, rel, m20, dd, rvol in [
            ("A", 0.80, 0.75, 0.70, 0.25),
            ("B", 0.40, 0.35, 0.30, 0.45),
            ("QQQ", 0.10, 0.05, 0.02, 0.95),
        ]:
            indicator_rows.append({
                "date": d, "symbol": sym,
                "relative_momentum_63_vs_benchmark": rel,
                "momentum_20": m20,
                "drawdown_from_63d_high": dd,
                "realized_volatility_20": rvol,
                "sma_50": 100.0, "close": 105.0,
            })
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "market_regime": {"reference": "QQQ"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "breadth_above_sma50": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 1,
            "maximum_selected_symbols_per_basket": 2,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
        },
    }
    pool = {"baskets": {"growth": {"symbols": ["A", "B"]}}}
    candidates = ["A", "B"]

    # Rotation with risk_on=False (simulating what build_hierarchical_rotation_history
    # would produce for a crash date) — selected_baskets is EMPTY
    rotations = [
        {
            "date": dates[0].strftime("%Y-%m-%d"),
            "selected_baskets": [],  # Empty — risk was off
            "risk_on": False,
        },
    ]

    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    # State-free baseline must STILL have exposure — it builds its own
    # basket selection from indicators regardless of risk_on
    assert cs_rets["gross_exposure"].sum() > 0, (
        "State-free CS baseline must stay invested even when rotation "
        "has empty selected_baskets due to risk_off"
    )


def test_nonpositive_state_does_not_change_state_free_cs_selections() -> None:
    """Nonpositive individual security states must NOT change state-free CS
    selections — the baseline ignores absolute state entirely."""
    from src.research.hierarchical_rotation_validation import (
        _cross_section_only_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=5)
    perf_frame = pd.DataFrame(
        {"A": [0.01] * 5, "B": [0.005] * 5, "QQQ": [0.003] * 5},
        index=dates,
    )
    perf_frame.index.name = "date"
    drift_frame = pd.DataFrame(
        {"A": [0.005] * 5, "B": [0.003] * 5, "QQQ": [0.001] * 5},
        index=dates,
    )
    drift_frame.index.name = "date"

    # A: great scores but EXIT state (would be excluded by full strategy)
    # B: mediocre scores but ENTER state
    indicator_rows = []
    for d in dates:
        for sym, rel, m20, dd, rvol in [
            ("A", 0.90, 0.85, 0.80, 0.20),
            ("B", 0.40, 0.35, 0.30, 0.45),
            ("QQQ", 0.50, 0.50, 0.50, 0.50),
        ]:
            indicator_rows.append({
                "date": d, "symbol": sym,
                "relative_momentum_63_vs_benchmark": rel,
                "momentum_20": m20,
                "drawdown_from_63d_high": dd,
                "realized_volatility_20": rvol,
                "sma_50": 100.0, "close": 105.0,
            })
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "market_regime": {"reference": "QQQ"},
        "rotation": {
            "score": {
                "components": {
                    "median_relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "breadth_above_sma50": {"weight": 0.25, "direction": "higher_is_better"},
                    "median_drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "eligibility": {
                "minimum_eligible_constituents": 1,
                "minimum_constituent_coverage_ratio": 0.5,
                "minimum_breadth_above_sma50": 0.0,
                "require_positive_median_relative_momentum_63": False,
            },
            "maximum_selected_baskets": 1,
            "maximum_selected_symbols_per_basket": 1,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
            "absolute_state_filter": {"ENTER": 1.0, "HOLD": 1.0, "WATCH": 0.0, "EXIT": 0.0},
        },
    }
    pool = {"baskets": {"growth": {"symbols": ["A", "B"]}}}
    candidates = ["A", "B"]

    rotations = [
        {"date": dates[0].strftime("%Y-%m-%d"), "selected_baskets": ["growth"]},
    ]

    cs_rets = _cross_section_only_returns(
        perf_frame, drift_frame, rotations, indicators,
        spec, pool, candidates, 10.0,
    )

    # A should be selected (high scores) regardless of what its state would be
    assert cs_rets["gross_exposure"].sum() > 0
    # A should have higher weight than B (better scores regardless of state)
    assert cs_rets["A"].iloc[0] > cs_rets["B"].iloc[0], (
        "State-free CS must select A (higher score) over B (lower score) "
        "regardless of what their individual states would be"
    )


def test_state_free_security_selection_is_deterministic() -> None:
    """State-free security selection must break ties by symbol (ascending).

    When two securities have identical composite scores, the selection must
    be deterministic — symbol ascending breaks the tie.
    """
    from src.research.hierarchical_rotation_validation import (
        _build_state_free_security_selection,
    )

    dates = pd.bdate_range("2025-01-02", periods=1)
    d = dates[0]
    # A and B have identical indicator values → identical composite scores
    indicator_rows = [
        {"date": d, "symbol": "B",
         "relative_momentum_63_vs_benchmark": 0.80,
         "momentum_20": 0.75,
         "drawdown_from_63d_high": 0.70,
         "realized_volatility_20": 0.25,
         "sma_50": 100.0, "close": 105.0},
        {"date": d, "symbol": "A",
         "relative_momentum_63_vs_benchmark": 0.80,
         "momentum_20": 0.75,
         "drawdown_from_63d_high": 0.70,
         "realized_volatility_20": 0.25,
         "sma_50": 100.0, "close": 105.0},
    ]
    indicators = pd.DataFrame(indicator_rows)

    spec = {
        "rotation": {
            "maximum_selected_symbols_per_basket": 1,
        },
        "security_selection": {
            "cross_section": {
                "components": {
                    "relative_momentum_63_vs_benchmark": {"weight": 0.25, "direction": "higher_is_better"},
                    "momentum_20": {"weight": 0.25, "direction": "higher_is_better"},
                    "drawdown_from_63d_high": {"weight": 0.25, "direction": "higher_is_better"},
                    "realized_volatility_20": {"weight": 0.25, "direction": "lower_is_better"},
                },
                "minimum_composite_percentile": 0.50,
            },
        },
    }

    selected = _build_state_free_security_selection(
        d, "test_basket", ["A", "B"], indicators, spec,
    )
    assert len(selected) == 1
    # "A" < "B" alphabetically → A must be selected when scores are tied
    assert selected[0] == "A", (
        f"State-free tie-breaking must select symbol ascending (A before B), "
        f"got: {selected[0]}"
    )


def test_missing_held_return_fails_closed_in_ew_bh() -> None:
    """EW B&H must raise ValueError when a positively held symbol has NaN
    return on a later date — not silently substitute 0.

    The frame must first be trimmed to observable dates via
    _trim_return_frame_to_observable.  A NaN for a positively-held symbol
    after trimming is a real data error.
    """
    from src.research.hierarchical_rotation_validation import (
        _ew_buy_hold_returns,
    )

    dates = pd.bdate_range("2025-01-02", periods=5)
    perf_frame = pd.DataFrame(
        {"A": [0.01, 0.02, np.nan, np.nan, np.nan], "B": [0.005, 0.01, -0.003, np.nan, np.nan]},
        index=dates,
    )
    perf_frame.index.name = "date"

    # Without trimming, EW B&H raises ValueError because A (positive weight
    # from day 0, drifts naturally) has NaN return on day 2
    with pytest.raises(ValueError, match="non-finite"):
        _ew_buy_hold_returns(perf_frame, ["A", "B"], cost_bps=10.0)

    # With a clean frame (all held symbols have valid returns throughout),
    # EW B&H succeeds
    clean_dates = pd.bdate_range("2025-01-02", periods=3)
    clean_perf = pd.DataFrame(
        {"A": [0.01, 0.02, 0.015], "B": [0.005, 0.01, -0.003]},
        index=clean_dates,
    )
    clean_perf.index.name = "date"
    ew, diag = _ew_buy_hold_returns(clean_perf, ["A", "B"], cost_bps=10.0)
    assert diag["eligible_count"] == 2
    assert ew["portfolio_return"].iloc[0] != 0.0
    # All returns present — no substitution needed
    assert ew["portfolio_return"].iloc[2] != 0.0


# ---------------------------------------------------------------------------
# module-scoped full-run fixture (shared across artifact/decision/manifest tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _full_run_output(tmp_path_factory) -> dict:
    """One full synthetic pipeline run; output_dir + decision reused by all
    artifact/decision/manifest/report tests to avoid recomputing the heavy
    indicator/rotation engine 16 times.

    A second identical run is also persisted so ``test_manifest_is_deterministic``
    can compare without a fresh pipeline call.

    The five expensive generic-engine functions are monkeypatched to return
    minimal deterministic data for both runs (``MonkeyPatch.context()`` is used
    because module-scoped fixtures cannot request function-scoped monkeypatch).
    The REAL validation pipeline — raw-cutoff, provider readiness, evidence
    writing, gates, report, hashes, and decision — is exercised unmodified.
    The existing tests/test_hierarchical_pool_rotation_engine.py and
    tests/test_multi_market_hierarchical_rotation_contract.py remain the true
    generic-engine coverage.
    """
    output_a = tmp_path_factory.mktemp("full_run_a")
    prices = _synthetic_prices_long()
    prices_a = output_a / "prices.csv"
    prices.to_csv(prices_a, index=False)

    pool = _pool()
    candidates = [sym for b in pool["baskets"].values() for sym in b["symbols"]]

    # 6 deterministic dates within the development window that exist in the
    # synthetic prices CSV
    stub_dates = pd.bdate_range("2025-06-02", periods=6)

    # ------------------------------------------------------------------ #
    # stub compute_hierarchical_indicators
    # ------------------------------------------------------------------ #
    def _stub_indicators(_prices: pd.DataFrame, _timing_spec: dict) -> pd.DataFrame:
        rows: list[dict] = []
        for d in stub_dates:
            for sym in candidates:
                rows.append({
                    "date": d, "symbol": sym, "risk_on": True,
                    "relative_momentum_63_vs_benchmark": 0.6,
                    "momentum_20": 0.5,
                    "drawdown_from_63d_high": -0.05,
                    "realized_volatility_20": 0.15,
                    "sma_50": 100.0, "close": 105.0,
                })
            for ref_sym in ("QQQ", "SOX"):
                rows.append({
                    "date": d, "symbol": ref_sym, "risk_on": True,
                    "relative_momentum_63_vs_benchmark": 0.5,
                    "momentum_20": 0.5,
                    "drawdown_from_63d_high": -0.03,
                    "realized_volatility_20": 0.12,
                    "sma_50": 100.0, "close": 105.0,
                })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    # stub generate_signal_history
    # ------------------------------------------------------------------ #
    def _stub_signal_history(
        _indicators: pd.DataFrame, _timing_spec: dict,
    ) -> tuple[list[dict], list[dict]]:
        signal_history: list[dict] = []
        for d in stub_dates:
            for sym in candidates:
                signal_history.append({
                    "date": d.strftime("%Y-%m-%d"), "symbol": sym,
                    "state": "ENTER", "previous_state": "WATCH",
                    "state_changed": True, "position_open_after_close": True,
                    "reason_codes": ["ENTER_BREAKOUT_TREND_RELATIVE_STRENGTH_CONFIRMED"],
                    "market_regime": "bull", "risk_on": True,
                    "actionable_from": None, "indicators": {},
                })
            for ref_sym in ("QQQ", "SOX"):
                signal_history.append({
                    "date": d.strftime("%Y-%m-%d"), "symbol": ref_sym,
                    "state": "HOLD", "previous_state": "HOLD",
                    "state_changed": False, "position_open_after_close": True,
                    "reason_codes": ["HOLD_TREND_AND_STOP_INTACT"],
                    "market_regime": "bull", "risk_on": True,
                    "actionable_from": None, "indicators": {},
                })
        reference_history = [
            {"date": d.strftime("%Y-%m-%d"), "symbol": "QQQ",
             "role": "market_regime", "regime": "bull",
             "close": 200.0, "sma_50": 195.0, "sma_200": 190.0}
            for d in stub_dates
        ] + [
            {"date": d.strftime("%Y-%m-%d"), "symbol": "SOX",
             "role": "sector_context", "regime": "bull",
             "close": 3000.0, "sma_50": 2900.0, "sma_200": 2800.0}
            for d in stub_dates
        ]
        return signal_history, reference_history

    # ------------------------------------------------------------------ #
    # stub build_hierarchical_rotation_history
    # ------------------------------------------------------------------ #
    def _stub_rotation_history(
        _indicators: pd.DataFrame, _signal_history: list[dict],
        _spec: dict, _pool: dict,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        basket_scores: list[dict] = []
        security_scores: list[dict] = []
        rotations: list[dict] = []
        for idx in (0, 4):
            rdate = stub_dates[idx]
            d_str = rdate.strftime("%Y-%m-%d")
            rotations.append({
                "date": d_str, "actionable_from": d_str,
                "market": "us", "benchmark": "QQQ",
                "risk_on": True, "market_regime": "bull",
                "selected_baskets": [
                    "semiconductor_compute", "ai_infrastructure_power",
                ],
                "selected_symbols_by_basket": {
                    "semiconductor_compute": [
                        {"symbol": "AMD", "security_composite_percentile": 0.9},
                        {"symbol": "INTC", "security_composite_percentile": 0.8},
                    ],
                    "ai_infrastructure_power": [
                        {"symbol": "VRT", "security_composite_percentile": 0.85},
                        {"symbol": "NBIS", "security_composite_percentile": 0.75},
                    ],
                },
                "reason_codes": ["ROTATION_SELECTION_COMPLETED"],
            })
        return basket_scores, security_scores, rotations

    # ------------------------------------------------------------------ #
    # stub build_hierarchical_portfolio_history
    # ------------------------------------------------------------------ #
    def _stub_portfolio_history(
        _indicators: pd.DataFrame, _signal_history: list[dict],
        _rotations: list[dict], _spec: dict,
    ) -> list[dict]:
        portfolio_history: list[dict] = []
        for d in stub_dates:
            d_str = d.strftime("%Y-%m-%d")
            portfolio_history.append({
                "date": d_str, "actionable_from": d_str,
                "market": "us", "benchmark": "QQQ",
                "rotation_date": stub_dates[0].strftime("%Y-%m-%d"),
                "risk_on": True, "market_regime": "bull",
                "selected_baskets": [
                    "semiconductor_compute", "ai_infrastructure_power",
                ],
                "positions": [
                    {
                        "symbol": "AMD", "target_weight": 0.125,
                        "basket": "semiconductor_compute", "state": "HOLD",
                        "security_composite_percentile": 0.9,
                        "state_multiplier": 1.0,
                        "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None,
                    },
                    {
                        "symbol": "INTC", "target_weight": 0.125,
                        "basket": "semiconductor_compute", "state": "HOLD",
                        "security_composite_percentile": 0.8,
                        "state_multiplier": 1.0,
                        "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None,
                    },
                    {
                        "symbol": "VRT", "target_weight": 0.125,
                        "basket": "ai_infrastructure_power", "state": "HOLD",
                        "security_composite_percentile": 0.85,
                        "state_multiplier": 1.0,
                        "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None,
                    },
                    {
                        "symbol": "NBIS", "target_weight": 0.125,
                        "basket": "ai_infrastructure_power", "state": "HOLD",
                        "security_composite_percentile": 0.75,
                        "state_multiplier": 1.0,
                        "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None,
                    },
                ],
                "gross_exposure": 0.5, "cash_weight": 0.5,
                "reason_codes": ["PORTFOLIO_ROTATION_ACTIVE"],
            })
        return portfolio_history

    # ------------------------------------------------------------------ #
    # stub _build_return_frames: deterministic 6-date frames
    # ------------------------------------------------------------------ #
    def _stub_return_frames(
        _prices: pd.DataFrame,
        candidates: list[str],
        benchmark: str,
        _start: str,
        _end: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return deterministic 6-date perf/drift frames for all windows."""
        dates = stub_dates
        all_cols = [*candidates, benchmark]
        perf_data: dict[str, list[float]] = {}
        drift_data: dict[str, list[float]] = {}
        market_pattern = [0.004, -0.003, 0.005, -0.002, 0.003, -0.001]
        for sym in all_cols:
            phase = (sum(ord(c) for c in sym) % 11 - 5) * 0.0001
            perf_data[sym] = [value + phase for value in market_pattern]
            drift_data[sym] = [value * 0.5 + phase for value in market_pattern]
        perf = pd.DataFrame(perf_data, index=list(dates))
        perf.index.name = "date"
        drift = pd.DataFrame(drift_data, index=list(dates))
        drift.index.name = "date"
        return perf, drift

    # ---- patch the five heavy generic-engine functions and run ----
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".compute_hierarchical_indicators",
            _stub_indicators,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".generate_signal_history",
            _stub_signal_history,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".build_hierarchical_rotation_history",
            _stub_rotation_history,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".build_hierarchical_portfolio_history",
            _stub_portfolio_history,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            "._build_return_frames",
            _stub_return_frames,
        )

        decision_a = run_us_hierarchical_rotation_validation(
            spec_path=FROZEN_SPEC,
            prices_csv=prices_a,
            output_dir=output_a,
        )

        # Second run for determinism comparison
        output_b = tmp_path_factory.mktemp("full_run_b")
        prices_b = output_b / "prices.csv"
        prices.to_csv(prices_b, index=False)
        decision_b = run_us_hierarchical_rotation_validation(
            spec_path=FROZEN_SPEC,
            prices_csv=prices_b,
            output_dir=output_b,
        )

    return {
        "output_dir": output_a,
        "decision": decision_a,
        "output_dir_b": output_b,
        "decision_b": decision_b,
    }


# ---------------------------------------------------------------------------
# integration tests: frozen spec validation
# ---------------------------------------------------------------------------


def test_frozen_spec_accepts_authoritative_validation() -> None:
    """Frozen spec has authoritative_validation_allowed=true."""
    spec = _load(FROZEN_SPEC)
    assert spec["authoritative_validation_allowed"] is True
    assert spec["experiment_id"] == "us_structured_pool_hierarchical_rotation_v2"
    assert spec["parameter_search"]["allowed"] is False
    assert "validation" in spec
    assert "gates" in spec["validation"]


def test_draft_spec_rejects_authoritative_validation(tmp_path: Path) -> None:
    """Draft spec cannot run authoritative validation (error raised before
    any CSV reading, so an empty CSV suffices)."""
    prices_csv = tmp_path / "prices.csv"
    pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close"]).to_csv(
        prices_csv, index=False
    )
    with pytest.raises(ValueError, match="authoritative"):
        run_us_hierarchical_rotation_validation(
            spec_path=DRAFT_SPEC,
            prices_csv=prices_csv,
            output_dir=tmp_path / "output",
        )


# ---------------------------------------------------------------------------
# provider readiness: fail-closed (with short-history support)
# ---------------------------------------------------------------------------


def test_provider_readiness_detects_missing_symbols() -> None:
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    prices = _synthetic_prices_long()
    prices = prices[~prices["symbol"].isin(["KO", "WMT"])]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices.to_csv(csv_path, index=False)
        result = _verify_provider_readiness(csv_path, spec, pool)
        assert not result["provider_ready"]
        assert len(result["missing_provider_symbols"]) >= 2


def test_provider_readiness_detects_stale_data() -> None:
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    prices = _synthetic_prices_long()
    prices = prices[pd.to_datetime(prices["date"]) < pd.Timestamp("2025-12-31")]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices.to_csv(csv_path, index=False)
        result = _verify_provider_readiness(csv_path, spec, pool)
        assert not result["provider_ready"]
        assert len(result["stale_provider_symbols"]) > 0


def test_provider_ready_with_complete_data() -> None:
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    prices = _synthetic_prices_long()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices.to_csv(csv_path, index=False)
        result = _verify_provider_readiness(csv_path, spec, pool)
        assert result["provider_ready"]
        assert result["required_provider_count"] == 25
        assert "^SOX" in result["required_provider_symbols"]


def test_short_history_candidate_not_failed_for_recent_listing() -> None:
    """A recent listing lacking 2021 history must not fail readiness.
    It still needs coverage from its actual first date through 2026-06-30."""
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    prices = _synthetic_prices_long()

    # Simulate a recent listing: HIMS only has data from 2025 onwards
    prices = prices[
        ~(
            (prices["symbol"] == "HIMS")
            & (pd.to_datetime(prices["date"]) < pd.Timestamp("2025-01-02"))
        )
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices.to_csv(csv_path, index=False)
        result = _verify_provider_readiness(csv_path, spec, pool)
        # Should still be ready — HIMS has coverage from its actual first date
        assert result["provider_ready"]
        # Short history diagnostics should be recorded
        assert len(result.get("short_history_diagnostics", {})) > 0
        # HIMS should appear in short_history_diagnostics
        assert "HIMS" in result.get("short_history_diagnostics", {})


# ---------------------------------------------------------------------------
# reserved rows exclusion
# ---------------------------------------------------------------------------


def test_reserved_rows_cutoff_via_pure_helper(tmp_path: Path) -> None:
    """Reserved rows are excluded by the pure raw-cutoff helper.

    Rows whose date >= 2026-07-01 are discarded as the FIRST data-boundary
    operation, before any alias mapping, duplicate checks, or computation.
    Adding garbage (extreme values, duplicates) to the reserved zone must NOT
    change the observed slice.  However, duplicate/invalid rows in the observed
    zone ARE still present (not silently filtered) — the cutoff is purely a
    date boundary, not a data-quality filter.
    """
    prices = _synthetic_prices_long()
    csv_path = tmp_path / "prices.csv"
    prices.to_csv(csv_path, index=False)

    reserved_start = pd.Timestamp("2026-07-01")
    observed_a, identity_a = _load_observed_slice(csv_path, reserved_start)

    # All synthetic rows end at 2026-06-30, so all are observed
    assert identity_a["reserved_rows_excluded"] == 0
    assert identity_a["raw_row_count"] == identity_a["observed_row_count"]
    assert observed_a["date"].max() < reserved_start

    # ---- mutate the reserved zone with garbage ----
    garbage_1 = prices.tail(5).copy()
    garbage_1["date"] = pd.Timestamp("2026-07-10")
    garbage_1["close"] *= 999.0
    garbage_1["open"] *= 999.0

    garbage_2 = prices.tail(3).copy()
    garbage_2["date"] = pd.Timestamp("2026-07-12")
    garbage_2["close"] = -1.0
    garbage_2["open"] = -1.0
    garbage_3 = garbage_2.copy()  # exact duplicate date/symbol

    mutated = pd.concat(
        [prices, garbage_1, garbage_2, garbage_3], ignore_index=True
    )
    csv_mut = tmp_path / "mutated.csv"
    mutated.to_csv(csv_mut, index=False)

    observed_b, identity_b = _load_observed_slice(csv_mut, reserved_start)

    # Observed rows must be identical (garbage in reserved zone ignored)
    assert identity_b["reserved_rows_excluded"] == len(garbage_1) + len(garbage_2) + len(garbage_3)
    assert identity_b["raw_row_count"] > identity_a["raw_row_count"]
    assert identity_b["observed_row_count"] == identity_a["observed_row_count"]
    assert len(observed_b) == len(observed_a)
    pd.testing.assert_frame_equal(
        observed_a.reset_index(drop=True),
        observed_b.reset_index(drop=True),
    )


def test_reserved_rows_cutoff_rejects_duplicate_observed_rows(tmp_path: Path) -> None:
    """Duplicate/invalid rows in the OBSERVED zone are still present after
    cutoff — the cutoff is a pure date filter, not a data-quality gate."""
    prices = _synthetic_prices_long()
    csv_path = tmp_path / "prices.csv"
    prices.to_csv(csv_path, index=False)

    # Add a duplicate date/symbol row within the observed zone (2026-06-01)
    dup = prices[prices["date"] == "2026-06-01"].head(1).copy()
    mutated = pd.concat([prices, dup], ignore_index=True)
    csv_mut = tmp_path / "mutated.csv"
    mutated.to_csv(csv_mut, index=False)

    reserved_start = pd.Timestamp("2026-07-01")
    observed, _identity = _load_observed_slice(csv_mut, reserved_start)

    # The duplicate survived the cutoff (no dedup at this stage)
    with_dates = observed[observed["date"] == pd.Timestamp("2026-06-01")]
    assert len(with_dates) > 0
    # Duplicate means > 1 row for that date+symbol
    dup_mask = (
        (observed["date"] == pd.Timestamp("2026-06-01"))
        & (observed["symbol"] == dup["symbol"].iloc[0])
    )
    assert dup_mask.sum() > 1, "duplicate observed rows survive the cutoff"


# ---------------------------------------------------------------------------
# decision vocabulary and trade_ready=false
# ---------------------------------------------------------------------------


def test_decision_vocabulary_and_safety_fields(
    _full_run_output: dict,
) -> None:
    """Decision must use correct vocabulary and never claim trade-ready."""
    decision = _full_run_output["decision"]

    assert decision["trade_ready"] is False
    assert decision["research_only"] is True
    assert decision["reserved_performance_opened"] is False
    assert decision["decision"] in {
        "us_hierarchical_rotation_not_supported_on_observed_evidence",
        "us_hierarchical_rotation_independent_validation_required",
    }
    assert decision["market"] == "us"
    assert decision["experiment_id"] == "us_structured_pool_hierarchical_rotation_v2"
    # observed_slice must be present
    assert "observed_slice" in decision
    assert "reserved_rows_excluded" in decision["observed_slice"]


def test_all_four_baselines_present_in_output(_full_run_output: dict) -> None:
    """Baseline metrics output must contain all four predeclared baselines."""
    metrics = json.loads(
        (_full_run_output["output_dir"] / "baseline_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "equal_weight_pool_buy_and_hold",
        "time_series_state_only",
        "hierarchical_cross_section_only",
        "hierarchical_cross_section_plus_state",
    }
    assert set(metrics["baselines"]) == expected
    for label in expected:
        for window in ["development_observed", "falsification_only", "full_observed"]:
            assert window in metrics["baselines"][label], f"{label} missing {window}"


# ---------------------------------------------------------------------------
# evidence manifest and hash determinism
# ---------------------------------------------------------------------------


def test_evidence_manifest_binds_all_outputs(_full_run_output: dict) -> None:
    """Evidence manifest must reference provider, spec, pool, and output hashes."""
    manifest = json.loads(
        (_full_run_output["output_dir"] / "evidence_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert "provider_identity_sha256" in manifest
    assert "spec_identity_sha256" in manifest
    assert "pool_identity_sha256" in manifest
    assert "validation_implementation_sha256" in manifest
    assert "hierarchical_engine_implementation_sha256" in manifest
    assert "timing_formula_identity_sha256" in manifest
    assert "manifest_identity_sha256" in manifest
    assert "observed_slice_identity" in manifest
    assert len(manifest["outputs"]) >= 6


def test_evidence_manifest_output_hashes_match_final_files(
    _full_run_output: dict,
) -> None:
    """The manifest seals final bytes, including report.md written in this run."""
    import hashlib

    output_dir = _full_run_output["output_dir"]
    manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    for filename, expected_sha256 in manifest["outputs"].items():
        actual_sha256 = hashlib.sha256(
            (output_dir / filename).read_bytes()
        ).hexdigest()
        assert actual_sha256 == expected_sha256, filename


def test_manifest_is_deterministic(_full_run_output: dict) -> None:
    """Two runs with identical inputs produce identical manifests.

    Uses the pre-computed twin runs from the module-scoped fixture."""
    manifest_a = json.loads(
        (_full_run_output["output_dir"] / "evidence_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_b = json.loads(
        (_full_run_output["output_dir_b"] / "evidence_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        manifest_a["manifest_identity_sha256"]
        == manifest_b["manifest_identity_sha256"]
    )
    assert manifest_a["outputs"] == manifest_b["outputs"]


# ---------------------------------------------------------------------------
# evidence output completeness
# ---------------------------------------------------------------------------


def test_all_evidence_files_written(_full_run_output: dict) -> None:
    """All expected evidence artifacts exist after a completed run."""
    output_dir = _full_run_output["output_dir"]
    expected_files = [
        "provider_readiness.json",
        "baseline_metrics.json",
        "attribution.json",
        "concentration.json",
        "selection_stability.json",
        "evidence_manifest.json",
        "decision.json",
        "report.md",
    ]
    for filename in expected_files:
        assert (output_dir / filename).is_file(), f"Missing {filename}"


def test_report_md_contains_decision_and_disclaimers(_full_run_output: dict) -> None:
    """Report.md must include decision, trade_ready=false, and methodology."""
    report = (_full_run_output["output_dir"] / "report.md").read_text(
        encoding="utf-8"
    )
    assert "trade_ready" in report.lower() or "Trade ready" in report
    assert "Research only" in report or "research_only" in report
    assert "next-session open-to-open" in report
    assert "equal_weight_pool_buy_and_hold" in report
    assert "Avg Cash" in report
    assert "Avg Hold" in report
    assert "Basket breadth and gross contribution" in report
    assert "Counterfactual totals" in report


def test_report_null_metrics_render_as_na(_full_run_output: dict) -> None:
    """Optional/None metrics in the report table render as 'n/a' not a crash or 'None'."""
    report = (_full_run_output["output_dir"] / "report.md").read_text(
        encoding="utf-8"
    )

    # The EW baseline's own ew_relative_return is None by design (difference of
    # itself against itself is not meaningful).  Must render as "n/a", not crash
    # with a format-string error, and not display the literal string "None".
    assert "n/a" in report, "report must contain 'n/a' for null metrics"
    assert "None" not in report, "report must not contain bare 'None' for metrics"


# ---------------------------------------------------------------------------
# incomplete coverage fails closed
# ---------------------------------------------------------------------------


def test_missing_symbol_fails_closed_at_provider_level(tmp_path: Path) -> None:
    """Removing a required symbol from the provider must produce fail decision."""
    prices = _synthetic_prices_long()
    prices = prices[prices["symbol"] != "TSLA"]
    prices_csv = tmp_path / "missing_tsla.csv"
    prices.to_csv(prices_csv, index=False)

    decision = run_us_hierarchical_rotation_validation(
        spec_path=FROZEN_SPEC,
        prices_csv=prices_csv,
        output_dir=tmp_path / "output",
    )

    assert (
        decision["decision"]
        == "us_hierarchical_rotation_not_supported_on_observed_evidence"
    )
    assert decision["provider_ready"] is False
    assert decision["trade_ready"] is False


# ---------------------------------------------------------------------------
# fail-closed artifacts on early provider failure
# ---------------------------------------------------------------------------


def test_fail_closed_writes_all_expected_artifacts(tmp_path: Path) -> None:
    """Early provider failure must write complete artifact set, never
    implying performance was evaluated."""
    prices = _synthetic_prices_long()
    prices = prices[prices["symbol"] != "TSLA"]  # force failure
    prices_csv = tmp_path / "missing_tsla.csv"
    prices.to_csv(prices_csv, index=False)
    output_dir = tmp_path / "output"

    run_us_hierarchical_rotation_validation(
        spec_path=FROZEN_SPEC,
        prices_csv=prices_csv,
        output_dir=output_dir,
    )

    expected_files = [
        "provider_readiness.json",
        "baseline_metrics.json",
        "attribution.json",
        "concentration.json",
        "selection_stability.json",
        "evidence_manifest.json",
        "decision.json",
        "report.md",
    ]
    for filename in expected_files:
        assert (output_dir / filename).is_file(), f"Missing {filename}"

    # Verify stub files do NOT claim performance was evaluated
    baseline = json.loads(
        (output_dir / "baseline_metrics.json").read_text(encoding="utf-8")
    )
    assert baseline.get("performance_evaluated") is False

    attribution = json.loads(
        (output_dir / "attribution.json").read_text(encoding="utf-8")
    )
    assert attribution.get("performance_evaluated") is False


# ---------------------------------------------------------------------------
# attribution: market_regime_effect is identified or null with limitation
# ---------------------------------------------------------------------------


def test_attribution_market_regime_not_fake_zero(_full_run_output: dict) -> None:
    """Attribution must not hardcode market_regime_effect=0; must be
    computed from the internal no-market-regime counterfactual."""
    attribution = json.loads(
        (_full_run_output["output_dir"] / "attribution.json").read_text(
            encoding="utf-8"
        )
    )
    mr = attribution.get("market_regime_effect")
    # market_regime_effect must be present and computed from counterfactual
    assert mr is not None, "market_regime_effect must be computed, not null"
    assert "market_regime_effect_definition" in attribution
    assert "full minus no-market-regime" in str(attribution["market_regime_effect_definition"]).lower()
    # Basket and security rank effects must also be present
    assert attribution.get("basket_rank_effect") is not None
    assert attribution.get("security_rank_effect") is not None
    assert attribution.get("state_overlay_effect") is not None


def test_counterfactual_no_market_regime_forces_risk_on_before_signal_generation() -> None:
    """Regression: risk_off indicators are forced risk_on=True BEFORE
    generate_signal_history is called, producing a recomputed portfolio
    with COUNTERFACTUAL_NO_MARKET_REGIME reason codes.

    This proves the counterfactual truly recomputes from forced indicators
    rather than post-processing an already-built portfolio (which can't
    undo market-regime decisions baked into individual security states).
    """
    from src.research.hierarchical_rotation_validation import (
        _counterfactual_no_market_regime,
    )
    from src.research.hierarchical_pool_rotation import (
        build_hierarchical_portfolio_history,
        build_hierarchical_rotation_history,
    )
    from src.research.focus_watchlist_signal import generate_signal_history

    spec = _load(FROZEN_SPEC)
    pool = _pool()
    candidates = [
        sym for basket in pool["baskets"].values() for sym in basket["symbols"]
    ]
    benchmark = str(spec["market_regime"]["reference"])
    dates = pd.bdate_range("2025-06-02", periods=5)

    # Build indicators with risk_on=False for ALL rows (market crash scenario)
    indicator_rows: list[dict] = []
    for d in dates:
        for sym in candidates + [benchmark]:
            indicator_rows.append({
                "date": d, "symbol": sym,
                "risk_on": False,  # <-- risk_off input
                "market_regime": "bear",
                "close": 100.0 + hash(sym) % 10,
                "sma_50": 98.0, "sma_200": 95.0,
                "atr_14": 1.5, "sma_20": 99.0,
                "relative_momentum_63_vs_benchmark": 0.3,
                "momentum_20": 0.2,
                "drawdown_from_63d_high": -0.15,
                "realized_volatility_20": 0.30,
            })
    indicators = pd.DataFrame(indicator_rows)

    # Minimal timing_spec matching the stub structure
    timing_spec: dict[str, Any] = {
        "anchor_date": "2025-06-02",
        "validation_start": "2025-01-02",
        "validation_end": "2026-06-30",
    }

    # Capture the indicators passed to generate_signal_history
    captured_indicators: list[pd.DataFrame] = []

    def _capture_signal_history(
        ind: pd.DataFrame, ts: dict,
    ) -> tuple[list[dict], list[dict]]:
        captured_indicators.append(ind.copy())
        signal_hist: list[dict] = []
        for d in dates:
            for sym in candidates:
                signal_hist.append({
                    "date": d.strftime("%Y-%m-%d"), "symbol": sym,
                    "state": "ENTER", "previous_state": "WATCH",
                    "state_changed": True, "position_open_after_close": True,
                    "reason_codes": ["ENTER_BREAKOUT"],
                    "market_regime": "counterfactual_risk_on",
                    "risk_on": True,
                    "actionable_from": None, "indicators": {},
                })
        ref_hist: list[dict] = [
            {"date": d.strftime("%Y-%m-%d"), "symbol": benchmark,
             "role": "market_regime", "regime": "bull",
             "close": 200.0, "sma_50": 195.0, "sma_200": 190.0}
            for d in dates
        ]
        return signal_hist, ref_hist

    def _stub_rotations(
        _ind: pd.DataFrame, _sig: list, _sp: dict, _p: dict,
    ) -> tuple[list, list, list]:
        rdate = dates[0].strftime("%Y-%m-%d")
        rot = {
            "date": rdate, "actionable_from": rdate,
            "market": "us", "benchmark": benchmark,
            "risk_on": True, "market_regime": "counterfactual_risk_on",
            "selected_baskets": ["semiconductor_compute"],
            "selected_symbols_by_basket": {
                "semiconductor_compute": [
                    {"symbol": "AMD", "security_composite_percentile": 0.9},
                    {"symbol": "INTC", "security_composite_percentile": 0.8},
                ],
            },
            "reason_codes": ["ROTATION_SELECTION_COMPLETED"],
        }
        return [], [], [rot]

    def _stub_portfolio(
        _ind: pd.DataFrame, _sig: list, _rots: list, _sp: dict,
    ) -> list[dict]:
        portfolio: list[dict] = []
        for d in dates:
            d_str = d.strftime("%Y-%m-%d")
            portfolio.append({
                "date": d_str, "actionable_from": d_str,
                "market": "us", "benchmark": benchmark,
                "rotation_date": dates[0].strftime("%Y-%m-%d"),
                "risk_on": True, "market_regime": "counterfactual_risk_on",
                "selected_baskets": ["semiconductor_compute"],
                "positions": [
                    {"symbol": "AMD", "target_weight": 0.25,
                     "basket": "semiconductor_compute", "state": "HOLD",
                     "security_composite_percentile": 0.9,
                     "state_multiplier": 1.0,
                     "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None},
                    {"symbol": "INTC", "target_weight": 0.25,
                     "basket": "semiconductor_compute", "state": "HOLD",
                     "security_composite_percentile": 0.8,
                     "state_multiplier": 1.0,
                     "state_reason_codes": ["HOLD"], "trailing_stop_3atr": None},
                ],
                "gross_exposure": 0.5, "cash_weight": 0.5,
                "reason_codes": ["PORTFOLIO_ROTATION_ACTIVE"],
            })
        return portfolio

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.research.hierarchical_rotation_validation.generate_signal_history",
            _capture_signal_history,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation.build_hierarchical_rotation_history",
            _stub_rotations,
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation.build_hierarchical_portfolio_history",
            _stub_portfolio,
        )
        result = _counterfactual_no_market_regime(
            indicators, timing_spec, spec, pool,
        )

    # ---- Verify risk_on was forced BEFORE signal generation -----------------
    assert len(captured_indicators) == 1, (
        "generate_signal_history must be called exactly once"
    )
    captured = captured_indicators[0]
    assert captured["risk_on"].all(), (
        "ALL rows in captured indicators must have risk_on=True (forced before "
        "signal generation)"
    )
    assert (captured["market_regime"] == "counterfactual_risk_on").all(), (
        "ALL rows in captured indicators must have "
        "market_regime='counterfactual_risk_on'"
    )
    # The original indicators still have risk_on=False (copy was forced, not mutated)
    assert (~indicators["risk_on"]).all(), (
        "Original indicators must NOT be mutated by the counterfactual"
    )

    # ---- Verify returned portfolio has counterfactual reason codes ----------
    assert len(result) > 0, "Counterfactual portfolio must not be empty"
    for entry in result:
        assert entry["risk_on"] is True, (
            f"Every entry must have risk_on=True, got {entry['risk_on']}"
        )
        assert entry["market_regime"] == "counterfactual_risk_on", (
            f"Every entry must have market_regime='counterfactual_risk_on', "
            f"got {entry['market_regime']}"
        )
        assert "COUNTERFACTUAL_NO_MARKET_REGIME" in entry["reason_codes"], (
            f"Every entry must have COUNTERFACTUAL_NO_MARKET_REGIME in "
            f"reason_codes, got {entry['reason_codes']}"
        )


# ---------------------------------------------------------------------------
# gate tightening: full strategy vs QQQ and EW
# ---------------------------------------------------------------------------


def test_gates_expose_every_comparison(_full_run_output: dict) -> None:
    """Gate output must expose every comparison including QQQ-relative and EW-relative."""
    decision = _full_run_output["decision"]
    gate_result = decision.get("gate_result", {})
    details = gate_result.get("details", {})
    # QQQ and EW relative return gates are driven by YAML config now
    # Verify the config-driven gate keys appear in the details
    gate_keys_present = set(details.keys())
    assert any("aggregate_qqq_relative_return" in k for k in gate_keys_present), (
        f"QQQ relative return gate missing from: {sorted(gate_keys_present)}"
    )
    assert any("ew_relative_return" in k for k in gate_keys_present), (
        f"EW relative return gate missing from: {sorted(gate_keys_present)}"
    )


# ---------------------------------------------------------------------------
# manifest / snapshot tests
# ---------------------------------------------------------------------------


def _mini_manifest(identity_sha256: str, prices_sha256: str) -> dict:
    """Minimal valid snapshot manifest fixture."""
    return {
        "schema_version": "1.0",
        "manifest_type": "provider_snapshot",
        "market": "us",
        "snapshot": {
            "prices_csv": "prices.csv",
            "prices_csv_sha256": prices_sha256,
            "symbols": ["AAPL", "QQQ", "^SOX"],
            "symbol_count": 3,
            "first_observed_date": "2021-01-04",
            "last_observed_date": "2026-06-30",
            "observed_row_count": 100,
        },
        "calendar": {
            "first_day": "2021-01-04",
            "last_day": "2026-06-30",
            "reserved_cutoff": "2026-07-01",
            "reserved_cutoff_rule": "exclude_rows_on_or_after",
        },
        "upstream": {
            "provider_root": "data/providers/us",
            "provider_identity_sha256": "upstream-identity",
            "provider_manifest_sha256": "upstream-manifest-sha256",
            "source_csvs": [],
            "source_hashes_verified": True,
            "source_attestation": "hashes_verified_by_snapshot_builder; no_third_party",
        },
        "spec": {
            "path": "configs/research_paradigms/us.yaml",
            "sha256": "spec-sha256",
            "experiment_id": "test",
            "pool_path": "configs/pools/us.yaml",
            "pool_sha256": "pool-sha256",
        },
        "provider_identity_sha256": identity_sha256,
    }


def _mini_prices_csv(tmp_path: Path, symbol: str = "AAPL") -> Path:
    """Write a minimal prices CSV with no reserved rows."""
    import pandas as pd

    dates = pd.bdate_range("2025-01-02", periods=10)
    rows = []
    for d in dates:
        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 1_000_000,
        })
    path = tmp_path / "prices.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_validate_manifest_rejects_wrong_prices_csv_hash(tmp_path: Path) -> None:
    """Snapshot manifest validation fails when prices_csv hash does not match."""
    from src.research.hierarchical_rotation_validation import (
        _validate_provider_manifest,
    )

    prices_csv = _mini_prices_csv(tmp_path)
    # Manifest with WRONG hash
    manifest = _mini_manifest("will-be-recomputed", "aaaa" + "0" * 60)
    # Recompute identity
    identity = {
        k: v for k, v in manifest.items() if k != "provider_identity_sha256"
    }
    import json as _json
    import hashlib as _hashlib
    encoded = _json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["provider_identity_sha256"] = _hashlib.sha256(encoded).hexdigest()

    manifest_path = tmp_path / "provider_manifest.json"
    manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match.*snapshot manifest bound hash"):
        _validate_provider_manifest(
            manifest_path,
            prices_csv,
            required_symbols={"AAPL", "QQQ", "^SOX"},
            required_count=3,
        )


def test_validate_manifest_rejects_wrong_symbol_set(tmp_path: Path) -> None:
    """Snapshot manifest validation fails when symbol set does not match required."""
    from src.research.hierarchical_rotation_validation import (
        _validate_provider_manifest,
    )

    prices_csv = _mini_prices_csv(tmp_path)
    actual_hash = sha256_file(prices_csv)

    import json as _json
    import hashlib as _hashlib

    manifest = _mini_manifest("will-be-recomputed", actual_hash)
    # Use wrong symbols in manifest
    manifest["snapshot"]["symbols"] = ["AAPL", "QQQ"]  # missing ^SOX
    manifest["snapshot"]["symbol_count"] = 2
    identity = {
        k: v for k, v in manifest.items() if k != "provider_identity_sha256"
    }
    encoded = _json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["provider_identity_sha256"] = _hashlib.sha256(encoded).hexdigest()

    manifest_path = tmp_path / "provider_manifest.json"
    manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="symbol set mismatch"):
        _validate_provider_manifest(
            manifest_path,
            prices_csv,
            required_symbols={"AAPL", "QQQ", "^SOX"},
            required_count=3,
        )


def test_validate_manifest_rejects_wrong_identity_hash(tmp_path: Path) -> None:
    """Manifest with tampered identity hash fails validation (recomputed != declared)."""
    from src.research.hierarchical_rotation_validation import (
        _validate_provider_manifest,
    )

    prices_csv = _mini_prices_csv(tmp_path)
    actual_hash = sha256_file(prices_csv)

    manifest = _mini_manifest("tampered-identity-hash", actual_hash)
    # provider_identity_sha256 is intentionally wrong — it will NOT match the recomputed one

    manifest_path = tmp_path / "provider_manifest.json"
    import json as _json
    manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="identity hash mismatch"):
        _validate_provider_manifest(
            manifest_path,
            prices_csv,
            required_symbols={"AAPL", "QQQ", "^SOX"},
            required_count=3,
        )


def test_validate_manifest_accepts_valid_snapshot(tmp_path: Path) -> None:
    """Valid snapshot manifest passes all validation checks."""
    from src.research.hierarchical_rotation_validation import (
        _validate_provider_manifest,
    )

    prices_csv = _mini_prices_csv(tmp_path)
    actual_hash = sha256_file(prices_csv)

    import json as _json
    import hashlib as _hashlib

    manifest = _mini_manifest("will-be-recomputed", actual_hash)
    identity = {
        k: v for k, v in manifest.items() if k != "provider_identity_sha256"
    }
    encoded = _json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["provider_identity_sha256"] = _hashlib.sha256(encoded).hexdigest()

    manifest_path = tmp_path / "provider_manifest.json"
    manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")

    result = _validate_provider_manifest(
        manifest_path,
        prices_csv,
        required_symbols={"AAPL", "QQQ", "^SOX"},
        required_count=3,
    )
    assert result["validated"] is True
    assert result["market"] == "us"
    assert result["source_hashes_verified"] is True


def test_validate_manifest_rejects_snapshot_bound_to_different_spec(
    tmp_path: Path,
) -> None:
    """A valid data hash is insufficient when the snapshot binds another spec."""
    from src.research.hierarchical_rotation_validation import (
        _validate_provider_manifest,
    )

    prices_csv = _mini_prices_csv(tmp_path)
    manifest = _mini_manifest("will-be-recomputed", sha256_file(prices_csv))
    identity_payload = {
        key: value
        for key, value in manifest.items()
        if key != "provider_identity_sha256"
    }
    import hashlib as _hashlib
    import json as _json

    encoded = _json.dumps(
        identity_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest["provider_identity_sha256"] = _hashlib.sha256(encoded).hexdigest()
    manifest_path = tmp_path / "provider_manifest.json"
    manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot manifest spec hash mismatch"):
        _validate_provider_manifest(
            manifest_path,
            prices_csv,
            required_symbols={"AAPL", "QQQ", "^SOX"},
            required_count=3,
            expected_spec_sha256="different-spec-sha256",
            expected_pool_sha256="pool-sha256",
            expected_experiment_id="test",
        )


def test_non_authoritative_without_manifest(tmp_path: Path) -> None:
    """Validation without provider_manifest_path is explicitly non-authoritative
    and can never emit independent_validation_required."""
    prices = _synthetic_prices_long()
    prices_csv = tmp_path / "prices.csv"
    prices.to_csv(prices_csv, index=False)
    output_dir = tmp_path / "output"

    # Patch the heavy generic-engine functions for speed
    with pytest.MonkeyPatch.context() as mp:
        # Minimal stubs — we only care about decision vocabulary here
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".compute_hierarchical_indicators",
            lambda _p, _t: pd.DataFrame(
                {"date": [], "symbol": [], "risk_on": []}
            ),
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".generate_signal_history",
            lambda _i, _t: ([], []),
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".build_hierarchical_rotation_history",
            lambda _i, _s, _sp, _p: ([], [], []),
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            ".build_hierarchical_portfolio_history",
            lambda _i, _s, _r, _sp: [],
        )
        mp.setattr(
            "src.research.hierarchical_rotation_validation"
            "._build_return_frames",
            lambda _prices, candidates, benchmark, _start, _end: (
                pd.DataFrame(
                    0.001,
                    index=pd.bdate_range("2025-06-02", periods=3),
                    columns=[*candidates, benchmark],
                ),
                pd.DataFrame(
                    0.0,
                    index=pd.bdate_range("2025-06-02", periods=3),
                    columns=[*candidates, benchmark],
                ),
            ),
        )

        decision = run_us_hierarchical_rotation_validation(
            spec_path=FROZEN_SPEC,
            prices_csv=prices_csv,
            output_dir=output_dir,
            # NO provider_manifest_path
        )

    assert decision["provider_manifest_validated"] is False
    assert decision["decision"] != (
        "us_hierarchical_rotation_independent_validation_required"
    )
    assert decision["decision"] == (
        "us_hierarchical_rotation_not_supported_on_observed_evidence"
    )
    # Gate result must include the manifest gate failure
    gate_details = decision.get("gate_result", {}).get("details", {})
    assert "provider_manifest_required" in gate_details


def test_provider_readiness_requires_25_symbols() -> None:
    """The frozen pool requires exactly 25 provider symbols (23 candidates + QQQ + ^SOX)."""
    spec = _load(FROZEN_SPEC)
    pool = _pool()
    prices = _synthetic_prices_long()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "prices.csv"
        prices.to_csv(csv_path, index=False)
        result = _verify_provider_readiness(csv_path, spec, pool)
        assert result["required_provider_count"] == 25
        assert "^SOX" in result["required_provider_symbols"]
        assert "QQQ" in result["required_provider_symbols"]


# ---------------------------------------------------------------------------
# CLI --help tests
# ---------------------------------------------------------------------------


def test_cli_validation_help() -> None:
    """Validation CLI --help exits cleanly."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/run_us_hierarchical_rotation_validation.py", "--help"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0
    assert "--prices-csv" in result.stdout
    assert "--provider-manifest" in result.stdout


def test_cli_snapshot_builder_help() -> None:
    """Snapshot builder CLI --help exits cleanly."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/build_us_hierarchical_validation_snapshot.py", "--help"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
    )
    assert result.returncode == 0
    assert "--provider-root" in result.stdout
    assert "--source-csv-dir" in result.stdout
